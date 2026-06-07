"""
Author: L. Saetta
Date last modified: 2026-06-07
License: MIT
Description: OCI resource managers for Agent Factory knowledge base setup.
"""

from __future__ import annotations

# pylint: disable=too-few-public-methods,too-many-lines

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal, Mapping, Protocol

CONTROL_PLANE_AUTH_MODES = {"session", "user_principal"}
DEFAULT_OCI_PROFILE = "DEFAULT"
OCI_AUTH_MODE_ENV_VAR = "OCI_AUTH_MODE"


class ResourceProvisioningError(RuntimeError):
    """Raised when Agent Factory cannot create or resolve an OCI resource."""


class ObjectStorageClientProtocol(Protocol):
    """Minimal Object Storage client behavior used by Agent Factory."""

    def get_namespace(self) -> Any:
        """Return the Object Storage namespace response."""

    def get_bucket(self, namespace_name: str, bucket_name: str) -> Any:
        """Return an existing Object Storage bucket response."""

    def create_bucket(self, namespace_name: str, create_bucket_details: Any) -> Any:
        """Create an Object Storage bucket and return the response."""


class IdentityClientProtocol(Protocol):
    """Minimal OCI Identity client behavior used by Agent Factory."""

    def list_compartments(self, compartment_id: str, **kwargs: Any) -> Any:
        """Return compartments visible under a tenancy or parent compartment."""


class VectorStoreClientProtocol(Protocol):
    """Minimal control plane client behavior used by Agent Factory."""

    vector_stores: Any


class VectorStoreConnectorClientProtocol(Protocol):
    """Minimal OCI Generative AI client behavior used for connectors."""

    def list_vector_store_connectors(self, compartment_id: str) -> Any:
        """Return Vector Store connectors in a compartment."""

    def create_vector_store_connector(self, create_details: Any) -> Any:
        """Create a Vector Store connector and return the response."""


@dataclass(frozen=True)
class BucketResult:
    """Object Storage bucket provisioning result.

    Attributes:
        bucket_name: Name of the created or reused bucket.
        namespace_name: Object Storage namespace containing the bucket.
        lifecycle_state: Reported bucket lifecycle state when available.
        created: Whether the operation created a new bucket.
    """

    bucket_name: str
    namespace_name: str
    lifecycle_state: str | None
    created: bool


@dataclass(frozen=True)
class VectorStoreResult:
    """Vector Store provisioning result.

    Attributes:
        vector_store_id: Identifier of the created or reused Vector Store.
        name: Display name of the Vector Store when available.
        created: Whether the operation created a new Vector Store.
    """

    vector_store_id: str
    name: str
    created: bool


@dataclass(frozen=True)
class ConnectorResult:
    """Data Sync Connector provisioning result.

    Attributes:
        connector_id: Identifier of the created or reused connector.
        name: Display name of the connector.
        lifecycle_state: Reported connector lifecycle state when available.
        created: Whether the operation created a new connector.
        skipped: Whether connector provisioning was skipped.
    """

    connector_id: str
    name: str
    lifecycle_state: str | None
    created: bool
    skipped: bool = False


@dataclass(frozen=True)
class FoundationResourcesResult:
    """Provisioning result for resources created before deployment planning.

    Attributes:
        compartment_id: Resolved compartment OCID used by all resources.
        bucket: Object Storage bucket result.
        vector_store: Vector Store result.
        connector: Data Sync Connector result, or None when skipped.
    """

    compartment_id: str
    bucket: BucketResult
    vector_store: VectorStoreResult
    connector: ConnectorResult | None


class ObjectStorageBucketManager:
    """Create or reuse an OCI Object Storage bucket."""

    def __init__(self, client: ObjectStorageClientProtocol) -> None:
        """Initialize the manager.

        Args:
            client: OCI Object Storage client.
        """

        self._client = client

    def create_or_reuse(
        self,
        *,
        compartment_id: str,
        bucket_name: str,
        mode: str,
    ) -> BucketResult:
        """Create or resolve an Object Storage bucket.

        Args:
            compartment_id: Compartment OCID for bucket creation.
            bucket_name: Bucket name to create or reuse.
            mode: Resource mode, either `create` or `reuse`.

        Returns:
            BucketResult: Created or resolved bucket details.

        Raises:
            ResourceProvisioningError: If the bucket cannot be created or
                resolved, or if the mode is unsupported.
        """

        namespace_name = _response_data(self._client.get_namespace())
        existing_bucket = self._get_bucket_if_exists(namespace_name, bucket_name)

        if mode == "reuse":
            if existing_bucket is None:
                raise ResourceProvisioningError(
                    f"Object Storage bucket not found: {bucket_name}"
                )
            return _bucket_result(existing_bucket, namespace_name, created=False)

        if mode == "create":
            if existing_bucket is not None:
                return _bucket_result(existing_bucket, namespace_name, created=False)

            details = _build_create_bucket_details(
                compartment_id=compartment_id,
                bucket_name=bucket_name,
            )
            try:
                created_bucket = _response_data(
                    self._client.create_bucket(
                        namespace_name=namespace_name,
                        create_bucket_details=details,
                    )
                )
            except Exception as exc:  # pylint: disable=broad-exception-caught
                raise ResourceProvisioningError(
                    f"Unable to create Object Storage bucket {bucket_name}: {exc}"
                ) from exc
            return _bucket_result(created_bucket, namespace_name, created=True)

        raise ResourceProvisioningError(f"Unsupported bucket mode: {mode}")

    def _get_bucket_if_exists(
        self, namespace_name: str, bucket_name: str
    ) -> Any | None:
        """Return a bucket when it exists, otherwise return None.

        Args:
            namespace_name: Object Storage namespace.
            bucket_name: Bucket name to resolve.

        Returns:
            Any | None: Bucket model or None when OCI returns 404.

        Raises:
            ResourceProvisioningError: If OCI returns an unexpected error.
        """

        try:
            return _response_data(self._client.get_bucket(namespace_name, bucket_name))
        except Exception as exc:  # pylint: disable=broad-exception-caught
            if _exception_status(exc) == 404:
                return None
            raise ResourceProvisioningError(
                f"Unable to read Object Storage bucket {bucket_name}: {exc}"
            ) from exc


class VectorStoreManager:
    """Create or reuse an OCI Enterprise AI Vector Store."""

    def __init__(self, client: VectorStoreClientProtocol) -> None:
        """Initialize the manager.

        Args:
            client: OCI Enterprise AI control plane client.
        """

        self._client = client

    def create_or_reuse(self, *, name_or_id: str, mode: str) -> VectorStoreResult:
        """Create or resolve a Vector Store.

        Args:
            name_or_id: Vector Store name or OCID.
            mode: Resource mode, either `create` or `reuse`.

        Returns:
            VectorStoreResult: Created or resolved Vector Store details.

        Raises:
            ResourceProvisioningError: If the Vector Store cannot be created or
                resolved, or if the mode is unsupported.
        """

        if name_or_id.startswith("ocid1."):
            vector_store = self._retrieve_vector_store(name_or_id)
            return VectorStoreResult(
                vector_store_id=_resource_id(vector_store, fallback=name_or_id),
                name=_resource_name(vector_store, fallback=name_or_id),
                created=False,
            )

        existing_vector_store = self._find_vector_store_by_name(name_or_id)

        if mode == "reuse":
            if existing_vector_store is None:
                raise ResourceProvisioningError(f"Vector Store not found: {name_or_id}")
            return VectorStoreResult(
                vector_store_id=_resource_id(existing_vector_store),
                name=_resource_name(existing_vector_store, fallback=name_or_id),
                created=False,
            )

        if mode == "create":
            if existing_vector_store is not None:
                return VectorStoreResult(
                    vector_store_id=_resource_id(existing_vector_store),
                    name=_resource_name(existing_vector_store, fallback=name_or_id),
                    created=False,
                )

            vector_store = self._client.vector_stores.create(
                name=name_or_id,
                description="Vector Store for OCI RAG Agent Blueprint.",
                expires_after={"anchor": "last_active_at", "days": 120},
                metadata={"source": "oci-rag-agent-blueprint"},
            )
            return VectorStoreResult(
                vector_store_id=_resource_id(vector_store),
                name=_resource_name(vector_store, fallback=name_or_id),
                created=True,
            )

        raise ResourceProvisioningError(f"Unsupported Vector Store mode: {mode}")

    def _retrieve_vector_store(self, vector_store_id: str) -> Any:
        """Retrieve a Vector Store by identifier.

        Args:
            vector_store_id: Vector Store OCID.

        Returns:
            Any: Vector Store resource.

        Raises:
            ResourceProvisioningError: If the Vector Store cannot be retrieved.
        """

        retrieve = getattr(self._client.vector_stores, "retrieve", None)
        if retrieve is None:
            return {"id": vector_store_id, "name": vector_store_id}

        try:
            return retrieve(vector_store_id)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            raise ResourceProvisioningError(
                f"Unable to retrieve Vector Store {vector_store_id}: {exc}"
            ) from exc

    def _find_vector_store_by_name(self, vector_store_name: str) -> Any | None:
        """Find a Vector Store by name using the control plane list API.

        Args:
            vector_store_name: Vector Store display name.

        Returns:
            Any | None: Matching Vector Store or None.

        Raises:
            ResourceProvisioningError: If the list operation fails.
        """

        list_vector_stores = getattr(self._client.vector_stores, "list", None)
        if list_vector_stores is None:
            return None

        try:
            vector_stores_page = list_vector_stores()
        except Exception as exc:  # pylint: disable=broad-exception-caught
            raise ResourceProvisioningError(
                f"Unable to list Vector Stores: {exc}"
            ) from exc

        for vector_store in _iter_resources(vector_stores_page):
            if _resource_name(vector_store, fallback="") == vector_store_name:
                return vector_store
        return None


class VectorStoreConnectorManager:
    """Create, reuse, or skip an Object Storage Data Sync Connector."""

    def __init__(self, client: VectorStoreConnectorClientProtocol) -> None:
        """Initialize the manager.

        Args:
            client: OCI Generative AI control plane client.
        """

        self._client = client

    def create_reuse_or_skip(
        self,
        *,
        compartment_id: str,
        connector_name: str | None,
        mode: str,
        vector_store_id: str,
        namespace_name: str,
        bucket_name: str,
    ) -> ConnectorResult | None:
        # pylint: disable=too-many-arguments
        """Create, resolve, or skip a Data Sync Connector.

        Args:
            compartment_id: Compartment OCID containing the connector.
            connector_name: Connector display name or OCID.
            mode: Connector mode, `create`, `reuse`, or `skip`.
            vector_store_id: Target Vector Store OCID.
            namespace_name: Object Storage namespace for the source bucket.
            bucket_name: Object Storage bucket name.

        Returns:
            ConnectorResult | None: Connector details or None when skipped.

        Raises:
            ResourceProvisioningError: If connector provisioning fails.
        """

        if mode == "skip":
            return None

        if not connector_name:
            raise ResourceProvisioningError(
                "Connector name is required when connector mode is active."
            )

        if connector_name.startswith("ocid1."):
            connector = self._retrieve_connector(connector_name)
            return _connector_result(connector, fallback_name=connector_name)

        existing_connector = self._find_connector_by_name(
            compartment_id=compartment_id,
            connector_name=connector_name,
        )

        if mode == "reuse":
            if existing_connector is None:
                raise ResourceProvisioningError(
                    f"Connector not found: {connector_name}"
                )
            return _connector_result(existing_connector, fallback_name=connector_name)

        if mode == "create":
            if existing_connector is not None:
                return _connector_result(
                    existing_connector, fallback_name=connector_name
                )

            try:
                connector = _response_data(
                    self._client.create_vector_store_connector(
                        _build_create_connector_details(
                            compartment_id=compartment_id,
                            connector_name=connector_name,
                            vector_store_id=vector_store_id,
                            namespace_name=namespace_name,
                            bucket_name=bucket_name,
                        )
                    )
                )
            except Exception as exc:  # pylint: disable=broad-exception-caught
                raise ResourceProvisioningError(
                    f"Unable to create connector {connector_name}: {exc}"
                ) from exc
            return _connector_result(
                connector,
                fallback_name=connector_name,
                created=True,
            )

        raise ResourceProvisioningError(f"Unsupported connector mode: {mode}")

    def _retrieve_connector(self, connector_id: str) -> Any:
        """Retrieve a connector by OCID when the SDK supports it.

        Args:
            connector_id: Connector OCID.

        Returns:
            Any: Connector model or fallback dictionary.

        Raises:
            ResourceProvisioningError: If retrieval fails.
        """

        get_connector = getattr(self._client, "get_vector_store_connector", None)
        if get_connector is None:
            return {"id": connector_id, "display_name": connector_id}

        try:
            return _response_data(get_connector(connector_id))
        except Exception as exc:  # pylint: disable=broad-exception-caught
            raise ResourceProvisioningError(
                f"Unable to retrieve connector {connector_id}: {exc}"
            ) from exc

    def _find_connector_by_name(
        self, *, compartment_id: str, connector_name: str
    ) -> Any | None:
        """Find a connector by display name.

        Args:
            compartment_id: Compartment OCID to search.
            connector_name: Connector display name.

        Returns:
            Any | None: Matching connector or None.

        Raises:
            ResourceProvisioningError: If listing connectors fails.
        """

        try:
            connectors_page = self._client.list_vector_store_connectors(compartment_id)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            raise ResourceProvisioningError(
                f"Unable to list Vector Store connectors: {exc}"
            ) from exc

        for connector in _iter_resources(connectors_page):
            if _resource_display_name(connector, fallback="") == connector_name:
                return connector
        return None


def provision_foundation_resources(
    payload: dict[str, Any],
) -> FoundationResourcesResult:
    """Create or reuse knowledge base resources for a deployment.

    Args:
        payload: Normalized Agent Factory deployment payload.

    Returns:
        FoundationResourcesResult: Created or resolved resource details.

    Raises:
        ResourceProvisioningError: If required resource provisioning fails.
    """

    compartment_id = resolve_compartment_id(
        compartment=str(payload["compartment"]),
        region=str(payload["region"]),
    )

    bucket = ObjectStorageBucketManager(
        create_object_storage_client(region=str(payload["region"]))
    ).create_or_reuse(
        compartment_id=compartment_id,
        bucket_name=str(payload["bucket_name"]),
        mode=str(payload["bucket_mode"]),
    )
    vector_store = VectorStoreManager(
        create_control_plane_client(
            region=str(payload["region"]),
            compartment_id=compartment_id,
        )
    ).create_or_reuse(
        name_or_id=str(payload["vector_store_name"]),
        mode=str(payload["vector_store_mode"]),
    )
    connector = VectorStoreConnectorManager(
        create_oci_genai_client(region=str(payload["region"]))
    ).create_reuse_or_skip(
        compartment_id=compartment_id,
        connector_name=payload.get("connector_name"),
        mode=str(payload["connector_mode"]),
        vector_store_id=vector_store.vector_store_id,
        namespace_name=bucket.namespace_name,
        bucket_name=bucket.bucket_name,
    )
    return FoundationResourcesResult(
        compartment_id=compartment_id,
        bucket=bucket,
        vector_store=vector_store,
        connector=connector,
    )


def resolve_compartment_id(*, compartment: str, region: str) -> str:
    """Resolve a compartment name or OCID to a compartment OCID.

    Args:
        compartment: Compartment OCID or display name.
        region: OCI region for the Identity client.

    Returns:
        str: Resolved compartment OCID.

    Raises:
        ResourceProvisioningError: If the compartment name cannot be resolved
            uniquely.
    """

    if compartment.startswith("ocid1.compartment."):
        return compartment

    try:
        import oci  # pylint: disable=import-outside-toplevel
    except ImportError as exc:
        raise ResourceProvisioningError(
            "The oci package is required for compartment resolution."
        ) from exc

    profile_name = os.environ.get("OCI_PROFILE", DEFAULT_OCI_PROFILE)
    config = oci.config.from_file(profile_name=profile_name)
    config["region"] = region
    identity_client = oci.identity.IdentityClient(config)
    tenancy_id = str(config.get("tenancy") or "")
    if not tenancy_id:
        raise ResourceProvisioningError(
            f"OCI profile '{profile_name}' does not include a tenancy OCID."
        )
    return _resolve_compartment_name(
        identity_client=identity_client,
        tenancy_id=tenancy_id,
        compartment_name=compartment,
    )


def _resolve_compartment_name(
    *,
    identity_client: IdentityClientProtocol,
    tenancy_id: str,
    compartment_name: str,
) -> str:
    """Resolve a compartment name using OCI Identity.

    Args:
        identity_client: OCI Identity client.
        tenancy_id: Tenancy OCID used as list root.
        compartment_name: Compartment display name to resolve.

    Returns:
        str: Resolved compartment OCID.

    Raises:
        ResourceProvisioningError: If resolution fails or is ambiguous.
    """

    try:
        compartments = _iter_resources(
            identity_client.list_compartments(
                tenancy_id,
                compartment_id_in_subtree=True,
                access_level="ANY",
                lifecycle_state="ACTIVE",
                name=compartment_name,
            )
        )
    except Exception as exc:  # pylint: disable=broad-exception-caught
        raise ResourceProvisioningError(
            f"Unable to resolve compartment '{compartment_name}': {exc}"
        ) from exc

    matching_compartments = [
        compartment
        for compartment in compartments
        if _resource_name(compartment, fallback="") == compartment_name
    ]
    if not matching_compartments:
        raise ResourceProvisioningError(
            f"Compartment not found: {compartment_name}. Provide a compartment OCID "
            "or a unique visible compartment name."
        )
    if len(matching_compartments) > 1:
        raise ResourceProvisioningError(
            f"Multiple compartments named '{compartment_name}' were found. Provide "
            "the compartment OCID."
        )
    return _resource_id(matching_compartments[0])


def create_object_storage_client(*, region: str) -> Any:
    """Create an OCI Object Storage client from local OCI configuration.

    Args:
        region: OCI region for the client.

    Returns:
        Any: OCI Object Storage client.

    Raises:
        ResourceProvisioningError: If the OCI SDK is unavailable or misconfigured.
    """

    try:
        import oci  # pylint: disable=import-outside-toplevel
    except ImportError as exc:
        raise ResourceProvisioningError(
            "The oci package is required for Object Storage operations."
        ) from exc

    profile_name = os.environ.get("OCI_PROFILE", "DEFAULT")
    config = oci.config.from_file(profile_name=profile_name)
    config["region"] = region
    return oci.object_storage.ObjectStorageClient(config)


def create_control_plane_client(*, region: str, compartment_id: str) -> Any:
    """Create an OCI Enterprise AI control plane client.

    Args:
        region: OCI region for the control plane endpoint.
        compartment_id: Compartment OCID used by the control plane client.

    Returns:
        Any: OpenAI-compatible OCI control plane client.

    Raises:
        ResourceProvisioningError: If the OCI OpenAI package is unavailable or
            misconfigured.
    """

    try:
        import httpx  # pylint: disable=import-outside-toplevel
        from oci_genai_auth import (  # pylint: disable=import-outside-toplevel
            OciSessionAuth,
            OciUserPrincipalAuth,
        )
        from openai import OpenAI  # pylint: disable=import-outside-toplevel
    except ImportError as exc:
        raise ResourceProvisioningError(
            "The openai, httpx, and oci-genai-auth packages are required for "
            "Vector Store operations."
        ) from exc

    profile_name = os.environ.get("OCI_PROFILE", DEFAULT_OCI_PROFILE)
    auth_mode = _resolve_control_plane_auth_mode(os.environ.get(OCI_AUTH_MODE_ENV_VAR))
    auth = (
        OciSessionAuth(profile_name=profile_name)
        if auth_mode == "session"
        else OciUserPrincipalAuth(profile_name=profile_name)
    )
    _validate_control_plane_auth(auth=auth, auth_mode=auth_mode, profile=profile_name)
    base_url = (
        os.environ.get("OCI_CONTROL_PLANE_ENDPOINT")
        or f"https://generativeai.{region}.oci.oraclecloud.com/20231130"
    )
    return OpenAI(
        base_url=base_url,
        api_key="unused",
        http_client=httpx.Client(
            auth=auth,
            headers={"opc-compartment-id": compartment_id},
        ),
    )


def create_oci_genai_client(*, region: str) -> Any:  # pylint: disable=too-many-locals
    """Create an OCI Generative AI SDK client for connector operations.

    Args:
        region: OCI region for the Generative AI endpoint.

    Returns:
        Any: OCI Generative AI client.

    Raises:
        ResourceProvisioningError: If the OCI SDK or auth package is unavailable
            or misconfigured.
    """

    try:
        import oci  # pylint: disable=import-outside-toplevel
        from oci.auth.signers import (  # pylint: disable=import-outside-toplevel
            SecurityTokenSigner,
        )
        from oci.generative_ai import (  # pylint: disable=import-outside-toplevel
            GenerativeAiClient,
        )
        from oci.signer import (  # pylint: disable=import-outside-toplevel
            load_private_key_from_file,
        )
        from oci_genai_auth import (  # pylint: disable=import-outside-toplevel
            OciUserPrincipalAuth,
        )
    except ImportError as exc:
        raise ResourceProvisioningError(
            "The oci and oci-genai-auth packages are required for connector "
            "operations."
        ) from exc

    profile_name = os.environ.get("OCI_PROFILE", DEFAULT_OCI_PROFILE)
    auth_mode = _resolve_control_plane_auth_mode(os.environ.get(OCI_AUTH_MODE_ENV_VAR))
    config = oci.config.from_file(profile_name=profile_name)
    config["region"] = region
    try:
        _validate_oci_auth_config(
            config=config,
            auth_mode=auth_mode,
            profile=profile_name,
        )
    except ValueError as exc:
        raise ResourceProvisioningError(str(exc)) from exc
    client_kwargs: dict[str, Any] = {
        "config": config,
        "service_endpoint": f"https://generativeai.{region}.oci.oraclecloud.com",
    }

    if auth_mode == "session":
        token_file = str(config["security_token_file"])
        key_file = str(config["key_file"])
        with open(os.path.expanduser(token_file), encoding="utf-8") as token_handle:
            token = token_handle.read()
        private_key = load_private_key_from_file(os.path.expanduser(key_file))
        client_kwargs["signer"] = SecurityTokenSigner(token, private_key)
    else:
        client_kwargs["signer"] = OciUserPrincipalAuth(profile_name=profile_name).signer

    return GenerativeAiClient(**client_kwargs)


def _resolve_control_plane_auth_mode(
    auth_mode: str | None,
) -> Literal["session", "user_principal"]:
    """Resolve the control plane OCI authentication mode.

    Args:
        auth_mode: Optional raw auth mode from the environment.

    Returns:
        Literal["session", "user_principal"]: Normalized auth mode.

    Raises:
        ResourceProvisioningError: If the auth mode is unsupported.
    """

    resolved_auth_mode = (auth_mode or "user_principal").strip().lower()
    if resolved_auth_mode not in CONTROL_PLANE_AUTH_MODES:
        accepted_modes = "', '".join(sorted(CONTROL_PLANE_AUTH_MODES))
        raise ResourceProvisioningError(
            f"Invalid OCI auth mode '{resolved_auth_mode}'. Expected one of: "
            f"'{accepted_modes}'."
        )
    return resolved_auth_mode  # type: ignore[return-value]


def _validate_control_plane_auth(
    *,
    auth: Any,
    auth_mode: Literal["session", "user_principal"],
    profile: str,
) -> None:
    """Validate auth configuration when exposed by the auth helper.

    Args:
        auth: OCI auth helper.
        auth_mode: Resolved authentication mode.
        profile: OCI profile name.

    Raises:
        ResourceProvisioningError: If the profile is incompatible with the
            selected auth mode.
    """

    auth_config = getattr(auth, "config", None)
    if not isinstance(auth_config, Mapping):
        return
    try:
        _validate_oci_auth_config(
            config=auth_config,
            auth_mode=auth_mode,
            profile=profile,
        )
    except ValueError as exc:
        raise ResourceProvisioningError(str(exc)) from exc


def _validate_oci_auth_config(
    *,
    config: Mapping[str, Any],
    auth_mode: Literal["session", "user_principal"],
    profile: str,
) -> None:
    """Validate OCI profile coherence for control plane authentication.

    Args:
        config: OCI profile configuration.
        auth_mode: Selected authentication mode.
        profile: OCI profile name.

    Raises:
        ValueError: If the profile is incompatible with the auth mode.
    """

    if auth_mode == "session":
        if not config.get("security_token_file") or not config.get("key_file"):
            raise ValueError(
                f"OCI profile '{profile}' is not valid for session auth: "
                "missing 'security_token_file' and/or 'key_file'."
            )
        return

    missing = [key for key in ("user", "tenancy", "fingerprint") if not config.get(key)]
    if missing:
        missing_keys = ", ".join(missing)
        raise ValueError(
            f"OCI profile '{profile}' is not valid for user_principal auth: "
            f"missing required key(s): {missing_keys}."
        )

    if not config.get("key_file") and not config.get("key_content"):
        raise ValueError(
            f"OCI profile '{profile}' is not valid for user_principal auth: "
            "missing 'key_file' or 'key_content'."
        )

    if config.get("security_token_file"):
        raise ValueError(
            f"OCI profile '{profile}' looks like a session-auth profile "
            "('security_token_file' is set). Use OCI_AUTH_MODE=session or switch "
            "to an API-key profile for user_principal."
        )

    key_file = str(config.get("key_file") or "")
    normalized_key_file = os.path.expanduser(key_file).replace("\\", "/")
    if "/.oci/sessions/" in normalized_key_file:
        raise ValueError(
            f"OCI profile '{profile}' key_file points to a session key "
            f"({key_file}). Use OCI_AUTH_MODE=session or configure an API-key "
            "profile for user_principal."
        )


def _build_create_bucket_details(*, compartment_id: str, bucket_name: str) -> Any:
    """Build OCI SDK create-bucket details.

    Args:
        compartment_id: Compartment OCID where the bucket is created.
        bucket_name: Bucket name.

    Returns:
        Any: OCI SDK CreateBucketDetails model or a compatible dictionary.
    """

    try:
        import oci  # pylint: disable=import-outside-toplevel
    except ImportError:
        return {"compartment_id": compartment_id, "name": bucket_name}

    return oci.object_storage.models.CreateBucketDetails(
        compartment_id=compartment_id,
        name=bucket_name,
    )


def _build_create_connector_details(  # pylint: disable=too-many-locals
    *,
    compartment_id: str,
    connector_name: str,
    vector_store_id: str,
    namespace_name: str,
    bucket_name: str,
) -> Any:
    # pylint: disable=too-many-arguments
    """Build OCI SDK create-connector details.

    Args:
        compartment_id: Compartment OCID containing the connector.
        connector_name: Connector display name.
        vector_store_id: Target Vector Store OCID.
        namespace_name: Object Storage namespace.
        bucket_name: Object Storage bucket name.

    Returns:
        Any: OCI SDK CreateVectorStoreConnectorDetails model or a compatible
        dictionary.
    """

    time_start = datetime.now(timezone.utc) + timedelta(minutes=10)
    try:
        from oci.generative_ai.models import (  # pylint: disable=import-outside-toplevel
            CreateVectorStoreConnectorDetails,
            ObjectStorageConfig,
            OciObjectStorageConfiguration,
            ScheduleIntervalConfig,
        )
    except ImportError:
        return {
            "compartment_id": compartment_id,
            "vector_store_id": vector_store_id,
            "display_name": connector_name,
            "description": "Syncs documentation from Object Storage.",
            "configuration": {
                "storage_config_list": [
                    {
                        "namespace": namespace_name,
                        "bucket_name": bucket_name,
                        "prefix_list": [],
                    }
                ]
            },
            "schedule_config": {
                "config_type": "INTERVAL",
                "frequency": "HOURLY",
                "interval": 1,
                "state": "ENABLED",
                "time_start": time_start,
            },
        }

    return CreateVectorStoreConnectorDetails(
        compartment_id=compartment_id,
        vector_store_id=vector_store_id,
        display_name=connector_name,
        description="Syncs documentation from Object Storage.",
        configuration=OciObjectStorageConfiguration(
            storage_config_list=[
                ObjectStorageConfig(
                    namespace=namespace_name,
                    bucket_name=bucket_name,
                    prefix_list=[],
                )
            ]
        ),
        schedule_config=ScheduleIntervalConfig(
            config_type="INTERVAL",
            frequency="HOURLY",
            interval=1,
            state="ENABLED",
            time_start=time_start,
        ),
    )


def _bucket_result(bucket: Any, namespace_name: str, *, created: bool) -> BucketResult:
    """Convert an OCI bucket model to a provisioning result.

    Args:
        bucket: OCI bucket model or compatible dictionary.
        namespace_name: Object Storage namespace.
        created: Whether the bucket was created in this operation.

    Returns:
        BucketResult: Normalized bucket details.
    """

    return BucketResult(
        bucket_name=str(_resource_attr(bucket, "name", fallback="")),
        namespace_name=namespace_name,
        lifecycle_state=_optional_resource_attr(bucket, "lifecycle_state"),
        created=created,
    )


def _connector_result(
    connector: Any, *, fallback_name: str, created: bool = False
) -> ConnectorResult:
    """Convert an OCI connector model to a provisioning result.

    Args:
        connector: OCI connector model or compatible dictionary.
        fallback_name: Fallback connector display name.
        created: Whether the connector was created in this operation.

    Returns:
        ConnectorResult: Normalized connector details.
    """

    return ConnectorResult(
        connector_id=_resource_id(connector),
        name=_resource_display_name(connector, fallback=fallback_name),
        lifecycle_state=_optional_resource_attr(connector, "lifecycle_state"),
        created=created,
    )


def _response_data(response: Any) -> Any:
    """Return OCI response data when present.

    Args:
        response: OCI SDK response or raw resource.

    Returns:
        Any: Response data.
    """

    return getattr(response, "data", response)


def _iter_resources(page: Any) -> list[Any]:
    """Return resources from a list response.

    Args:
        page: Control plane list response.

    Returns:
        list[Any]: Resource values.
    """

    data = getattr(page, "data", page)
    items = getattr(data, "items", None)
    if items is not None:
        return list(items)
    if isinstance(data, list):
        return data
    if isinstance(data, tuple):
        return list(data)
    return list(getattr(data, "data", []) or [])


def _resource_id(resource: Any, fallback: str | None = None) -> str:
    """Return a resource identifier.

    Args:
        resource: Resource model or dictionary.
        fallback: Optional fallback identifier.

    Returns:
        str: Resource identifier.

    Raises:
        ResourceProvisioningError: If no identifier can be found.
    """

    value = _optional_resource_attr(resource, "id") or _optional_resource_attr(
        resource, "ocid"
    )
    if value:
        return value
    if fallback:
        return fallback
    raise ResourceProvisioningError("Resource response does not include an identifier.")


def _resource_name(resource: Any, fallback: str) -> str:
    """Return a resource name.

    Args:
        resource: Resource model or dictionary.
        fallback: Fallback name.

    Returns:
        str: Resource name.
    """

    return _optional_resource_attr(resource, "name") or fallback


def _resource_display_name(resource: Any, fallback: str) -> str:
    """Return a resource display name.

    Args:
        resource: Resource model or dictionary.
        fallback: Fallback display name.

    Returns:
        str: Resource display name.
    """

    return _optional_resource_attr(resource, "display_name") or _resource_name(
        resource,
        fallback=fallback,
    )


def _resource_attr(resource: Any, name: str, *, fallback: Any) -> Any:
    """Return a resource attribute from a model or dictionary.

    Args:
        resource: Resource model or dictionary.
        name: Attribute name.
        fallback: Value returned when the attribute is missing.

    Returns:
        Any: Attribute value or fallback.
    """

    value = _optional_resource_attr(resource, name)
    return fallback if value is None else value


def _optional_resource_attr(resource: Any, name: str) -> Any | None:
    """Return a resource attribute when available.

    Args:
        resource: Resource model or dictionary.
        name: Attribute name.

    Returns:
        Any | None: Attribute value or None.
    """

    if isinstance(resource, dict):
        return resource.get(name)
    return getattr(resource, name, None)


def _exception_status(exc: Exception) -> int | None:
    """Return an OCI-style exception status code when available.

    Args:
        exc: Exception raised by an OCI client.

    Returns:
        int | None: HTTP status code or None.
    """

    return getattr(exc, "status", None) or getattr(exc, "status_code", None)
