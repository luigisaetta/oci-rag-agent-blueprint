"""
Author: L. Saetta
Date last modified: 2026-06-25
License: MIT
Description: Shared helpers for Object Storage document staging and connector sync jobs.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Any, Protocol

SUPPORTED_EXTENSIONS = frozenset({".pdf", ".txt", ".md"})


class ObjectStorageClientProtocol(Protocol):
    """Protocol for Object Storage operations used by document ingestion."""

    def head_object(
        self, namespace_name: str, bucket_name: str, object_name: str
    ) -> Any:
        """Return object metadata or raise when the object does not exist."""

    def put_object(
        self,
        namespace_name: str,
        bucket_name: str,
        object_name: str,
        put_object_body: Any,
    ) -> Any:
        """Upload object content."""


class GenerativeAiClientProtocol(Protocol):
    """Protocol for Generative AI connector file sync operations."""

    def create_vector_store_connector_file_sync(self, details: Any) -> Any:
        """Create a Vector Store connector file sync."""

    def get_vector_store_connector_file_sync(self, file_sync_id: str) -> Any:
        """Return a Vector Store connector file sync."""


def normalize_prefix(prefix: str) -> str:
    """Normalize an Object Storage prefix.

    Args:
        prefix: User-provided prefix.

    Returns:
        str: Empty prefix or prefix ending with `/`.

    Raises:
        ValueError: If the prefix starts with `/`.
    """

    clean_prefix = prefix.strip()
    if not clean_prefix:
        return ""
    if clean_prefix.startswith("/"):
        raise ValueError("prefix must not start with '/'.")
    return clean_prefix.rstrip("/") + "/"


def validate_supported_filename(filename: str) -> str:
    """Validate and normalize an uploaded document filename.

    Args:
        filename: Original filename provided by a client or local path.

    Returns:
        str: Safe relative filename using `/` separators.

    Raises:
        ValueError: If the filename is empty, unsafe, or unsupported.
    """

    normalized_name = filename.replace("\\", "/").lstrip("/")
    path = PurePosixPath(normalized_name)
    if not normalized_name or str(path) in {"", "."}:
        raise ValueError("filename must not be empty.")
    if ".." in path.parts:
        raise ValueError(f"filename must not contain path traversal: {filename}")
    if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        supported = ", ".join(sorted(SUPPORTED_EXTENSIONS))
        raise ValueError(f"unsupported document extension for {filename}: {supported}")
    return path.as_posix()


def build_object_name(filename: str, prefix: str = "") -> str:
    """Build the Object Storage object name for a document.

    Args:
        filename: Relative document filename.
        prefix: Optional Object Storage prefix.

    Returns:
        str: Normalized Object Storage object name.

    Raises:
        ValueError: If the filename or prefix is invalid.
    """

    return f"{normalize_prefix(prefix)}{validate_supported_filename(filename)}"


def object_exists(
    object_storage_client: ObjectStorageClientProtocol,
    namespace: str,
    bucket: str,
    object_name: str,
) -> bool:
    """Return whether an Object Storage object already exists.

    Args:
        object_storage_client: OCI Object Storage client.
        namespace: Object Storage namespace.
        bucket: Object Storage bucket name.
        object_name: Object name to check.

    Returns:
        bool: True when the object exists.

    Raises:
        Exception: Any non-404 client error.
    """

    try:
        object_storage_client.head_object(namespace, bucket, object_name)
        return True
    except Exception as exc:  # pylint: disable=broad-exception-caught
        if getattr(exc, "status", None) == 404:
            return False
        raise


def trigger_file_sync(
    generative_ai_client: GenerativeAiClientProtocol,
    connector_id: str,
    display_name: str | None = None,
    details_factory: Any | None = None,
) -> Any:
    """Trigger a manual Vector Store connector file sync.

    Args:
        generative_ai_client: OCI Generative AI client.
        connector_id: Vector Store Data Sync Connector OCID.
        display_name: Optional sync display name.
        details_factory: Optional details class or factory for tests.

    Returns:
        Any: OCI file sync response data.
    """

    details_class = details_factory or load_file_sync_details_class()
    details = details_class(
        vector_store_connector_id=connector_id,
        display_name=display_name or build_default_sync_display_name(),
    )
    response = generative_ai_client.create_vector_store_connector_file_sync(details)
    return response.data


def build_default_sync_display_name() -> str:
    """Build a readable default sync display name.

    Returns:
        str: Generated display name.
    """

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"document-loader-sync-{timestamp}"


def load_file_sync_details_class() -> Any:
    """Load the OCI file sync details model class.

    Returns:
        Any: CreateVectorStoreConnectorFileSyncDetails class.

    Raises:
        RuntimeError: If the OCI SDK is unavailable.
    """

    try:
        from oci.generative_ai.models import (  # pylint: disable=import-outside-toplevel
            CreateVectorStoreConnectorFileSyncDetails,
        )
    except ImportError as exc:
        raise RuntimeError("The oci package is required for document loading.") from exc

    return CreateVectorStoreConnectorFileSyncDetails


def format_error(exc: Exception) -> str:
    """Format an exception for command or API output.

    Args:
        exc: Exception to format.

    Returns:
        str: Human-readable error.
    """

    message = getattr(exc, "message", None)
    if message:
        return str(message)
    return str(exc)
