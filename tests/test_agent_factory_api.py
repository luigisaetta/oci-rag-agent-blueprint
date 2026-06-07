"""
Author: L. Saetta
Date last modified: 2026-06-07
License: MIT
Description: Unit tests for the Agent Factory FastAPI skeleton.
"""

from __future__ import annotations

# pylint: disable=too-few-public-methods

import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

AGENT_FACTORY_API_PATH = Path(__file__).resolve().parents[1] / "agent-factory" / "api"
sys.path.insert(0, str(AGENT_FACTORY_API_PATH))

from agent_factory_api.app import RUNS, app  # pylint: disable=wrong-import-position
from agent_factory_api.commands import (  # pylint: disable=wrong-import-position
    AGENT_RUNTIME_ENVIRONMENT_VARIABLES,
)
from agent_factory_api.resources import (  # pylint: disable=wrong-import-position
    BucketResult,
    ConnectorResult,
    FoundationResourcesResult,
    ObjectStorageBucketManager,
    ResourceProvisioningError,
    VectorStoreConnectorManager,
    VectorStoreManager,
    VectorStoreResult,
    _build_control_plane_base_url,
    _load_oci_config,
    _resolve_compartment_name,
    _resolve_control_plane_auth_mode,
    _validate_oci_auth_config,
)


def test_agent_factory_health_endpoint() -> None:
    """Test Agent Factory health endpoint."""

    client = TestClient(app)

    response = client.get("/factory/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_agent_factory_dry_run_generates_redacted_command_plan() -> None:
    """Test dry-run deployment planning without secret exposure."""

    RUNS.clear()
    client = TestClient(app)

    response = client.post("/factory/deployments", json=_valid_payload())

    assert response.status_code == 201
    payload = response.json()
    assert payload["dry_run"] is True
    assert payload["status"] == "succeeded"
    assert payload["request"]["openai_api_key"] == "********"
    assert "test-api-key" not in response.text
    assert "docker build --platform linux/amd64" in payload["commands_text"]
    assert "docker manifest inspect" in payload["commands_text"]
    assert "hosted-application-collection list-hosted-applications" in (
        payload["commands_text"]
    )
    assert "hosted-deployment create" in payload["commands_text"]
    assert "--active-artifact" in payload["commands_text"]
    assert (
        payload["outputs"]["image_reference"] == "fra.ocir.io/<tenancy-namespace>/"
        "oci-rag-agent-blueprint-agent:0.1.0"
    )
    runtime_environment = payload["outputs"]["runtime_environment"]
    assert set(runtime_environment) == set(AGENT_RUNTIME_ENVIRONMENT_VARIABLES)
    assert payload["outputs"]["resolved_identifiers"] == {
        "compartment_id": "ocid1.compartment.oc1..example",
        "vector_store_id": "<created-or-resolved-vector-store-ocid>",
        "connector_id": "<created-or-resolved-data-sync-connector-ocid>",
    }
    assert runtime_environment["OCI_REGION"] == "eu-frankfurt-1"
    assert runtime_environment["OCI_COMPARTMENT_ID"] == (
        "ocid1.compartment.oc1..example"
    )
    assert runtime_environment["OCI_PROJECT_ID"] == (
        "ocid1.generativeaiproject.oc1..example"
    )
    assert runtime_environment["OCI_MODEL_ID"] == "openai.gpt-5.4"
    assert runtime_environment["OCI_VECTOR_STORE_ID"] == (
        "<created-or-resolved-vector-store-ocid>"
    )
    assert runtime_environment["OPENAI_API_KEY"] == "********"
    assert runtime_environment["FILE_SEARCH_MAX_NUM_RESULTS"] == "10"
    assert runtime_environment["RESPONSES_TIMEOUT_SECONDS"] == "60"
    assert runtime_environment["STREAM_FINALIZATION_MODE"] == "never"
    dry_run_artifacts = payload["outputs"]["dry_run_artifacts"]
    assert set(dry_run_artifacts) == {
        "create-hosted-application.json",
        "create-hosted-deployment.json",
        "hosted-application-environment-variables.json",
        "hosted-application-inbound-auth-config.json",
        "hosted-application-networking-config.json",
        "hosted-deployment-active-artifact.json",
    }
    assert dry_run_artifacts["hosted-application-inbound-auth-config.json"] == {
        "inboundAuthConfigType": "NO_AUTH_CONFIG"
    }
    assert dry_run_artifacts["hosted-application-networking-config.json"] == {
        "inboundNetworkingConfig": {"endpointMode": "PUBLIC"},
        "outboundNetworkingConfig": {"networkMode": "MANAGED"},
    }
    assert dry_run_artifacts["hosted-deployment-active-artifact.json"] == {
        "artifactType": "SIMPLE_DOCKER_ARTIFACT",
        "containerUri": (
            "fra.ocir.io/<tenancy-namespace>/oci-rag-agent-blueprint-agent"
        ),
        "tag": "0.1.0",
    }
    assert any(step["step_id"] == "docker-build" for step in payload["steps"])
    assert any(step["step_id"] == "runtime-environment" for step in payload["steps"])


def test_agent_factory_resolves_names_before_downstream_commands() -> None:
    """Test names are converted to OCID placeholders for downstream commands."""

    RUNS.clear()
    client = TestClient(app)
    request_payload = _valid_payload()
    request_payload["compartment"] = "lsaetta"

    response = client.post("/factory/deployments", json=request_payload)

    assert response.status_code == 201
    payload = response.json()
    commands = payload["commands"]
    assert commands[0] == [
        "oci",
        "--region",
        "eu-frankfurt-1",
        "--output",
        "json",
        "iam",
        "compartment",
        "list",
        "--name",
        "lsaetta",
        "--compartment-id-in-subtree",
        "true",
        "--access-level",
        "ANY",
        "--include-root",
        "--all",
    ]
    assert payload["outputs"]["resolved_identifiers"]["compartment_id"] == (
        "<resolved-compartment-ocid>"
    )
    assert payload["outputs"]["runtime_environment"]["OCI_COMPARTMENT_ID"] == (
        "<resolved-compartment-ocid>"
    )
    assert (
        payload["outputs"]["dry_run_artifacts"]["create-hosted-application.json"][
            "compartmentId"
        ]
        == "<resolved-compartment-ocid>"
    )
    assert (
        payload["outputs"]["dry_run_artifacts"]["create-hosted-deployment.json"][
            "compartmentId"
        ]
        == "<resolved-compartment-ocid>"
    )
    assert "--compartment-id '<resolved-compartment-ocid>'" in (
        payload["commands_text"]
    )


def test_agent_factory_rejects_unsupported_options() -> None:
    """Test first-version disabled options are rejected."""

    client = TestClient(app)
    request_payload = _valid_payload()
    request_payload["jwt_protection_enabled"] = True
    request_payload["endpoint_visibility"] = "private"
    request_payload["network_mode"] = "custom"

    response = client.post("/factory/deployments", json=request_payload)

    assert response.status_code == 400
    field_errors = response.json()["field_errors"]
    assert "jwt_protection_enabled" in field_errors
    assert "endpoint_visibility" in field_errors
    assert "network_mode" in field_errors


def test_agent_factory_rejects_unknown_region_and_model() -> None:
    """Test region and model are restricted to guided choices."""

    client = TestClient(app)
    request_payload = _valid_payload()
    request_payload["region"] = "ap-mars-1"
    request_payload["model_id"] = "not-a-supported-model"

    response = client.post("/factory/deployments", json=request_payload)

    assert response.status_code == 400
    field_errors = response.json()["field_errors"]
    assert field_errors["region"] == ("Expected one of: eu-frankfurt-1, us-chicago-1.")
    assert field_errors["model_id"] == (
        "Expected one of: google.gemini-2.5-pro, openai.gpt-5.4, "
        "openai.gpt-oss-120b."
    )


def test_agent_factory_uses_region_key_for_ocir_registry() -> None:
    """Test OCIR image references use the OCI region key, not region name."""

    RUNS.clear()
    client = TestClient(app)
    request_payload = _valid_payload()
    request_payload["region"] = "us-chicago-1"
    request_payload["model_id"] = "google.gemini-2.5-pro"

    response = client.post("/factory/deployments", json=request_payload)

    assert response.status_code == 201
    payload = response.json()
    assert payload["outputs"]["image_reference"] == (
        "ord.ocir.io/<tenancy-namespace>/oci-rag-agent-blueprint-agent:0.1.0"
    )
    assert "docker login ord.ocir.io" in payload["commands_text"]
    assert payload["outputs"]["runtime_environment"]["OCI_REGION"] == "us-chicago-1"
    assert payload["outputs"]["runtime_environment"]["OCI_MODEL_ID"] == (
        "google.gemini-2.5-pro"
    )


def test_agent_factory_rejects_connector_without_name() -> None:
    """Test connector name is required when connector mode is active."""

    client = TestClient(app)
    request_payload = _valid_payload()
    request_payload["connector_name"] = ""

    response = client.post("/factory/deployments", json=request_payload)

    assert response.status_code == 400
    assert "connector_name" in response.json()["field_errors"]


def test_agent_factory_returns_saved_run_and_commands() -> None:
    """Test deployment run status and command script endpoints."""

    RUNS.clear()
    client = TestClient(app)

    create_response = client.post("/factory/deployments", json=_valid_payload())
    deployment_run_id = create_response.json()["deployment_run_id"]

    status_response = client.get(f"/factory/deployments/{deployment_run_id}")
    commands_response = client.get(f"/factory/deployments/{deployment_run_id}/commands")

    assert status_response.status_code == 200
    assert commands_response.status_code == 200
    assert commands_response.text.startswith("#!/usr/bin/env bash")


def test_agent_factory_apply_plan_passes_runtime_environment_to_deployment(
    monkeypatch,
) -> None:
    """Test real deployment command plan includes runtime environment injection."""

    RUNS.clear()
    client = TestClient(app)
    request_payload = _valid_payload()
    request_payload["dry_run"] = False
    request_payload["vector_store_name"] = "ocid1.vectorstore.oc1..example"
    monkeypatch.setattr(
        "agent_factory_api.app.provision_foundation_resources",
        lambda payload: FoundationResourcesResult(
            compartment_id=payload["compartment"],
            bucket=BucketResult(
                bucket_name=payload["bucket_name"],
                namespace_name="test-namespace",
                lifecycle_state="ACTIVE",
                created=False,
            ),
            vector_store=VectorStoreResult(
                vector_store_id="ocid1.vectorstore.oc1..example",
                name="ocid1.vectorstore.oc1..example",
                created=False,
            ),
            connector=ConnectorResult(
                connector_id="ocid1.vectorstoreconnector.oc1..example",
                name="agent-factory-connector",
                lifecycle_state="ACTIVE",
                created=False,
            ),
        ),
    )

    response = client.post("/factory/deployments", json=request_payload)

    assert response.status_code == 201
    payload = response.json()
    assert "--environment-variables" in payload["commands_text"]
    assert "hosted-application-environment-variables.json" in (payload["commands_text"])
    assert "hosted-deployment create" in payload["commands_text"]
    runtime_environment = payload["outputs"]["runtime_environment"]
    assert payload["outputs"]["resolved_identifiers"]["vector_store_id"] == (
        "ocid1.vectorstore.oc1..example"
    )
    assert (
        runtime_environment["OCI_VECTOR_STORE_ID"] == "ocid1.vectorstore.oc1..example"
    )
    assert runtime_environment["OPENAI_API_KEY"] == "********"
    assert "test-api-key" not in response.text
    environment_artifact = payload["outputs"]["dry_run_artifacts"][
        "hosted-application-environment-variables.json"
    ]
    environment_by_name = {item["name"]: item for item in environment_artifact}
    assert environment_by_name["OPENAI_API_KEY"] == {
        "name": "OPENAI_API_KEY",
        "type": "PLAINTEXT",
        "value": "********",
    }


def test_agent_factory_apply_provisions_bucket_and_vector_store(monkeypatch) -> None:
    """Test non-dry-run deployments provision foundation resources first."""

    RUNS.clear()
    client = TestClient(app)
    request_payload = _valid_payload()
    request_payload["dry_run"] = False

    def fake_provision(payload: dict[str, Any]) -> FoundationResourcesResult:
        assert payload["bucket_name"] == "agent-factory-docs"
        assert payload["vector_store_name"] == "agent-factory-vector-store"
        return FoundationResourcesResult(
            compartment_id="ocid1.compartment.oc1..example",
            bucket=BucketResult(
                bucket_name="agent-factory-docs",
                namespace_name="test-namespace",
                lifecycle_state="ACTIVE",
                created=True,
            ),
            vector_store=VectorStoreResult(
                vector_store_id="ocid1.vectorstore.oc1..created",
                name="agent-factory-vector-store",
                created=True,
            ),
            connector=ConnectorResult(
                connector_id="ocid1.vectorstoreconnector.oc1..created",
                name="agent-factory-connector",
                lifecycle_state="ACTIVE",
                created=True,
            ),
        )

    monkeypatch.setattr(
        "agent_factory_api.app.provision_foundation_resources",
        fake_provision,
    )

    response = client.post("/factory/deployments", json=request_payload)

    assert response.status_code == 201
    payload = response.json()
    assert payload["status"] == "succeeded"
    assert payload["outputs"]["resolved_identifiers"]["compartment_id"] == (
        "ocid1.compartment.oc1..example"
    )
    assert payload["outputs"]["resolved_identifiers"]["vector_store_id"] == (
        "ocid1.vectorstore.oc1..created"
    )
    assert payload["outputs"]["runtime_environment"]["OCI_VECTOR_STORE_ID"] == (
        "ocid1.vectorstore.oc1..created"
    )
    assert payload["outputs"]["resolved_identifiers"]["connector_id"] == (
        "ocid1.vectorstoreconnector.oc1..created"
    )
    assert payload["outputs"]["foundation_resources"]["compartment_id"] == (
        "ocid1.compartment.oc1..example"
    )
    assert payload["outputs"]["foundation_resources"]["bucket"] == {
        "bucket_name": "agent-factory-docs",
        "namespace_name": "test-namespace",
        "lifecycle_state": "ACTIVE",
        "created": True,
    }
    assert payload["outputs"]["foundation_resources"]["connector"] == {
        "connector_id": "ocid1.vectorstoreconnector.oc1..created",
        "name": "agent-factory-connector",
        "lifecycle_state": "ACTIVE",
        "created": True,
        "skipped": False,
    }


def test_agent_factory_apply_uses_resolved_compartment_id(monkeypatch) -> None:
    """Test non-dry-run planning uses the live resolved compartment OCID."""

    RUNS.clear()
    client = TestClient(app)
    request_payload = _valid_payload()
    request_payload["dry_run"] = False
    request_payload["compartment"] = "lsaetta"

    def fake_provision(payload: dict[str, Any]) -> FoundationResourcesResult:
        assert payload["compartment"] == "lsaetta"
        return FoundationResourcesResult(
            compartment_id="ocid1.compartment.oc1..resolved",
            bucket=BucketResult(
                bucket_name=payload["bucket_name"],
                namespace_name="test-namespace",
                lifecycle_state="ACTIVE",
                created=False,
            ),
            vector_store=VectorStoreResult(
                vector_store_id="ocid1.vectorstore.oc1..created",
                name=payload["vector_store_name"],
                created=True,
            ),
            connector=ConnectorResult(
                connector_id="ocid1.vectorstoreconnector.oc1..created",
                name=payload["connector_name"],
                lifecycle_state="ACTIVE",
                created=True,
            ),
        )

    monkeypatch.setattr(
        "agent_factory_api.app.provision_foundation_resources",
        fake_provision,
    )

    response = client.post("/factory/deployments", json=request_payload)

    assert response.status_code == 201
    payload = response.json()
    assert payload["outputs"]["resolved_identifiers"]["compartment_id"] == (
        "ocid1.compartment.oc1..resolved"
    )
    assert payload["outputs"]["runtime_environment"]["OCI_COMPARTMENT_ID"] == (
        "ocid1.compartment.oc1..resolved"
    )
    assert (
        payload["outputs"]["dry_run_artifacts"]["create-hosted-application.json"][
            "compartmentId"
        ]
        == "ocid1.compartment.oc1..resolved"
    )


def test_object_storage_bucket_manager_creates_missing_bucket() -> None:
    """Test Object Storage bucket creation through the OCI client."""

    client = FakeObjectStorageClient()
    manager = ObjectStorageBucketManager(client)

    result = manager.create_or_reuse(
        compartment_id="ocid1.compartment.oc1..example",
        bucket_name="agent-factory-docs",
        mode="create",
    )

    assert result == BucketResult(
        bucket_name="agent-factory-docs",
        namespace_name="test-namespace",
        lifecycle_state="ACTIVE",
        created=True,
    )
    assert client.created_bucket_details is not None


def test_vector_store_manager_creates_missing_vector_store() -> None:
    """Test Vector Store creation through the control plane client."""

    client = FakeControlPlaneClient()
    manager = VectorStoreManager(client)

    result = manager.create_or_reuse(
        name_or_id="agent-factory-vector-store",
        mode="create",
    )

    assert result == VectorStoreResult(
        vector_store_id="ocid1.vectorstore.oc1..created",
        name="agent-factory-vector-store",
        created=True,
    )
    assert client.vector_stores.created_payload == {
        "name": "agent-factory-vector-store",
        "description": "Vector Store for OCI RAG Agent Blueprint.",
        "expires_after": {"anchor": "last_active_at", "days": 120},
        "metadata": {"source": "oci-rag-agent-blueprint"},
    }


def test_vector_store_manager_create_requires_list_lookup() -> None:
    """Test create mode fails clearly when lookup is unavailable."""

    client = FakeControlPlaneClient(
        list_error=RuntimeError("404 NotAuthorizedOrNotFound")
    )
    manager = VectorStoreManager(client)

    with pytest.raises(ResourceProvisioningError, match="Unable to list Vector Stores"):
        manager.create_or_reuse(
            name_or_id="agent-factory-vector-store",
            mode="create",
        )
    assert client.vector_stores.created_payload is None


def test_vector_store_manager_reuse_requires_list_lookup() -> None:
    """Test reuse mode fails clearly when lookup is unavailable."""

    client = FakeControlPlaneClient(
        list_error=RuntimeError("404 NotAuthorizedOrNotFound")
    )
    manager = VectorStoreManager(client)

    with pytest.raises(ResourceProvisioningError, match="Unable to list Vector Stores"):
        manager.create_or_reuse(
            name_or_id="agent-factory-vector-store",
            mode="reuse",
        )


def test_vector_store_manager_wraps_create_errors() -> None:
    """Test create failures are returned as managed provisioning errors."""

    client = FakeControlPlaneClient(create_error=RuntimeError("create failed"))
    manager = VectorStoreManager(client)

    with pytest.raises(
        ResourceProvisioningError, match="Unable to create Vector Store"
    ):
        manager.create_or_reuse(
            name_or_id="agent-factory-vector-store",
            mode="create",
        )


def test_connector_manager_creates_object_storage_connector() -> None:
    """Test connector creation through the OCI Generative AI client."""

    client = FakeConnectorClient()
    manager = VectorStoreConnectorManager(client)

    result = manager.create_reuse_or_skip(
        compartment_id="ocid1.compartment.oc1..example",
        connector_name="agent-factory-connector",
        mode="create",
        vector_store_id="ocid1.vectorstore.oc1..created",
        namespace_name="test-namespace",
        bucket_name="agent-factory-docs",
    )

    assert result == ConnectorResult(
        connector_id="ocid1.vectorstoreconnector.oc1..created",
        name="agent-factory-connector",
        lifecycle_state="ACTIVE",
        created=True,
    )
    assert client.created_details is not None
    assert client.created_details.compartment_id == "ocid1.compartment.oc1..example"
    assert client.created_details.vector_store_id == "ocid1.vectorstore.oc1..created"
    assert client.created_details.display_name == "agent-factory-connector"
    storage_config = client.created_details.configuration.storage_config_list[0]
    assert storage_config.namespace == "test-namespace"
    assert storage_config.bucket_name == "agent-factory-docs"
    assert storage_config.prefix_list == []
    assert client.created_details.schedule_config.frequency == "HOURLY"
    assert client.created_details.schedule_config.state == "ENABLED"


def test_control_plane_auth_mode_defaults_to_user_principal() -> None:
    """Test control plane auth mode defaults to user principal."""

    assert _resolve_control_plane_auth_mode(None) == "user_principal"
    assert _resolve_control_plane_auth_mode(" session ") == "session"


def test_control_plane_base_url_matches_agent_hub_pattern() -> None:
    """Test control plane endpoint includes the OpenAI-compatible API path."""

    assert _build_control_plane_base_url(region="eu-frankfurt-1") == (
        "https://generativeai.eu-frankfurt-1.oci.oraclecloud.com/20231130/openai/v1"
    )


def test_control_plane_auth_config_rejects_session_profile_for_user_principal() -> None:
    """Test user principal auth rejects OCI session-token profiles."""

    try:
        _validate_oci_auth_config(
            config={
                "user": "ocid1.user.oc1..example",
                "tenancy": "ocid1.tenancy.oc1..example",
                "fingerprint": "aa:bb",
                "key_file": "~/.oci/sessions/test/oci_api_key.pem",
                "security_token_file": "~/.oci/sessions/test/token",
            },
            auth_mode="user_principal",
            profile="DEFAULT",
        )
    except ValueError as exc:
        assert "Use OCI_AUTH_MODE=session" in str(exc)
    else:
        raise AssertionError("Expected session profile validation to fail.")


def test_resolve_compartment_name_returns_unique_active_match() -> None:
    """Test compartment name resolution returns the matching OCID."""

    client = FakeIdentityClient(
        [
            {"id": "ocid1.compartment.oc1..resolved", "name": "lsaetta"},
        ]
    )

    compartment_id = _resolve_compartment_name(
        identity_client=client,
        tenancy_id="ocid1.tenancy.oc1..example",
        compartment_name="lsaetta",
    )

    assert compartment_id == "ocid1.compartment.oc1..resolved"
    assert client.list_kwargs == {
        "compartment_id_in_subtree": True,
        "access_level": "ANY",
        "lifecycle_state": "ACTIVE",
        "name": "lsaetta",
    }


def test_load_oci_config_reports_missing_config_as_provisioning_error(
    monkeypatch,
) -> None:
    """Test missing OCI config is returned as a managed provisioning error."""

    monkeypatch.setenv("OCI_CONFIG_FILE", "/tmp/missing-oci-config")

    try:
        _load_oci_config(region="eu-frankfurt-1")
    except ResourceProvisioningError as exc:
        assert "Unable to load OCI config profile" in str(exc)
        assert "/tmp/missing-oci-config" in str(exc)
    else:
        raise AssertionError("Expected missing OCI config to fail.")


def _valid_payload() -> dict[str, Any]:
    """Build a valid Agent Factory deployment request.

    Returns:
        dict[str, Any]: Valid deployment payload.
    """

    return {
        "compartment": "ocid1.compartment.oc1..example",
        "region": "eu-frankfurt-1",
        "bucket_mode": "create",
        "bucket_name": "agent-factory-docs",
        "vector_store_mode": "create",
        "vector_store_name": "agent-factory-vector-store",
        "connector_mode": "create",
        "connector_name": "agent-factory-connector",
        "hosted_application_name": "agent-factory-app",
        "deployment_name": "agent-factory-deployment",
        "jwt_protection_enabled": False,
        "endpoint_visibility": "public",
        "network_mode": "oracle_managed",
        "genai_project_ocid": "ocid1.generativeaiproject.oc1..example",
        "model_id": "openai.gpt-5.4",
        "openai_api_key": "test-api-key",
        "file_search_max_num_results": 10,
        "responses_timeout_seconds": 60,
        "stream_finalization_mode": "never",
        "container_repository_name": "oci-rag-agent-blueprint-agent",
        "container_image_tag": "0.1.0",
        "dry_run": True,
    }


class FakeResponse:
    """Small OCI-style response wrapper for tests."""

    def __init__(self, data: Any) -> None:
        """Initialize the fake response.

        Args:
            data: Wrapped response data.
        """

        self.data = data


class FakeListData:
    """Small OCI-style list data wrapper for tests."""

    def __init__(self, items: list[Any]) -> None:
        """Initialize the fake list data.

        Args:
            items: Wrapped list items.
        """

        self.items = items


class FakeNotFoundError(Exception):
    """Small OCI-style 404 exception for tests."""

    status = 404


class FakeObjectStorageClient:
    """Fake Object Storage client used by bucket manager tests."""

    def __init__(self) -> None:
        """Initialize the fake client."""

        self.created_bucket_details: Any | None = None

    def get_namespace(self) -> FakeResponse:
        """Return a fake namespace response.

        Returns:
            FakeResponse: Namespace response.
        """

        return FakeResponse("test-namespace")

    def get_bucket(self, namespace_name: str, bucket_name: str) -> FakeResponse:
        """Raise 404 to simulate a missing bucket.

        Args:
            namespace_name: Object Storage namespace.
            bucket_name: Bucket name.

        Raises:
            FakeNotFoundError: Always raised for this fake.
        """

        raise FakeNotFoundError(f"{namespace_name}/{bucket_name}")

    def create_bucket(
        self, namespace_name: str, create_bucket_details: Any
    ) -> FakeResponse:
        """Create a fake bucket.

        Args:
            namespace_name: Object Storage namespace.
            create_bucket_details: OCI SDK create details.

        Returns:
            FakeResponse: Bucket response.
        """

        self.created_bucket_details = create_bucket_details
        return FakeResponse(
            {
                "name": "agent-factory-docs",
                "namespace": namespace_name,
                "lifecycle_state": "ACTIVE",
            }
        )


class FakeIdentityClient:
    """Fake OCI Identity client used by compartment resolver tests."""

    def __init__(self, compartments: list[dict[str, str]]) -> None:
        """Initialize the fake client.

        Args:
            compartments: Compartments returned by list calls.
        """

        self.compartments = compartments
        self.list_kwargs: dict[str, Any] | None = None

    def list_compartments(self, compartment_id: str, **kwargs: Any) -> FakeResponse:
        """Return fake compartments.

        Args:
            compartment_id: Tenancy OCID.
            kwargs: List filter arguments.

        Returns:
            FakeResponse: Compartment list response.
        """

        assert compartment_id == "ocid1.tenancy.oc1..example"
        self.list_kwargs = kwargs
        return FakeResponse(self.compartments)


class FakeVectorStores:
    """Fake Vector Stores control plane API."""

    def __init__(
        self,
        *,
        list_error: Exception | None = None,
        create_error: Exception | None = None,
    ) -> None:
        """Initialize the fake API."""

        self.created_payload: dict[str, Any] | None = None
        self._list_error = list_error
        self._create_error = create_error

    def list(self) -> FakeResponse:
        """Return no Vector Stores.

        Returns:
            FakeResponse: Empty Vector Store list response.
        """

        if self._list_error is not None:
            raise self._list_error
        return FakeResponse([])

    def create(
        self,
        *,
        name: str,
        description: str,
        expires_after: dict[str, Any],
        metadata: dict[str, str],
    ) -> dict[str, str]:
        """Create a fake Vector Store.

        Args:
            name: Vector Store name.
            description: Vector Store description.
            expires_after: Expiration policy.
            metadata: Vector Store metadata.

        Returns:
            dict[str, str]: Fake Vector Store resource.
        """

        if self._create_error is not None:
            raise self._create_error
        self.created_payload = {
            "name": name,
            "description": description,
            "expires_after": expires_after,
            "metadata": metadata,
        }
        return {"id": "ocid1.vectorstore.oc1..created", "name": name}


class FakeControlPlaneClient:
    """Fake OCI Enterprise AI control plane client."""

    def __init__(
        self,
        *,
        list_error: Exception | None = None,
        create_error: Exception | None = None,
    ) -> None:
        """Initialize the fake client."""

        self.vector_stores = FakeVectorStores(
            list_error=list_error,
            create_error=create_error,
        )


class FakeConnectorClient:
    """Fake OCI Generative AI client used by connector manager tests."""

    def __init__(self) -> None:
        """Initialize the fake client."""

        self.created_details: Any | None = None

    def list_vector_store_connectors(self, compartment_id: str) -> FakeResponse:
        """Return no existing connectors.

        Args:
            compartment_id: Compartment OCID.

        Returns:
            FakeResponse: Empty connector list response.
        """

        assert compartment_id == "ocid1.compartment.oc1..example"
        return FakeResponse(FakeListData([]))

    def create_vector_store_connector(self, create_details: Any) -> FakeResponse:
        """Create a fake connector.

        Args:
            create_details: OCI SDK create connector details.

        Returns:
            FakeResponse: Connector response.
        """

        self.created_details = create_details
        return FakeResponse(
            {
                "id": "ocid1.vectorstoreconnector.oc1..created",
                "display_name": "agent-factory-connector",
                "lifecycle_state": "ACTIVE",
            }
        )
