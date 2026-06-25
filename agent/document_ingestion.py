"""
Author: L. Saetta
Date last modified: 2026-06-25
License: MIT
Description: Server-side document ingestion orchestration for the RAG agent.
"""

from __future__ import annotations

# pylint: disable=too-many-instance-attributes

from dataclasses import dataclass
from os import environ
from typing import Any, BinaryIO, Iterable

from agent.config import load_optional_choice_env, load_optional_int_env
from management.document_ingestion import (
    GenerativeAiClientProtocol,
    ObjectStorageClientProtocol,
    build_object_name,
    format_error,
    object_exists,
    trigger_file_sync,
)

DOCUMENT_INGESTION_ENABLED_DEFAULT = False
DOCUMENT_INGESTION_MAX_FILES_DEFAULT = 10
DOCUMENT_INGESTION_MAX_FILES_MIN = 1
DOCUMENT_INGESTION_MAX_FILES_MAX = 100
DOCUMENT_INGESTION_MAX_FILE_SIZE_MB_DEFAULT = 25
DOCUMENT_INGESTION_MAX_FILE_SIZE_MB_MIN = 1
DOCUMENT_INGESTION_MAX_FILE_SIZE_MB_MAX = 1024
OCI_AUTH_MODE_DEFAULT = "openai_api_key"
OCI_AUTH_MODES = frozenset({"openai_api_key", "resource_principal", "config_file"})
BOOLEAN_TRUE_VALUES = frozenset({"true", "1", "yes", "on"})
BOOLEAN_FALSE_VALUES = frozenset({"false", "0", "no", "off"})


@dataclass(frozen=True)
class DocumentIngestionSettings:
    """Runtime settings for agent-managed connector ingestion.

    Attributes:
        enabled: Whether the document ingestion endpoints are enabled.
        namespace: Object Storage namespace for staged documents.
        bucket: Object Storage bucket used by the connector.
        connector_id: Vector Store Data Sync Connector OCID.
        default_prefix: Prefix used when a request does not provide one.
        max_files: Maximum files accepted in one submission.
        max_file_size_mb: Maximum accepted size for each uploaded file.
    """

    enabled: bool
    namespace: str = ""
    bucket: str = ""
    connector_id: str = ""
    default_prefix: str = ""
    max_files: int = DOCUMENT_INGESTION_MAX_FILES_DEFAULT
    max_file_size_mb: int = DOCUMENT_INGESTION_MAX_FILE_SIZE_MB_DEFAULT

    @property
    def max_file_size_bytes(self) -> int:
        """Return the per-file size limit in bytes.

        Returns:
            int: Maximum file size in bytes.
        """

        return self.max_file_size_mb * 1024 * 1024


@dataclass(frozen=True)
class IncomingDocument:
    """Document content accepted by the agent ingestion service.

    Attributes:
        filename: Client-provided document filename.
        body: File-like object positioned at the start of the document content.
        size_bytes: Document size in bytes.
    """

    filename: str
    body: BinaryIO
    size_bytes: int


@dataclass(frozen=True)
class PlannedDocumentUpload:
    """Validated document upload plan.

    Attributes:
        document: Incoming document to upload.
        object_name: Target Object Storage object name.
    """

    document: IncomingDocument
    object_name: str


@dataclass(frozen=True)
class DocumentIngestionResult:
    """Result returned after successfully submitting connector ingestion.

    Attributes:
        job_id: Created connector file sync job identifier.
        connector_id: Vector Store Data Sync Connector OCID.
        namespace: Object Storage namespace.
        bucket: Object Storage bucket.
        uploaded_objects: Uploaded Object Storage object names.
        job_lifecycle_state: Initial connector job lifecycle state.
        job_trigger_type: Connector job trigger type, when returned.
        job_display_name: Connector job display name, when returned.
    """

    job_id: str
    connector_id: str
    namespace: str
    bucket: str
    uploaded_objects: list[str]
    job_lifecycle_state: str | None = None
    job_trigger_type: str | None = None
    job_display_name: str | None = None


@dataclass(frozen=True)
class DocumentIngestionStatus:
    """Current state of a connector file sync job.

    Attributes:
        job_id: Connector file sync job identifier.
        connector_id: Vector Store Data Sync Connector OCID.
        lifecycle_state: OCI lifecycle state.
        display_name: Connector job display name.
        time_created: Creation timestamp, when returned by OCI.
        time_updated: Last update timestamp, when returned by OCI.
        lifecycle_details: OCI lifecycle details, when returned.
        trigger_type: Connector job trigger type, when returned.
    """

    job_id: str
    connector_id: str
    lifecycle_state: str | None
    display_name: str | None = None
    time_created: str | None = None
    time_updated: str | None = None
    lifecycle_details: str | None = None
    trigger_type: str | None = None


@dataclass(frozen=True)
class ConnectorIngestionRequest:
    """Validated request options for one connector ingestion submission.

    Attributes:
        documents: Incoming documents to stage in Object Storage.
        prefix: Optional request-level Object Storage prefix.
        sync_display_name: Optional connector sync job display name.
        overwrite: Whether existing Object Storage objects may be replaced.
        details_factory: Optional sync details class or factory for tests.
    """

    documents: Iterable[IncomingDocument]
    prefix: str = ""
    sync_display_name: str | None = None
    overwrite: bool = False
    details_factory: Any | None = None


class DocumentIngestionError(Exception):
    """Base class for document ingestion failures."""

    status_code = 500


class DocumentIngestionDisabledError(DocumentIngestionError):
    """Raised when document ingestion endpoints are disabled."""

    status_code = 404


class DocumentIngestionValidationError(DocumentIngestionError):
    """Raised when a document ingestion request is invalid."""

    status_code = 400


class DocumentIngestionConflictError(DocumentIngestionError):
    """Raised when staged Object Storage objects already exist."""

    status_code = 409


class DocumentIngestionNotFoundError(DocumentIngestionError):
    """Raised when a connector file sync job cannot be found."""

    status_code = 404


class DocumentIngestionUpstreamError(DocumentIngestionError):
    """Raised when OCI upload or connector operations fail."""

    status_code = 502


def load_document_ingestion_settings() -> DocumentIngestionSettings:
    """Load document ingestion settings from environment variables.

    Returns:
        DocumentIngestionSettings: Validated ingestion settings.

    Raises:
        ValueError: If enabled settings are incomplete or invalid.
    """

    enabled = _load_optional_bool(
        "DOCUMENT_INGESTION_ENABLED",
        DOCUMENT_INGESTION_ENABLED_DEFAULT,
    )
    max_files = load_optional_int_env(
        "DOCUMENT_INGESTION_MAX_FILES",
        DOCUMENT_INGESTION_MAX_FILES_DEFAULT,
        DOCUMENT_INGESTION_MAX_FILES_MIN,
        DOCUMENT_INGESTION_MAX_FILES_MAX,
    )
    max_file_size_mb = load_optional_int_env(
        "DOCUMENT_INGESTION_MAX_FILE_SIZE_MB",
        DOCUMENT_INGESTION_MAX_FILE_SIZE_MB_DEFAULT,
        DOCUMENT_INGESTION_MAX_FILE_SIZE_MB_MIN,
        DOCUMENT_INGESTION_MAX_FILE_SIZE_MB_MAX,
    )

    settings = DocumentIngestionSettings(
        enabled=enabled,
        namespace=environ.get("OCI_DOCUMENT_NAMESPACE", "").strip(),
        bucket=environ.get("OCI_DOCUMENT_BUCKET", "").strip(),
        connector_id=environ.get("OCI_VECTOR_STORE_CONNECTOR_ID", "").strip(),
        default_prefix=environ.get("DOCUMENT_INGESTION_DEFAULT_PREFIX", "").strip(),
        max_files=max_files,
        max_file_size_mb=max_file_size_mb,
    )

    if not enabled:
        return settings

    missing_vars = [
        env_name
        for env_name, value in {
            "OCI_DOCUMENT_NAMESPACE": settings.namespace,
            "OCI_DOCUMENT_BUCKET": settings.bucket,
            "OCI_VECTOR_STORE_CONNECTOR_ID": settings.connector_id,
        }.items()
        if not value
    ]
    if missing_vars:
        names = ", ".join(missing_vars)
        raise ValueError(
            "Missing required document ingestion environment variables: " f"{names}"
        )

    build_object_name("validation.md", settings.default_prefix)
    return settings


def submit_connector_ingestion(
    ingestion_request: ConnectorIngestionRequest,
    settings: DocumentIngestionSettings,
    object_storage_client: ObjectStorageClientProtocol,
    generative_ai_client: GenerativeAiClientProtocol,
) -> DocumentIngestionResult:
    """Upload documents and submit a Vector Store connector sync job.

    Args:
        ingestion_request: Documents and request options for this submission.
        settings: Validated document ingestion settings.
        object_storage_client: OCI Object Storage client.
        generative_ai_client: OCI Generative AI client.

    Returns:
        DocumentIngestionResult: Submission result with connector job metadata.

    Raises:
        DocumentIngestionError: If validation, upload, or sync creation fails.
    """

    _ensure_enabled(settings)
    upload_plan = _build_upload_plan(
        ingestion_request.documents,
        settings,
        ingestion_request.prefix,
    )
    _reject_existing_objects(
        upload_plan,
        settings,
        object_storage_client,
        ingestion_request.overwrite,
    )
    uploaded_objects = _upload_planned_documents(
        upload_plan,
        settings,
        object_storage_client,
    )
    try:
        file_sync = trigger_file_sync(
            generative_ai_client,
            settings.connector_id,
            ingestion_request.sync_display_name,
            ingestion_request.details_factory,
        )
    except Exception as exc:  # pylint: disable=broad-exception-caught
        objects = ", ".join(uploaded_objects)
        raise DocumentIngestionUpstreamError(
            "Connector file sync creation failed for "
            f"{settings.connector_id}. Uploaded objects: {objects}. "
            f"Error: {format_error(exc)}"
        ) from exc

    return DocumentIngestionResult(
        job_id=str(getattr(file_sync, "id", "")),
        connector_id=settings.connector_id,
        namespace=settings.namespace,
        bucket=settings.bucket,
        uploaded_objects=uploaded_objects,
        job_lifecycle_state=getattr(file_sync, "lifecycle_state", None),
        job_trigger_type=getattr(file_sync, "trigger_type", None),
        job_display_name=getattr(file_sync, "display_name", None),
    )


def get_connector_ingestion_status(
    job_id: str,
    settings: DocumentIngestionSettings,
    generative_ai_client: GenerativeAiClientProtocol,
) -> DocumentIngestionStatus:
    """Read the current state of a connector file sync job.

    Args:
        job_id: Connector file sync job identifier.
        settings: Validated document ingestion settings.
        generative_ai_client: OCI Generative AI client.

    Returns:
        DocumentIngestionStatus: Current connector job status.

    Raises:
        DocumentIngestionError: If validation or OCI retrieval fails.
    """

    _ensure_enabled(settings)
    if not job_id.strip():
        raise DocumentIngestionValidationError("job_id must not be empty.")

    try:
        response = generative_ai_client.get_vector_store_connector_file_sync(job_id)
    except Exception as exc:  # pylint: disable=broad-exception-caught
        if getattr(exc, "status", None) == 404:
            raise DocumentIngestionNotFoundError(
                f"Connector file sync job was not found: {job_id}"
            ) from exc
        raise DocumentIngestionUpstreamError(
            f"Unable to read connector file sync job {job_id}: {format_error(exc)}"
        ) from exc

    file_sync = response.data
    return DocumentIngestionStatus(
        job_id=str(getattr(file_sync, "id", job_id)),
        connector_id=str(
            getattr(file_sync, "vector_store_connector_id", settings.connector_id)
        ),
        lifecycle_state=getattr(file_sync, "lifecycle_state", None),
        display_name=getattr(file_sync, "display_name", None),
        time_created=_format_optional_time(getattr(file_sync, "time_created", None)),
        time_updated=_format_optional_time(getattr(file_sync, "time_updated", None)),
        lifecycle_details=getattr(file_sync, "lifecycle_details", None),
        trigger_type=getattr(file_sync, "trigger_type", None),
    )


def build_oci_document_ingestion_clients() -> tuple[Any, Any]:
    """Build OCI Object Storage and Generative AI clients for agent ingestion.

    Returns:
        tuple[Any, Any]: Object Storage client and Generative AI client.

    Raises:
        RuntimeError: If the OCI SDK is unavailable or misconfigured.
    """

    try:
        import oci  # pylint: disable=import-outside-toplevel
    except ImportError as exc:
        raise RuntimeError(
            "The oci package is required for document ingestion."
        ) from exc

    auth_mode = load_optional_choice_env(
        "OCI_AUTH_MODE",
        OCI_AUTH_MODE_DEFAULT,
        OCI_AUTH_MODES,
    )
    if auth_mode == "resource_principal":
        return _build_resource_principal_clients(oci)
    if auth_mode == "config_file":
        return _build_config_file_clients(oci)

    raise RuntimeError(
        "DOCUMENT_INGESTION_ENABLED requires OCI_AUTH_MODE to be "
        "resource_principal or config_file. openai_api_key cannot authenticate "
        "Object Storage or connector file sync operations."
    )


def _build_resource_principal_clients(oci_module: Any) -> tuple[Any, Any]:
    """Build OCI SDK clients with a Resource Principal signer.

    Args:
        oci_module: Imported OCI SDK module.

    Returns:
        tuple[Any, Any]: Object Storage client and Generative AI client.

    Raises:
        RuntimeError: If Resource Principal signer creation fails.
    """

    try:
        signer = oci_module.auth.signers.get_resource_principals_signer()
    except Exception as exc:  # pylint: disable=broad-exception-caught
        raise RuntimeError(
            "Unable to initialize OCI Resource Principal authentication for "
            f"document ingestion: {exc}"
        ) from exc

    region = environ.get("OCI_REGION", "").strip()
    client_config = {"region": region} if region else {}
    return (
        oci_module.object_storage.ObjectStorageClient(client_config, signer=signer),
        oci_module.generative_ai.GenerativeAiClient(client_config, signer=signer),
    )


def _build_config_file_clients(oci_module: Any) -> tuple[Any, Any]:
    """Build OCI SDK clients from an OCI config file.

    Args:
        oci_module: Imported OCI SDK module.

    Returns:
        tuple[Any, Any]: Object Storage client and Generative AI client.

    Raises:
        RuntimeError: If OCI config loading fails.
    """

    profile = environ.get("OCI_PROFILE", "DEFAULT")
    config_file = environ.get("OCI_CONFIG_FILE")
    try:
        if config_file:
            oci_config = oci_module.config.from_file(
                file_location=config_file,
                profile_name=profile,
            )
        else:
            oci_config = oci_module.config.from_file(profile_name=profile)
    except Exception as exc:  # pylint: disable=broad-exception-caught
        raise RuntimeError(f"Unable to load OCI SDK configuration: {exc}") from exc

    return (
        oci_module.object_storage.ObjectStorageClient(oci_config),
        oci_module.generative_ai.GenerativeAiClient(oci_config),
    )


def _build_upload_plan(
    documents: Iterable[IncomingDocument],
    settings: DocumentIngestionSettings,
    request_prefix: str,
) -> list[PlannedDocumentUpload]:
    """Validate documents and build their Object Storage upload plan."""

    document_list = list(documents)
    if not document_list:
        raise DocumentIngestionValidationError("At least one document is required.")
    if len(document_list) > settings.max_files:
        raise DocumentIngestionValidationError(
            f"Too many documents. Maximum allowed: {settings.max_files}."
        )

    prefix = request_prefix if request_prefix.strip() else settings.default_prefix
    upload_plan: list[PlannedDocumentUpload] = []
    object_names: set[str] = set()
    for document in document_list:
        if document.size_bytes > settings.max_file_size_bytes:
            raise DocumentIngestionValidationError(
                f"{document.filename} exceeds the maximum size of "
                f"{settings.max_file_size_mb} MB."
            )
        try:
            object_name = build_object_name(document.filename, prefix)
        except ValueError as exc:
            raise DocumentIngestionValidationError(str(exc)) from exc
        if object_name in object_names:
            raise DocumentIngestionValidationError(
                f"Duplicate target object name in request: {object_name}"
            )
        object_names.add(object_name)
        upload_plan.append(
            PlannedDocumentUpload(document=document, object_name=object_name)
        )

    return upload_plan


def _reject_existing_objects(
    upload_plan: list[PlannedDocumentUpload],
    settings: DocumentIngestionSettings,
    object_storage_client: ObjectStorageClientProtocol,
    overwrite: bool,
) -> None:
    """Reject a request if existing staged objects would be overwritten."""

    if overwrite:
        return

    existing_objects = [
        planned_upload.object_name
        for planned_upload in upload_plan
        if object_exists(
            object_storage_client,
            settings.namespace,
            settings.bucket,
            planned_upload.object_name,
        )
    ]
    if existing_objects:
        objects = ", ".join(existing_objects)
        raise DocumentIngestionConflictError(
            "Target Object Storage objects already exist: " f"{objects}"
        )


def _upload_planned_documents(
    upload_plan: list[PlannedDocumentUpload],
    settings: DocumentIngestionSettings,
    object_storage_client: ObjectStorageClientProtocol,
) -> list[str]:
    """Upload planned documents to Object Storage."""

    uploaded_objects: list[str] = []
    for planned_upload in upload_plan:
        planned_upload.document.body.seek(0)
        try:
            object_storage_client.put_object(
                settings.namespace,
                settings.bucket,
                planned_upload.object_name,
                planned_upload.document.body,
            )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            raise DocumentIngestionUpstreamError(
                "Object Storage upload failed for "
                f"{planned_upload.document.filename} -> "
                f"{planned_upload.object_name}: {format_error(exc)}"
            ) from exc
        uploaded_objects.append(planned_upload.object_name)
    return uploaded_objects


def _ensure_enabled(settings: DocumentIngestionSettings) -> None:
    """Raise if agent-managed document ingestion is disabled."""

    if not settings.enabled:
        raise DocumentIngestionDisabledError("Document ingestion is not enabled.")


def _load_optional_bool(env_name: str, default_value: bool) -> bool:
    """Load and validate an optional boolean environment variable."""

    raw_value = environ.get(env_name)
    if raw_value is None or raw_value.strip() == "":
        return default_value

    normalized_value = raw_value.strip().lower()
    if normalized_value in BOOLEAN_TRUE_VALUES:
        return True
    if normalized_value in BOOLEAN_FALSE_VALUES:
        return False

    accepted_values = ", ".join(sorted(BOOLEAN_TRUE_VALUES.union(BOOLEAN_FALSE_VALUES)))
    raise ValueError(
        f"{env_name} must be a boolean value ({accepted_values}): {raw_value}"
    )


def _format_optional_time(value: Any) -> str | None:
    """Format optional OCI timestamp values for JSON responses."""

    if value is None:
        return None
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        return str(isoformat())
    return str(value)
