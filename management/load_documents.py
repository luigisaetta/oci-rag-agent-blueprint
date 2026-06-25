"""
Author: L. Saetta
Date last modified: 2026-06-25
License: MIT
Description: Upload local knowledge base documents and trigger Vector Store sync.
"""

from __future__ import annotations

# pylint: disable=too-few-public-methods,too-many-instance-attributes

import argparse
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Protocol

from management.document_ingestion import (
    SUPPORTED_EXTENSIONS,
    build_default_sync_display_name,
    format_error,
    load_file_sync_details_class,
    normalize_prefix,
    object_exists,
    trigger_file_sync as trigger_shared_file_sync,
)

DEFAULT_OCI_PROFILE = "DEFAULT"


class ObjectStorageClientProtocol(Protocol):
    """Protocol for the Object Storage methods used by the loader."""

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
    """Protocol for the Generative AI method used to trigger sync."""

    def create_vector_store_connector_file_sync(self, details: Any) -> Any:
        """Create a Vector Store connector file sync."""


@dataclass(frozen=True)
class DocumentFile:
    """A discovered local file and its target Object Storage object name.

    Attributes:
        path: Local file path.
        object_name: Target Object Storage object name.
    """

    path: Path
    object_name: str


@dataclass(frozen=True)
class LoaderConfig:
    """Runtime configuration for one document loading operation.

    Attributes:
        directory: Local directory to scan recursively.
        namespace: Object Storage namespace.
        bucket: Object Storage bucket name.
        connector_id: Vector Store Data Sync Connector OCID.
        prefix: Optional Object Storage object name prefix.
        profile: OCI configuration profile.
        config_file: Optional OCI configuration file path.
        sync_display_name: Display name for the manual file sync.
        dry_run: Whether to only print planned operations.
        overwrite: Whether to replace existing objects.
    """

    directory: Path
    namespace: str
    bucket: str
    connector_id: str
    prefix: str = ""
    profile: str = DEFAULT_OCI_PROFILE
    config_file: str | None = None
    sync_display_name: str | None = None
    dry_run: bool = False
    overwrite: bool = False


@dataclass
class LoadSummary:
    """Summary counters and sync metadata from one loader run.

    Attributes:
        planned: Number of supported files discovered for upload.
        uploaded: Number of files uploaded.
        skipped: Number of files skipped because the object already exists.
        ignored: Number of unsupported files ignored during discovery.
        failed: Number of failed uploads.
        errors: Human-readable upload or sync errors.
        sync_id: Created file sync OCID.
        sync_lifecycle_state: File sync lifecycle state, when returned.
        sync_trigger_type: File sync trigger type, when returned.
    """

    planned: int = 0
    uploaded: int = 0
    skipped: int = 0
    ignored: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)
    sync_id: str | None = None
    sync_lifecycle_state: str | None = None
    sync_trigger_type: str | None = None


def build_parser() -> argparse.ArgumentParser:
    """Build the document loader command-line parser.

    Returns:
        argparse.ArgumentParser: Configured parser.
    """

    parser = argparse.ArgumentParser(
        description=(
            "Upload local PDF, text, and Markdown documents to Object Storage "
            "and trigger a Vector Store connector file sync."
        )
    )
    parser.add_argument("--directory", required=True, help="Local document directory.")
    parser.add_argument("--namespace", required=True, help="Object Storage namespace.")
    parser.add_argument("--bucket", required=True, help="Object Storage bucket name.")
    parser.add_argument(
        "--connector-id",
        required=True,
        help="Vector Store Data Sync Connector OCID.",
    )
    parser.add_argument("--prefix", default="", help="Object name prefix.")
    parser.add_argument(
        "--profile",
        default=DEFAULT_OCI_PROFILE,
        help=f"OCI config profile. Default: {DEFAULT_OCI_PROFILE}.",
    )
    parser.add_argument("--config-file", help="OCI config file path.")
    parser.add_argument("--sync-display-name", help="Manual sync display name.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned operations without modifying OCI resources.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace existing Object Storage objects.",
    )
    return parser


def parse_args(argv: list[str] | None = None) -> LoaderConfig:
    """Parse command-line arguments into loader configuration.

    Args:
        argv: Optional argument list. Uses process arguments when omitted.

    Returns:
        LoaderConfig: Parsed loader configuration.
    """

    args = build_parser().parse_args(argv)
    return LoaderConfig(
        directory=Path(args.directory),
        namespace=args.namespace,
        bucket=args.bucket,
        connector_id=args.connector_id,
        prefix=args.prefix,
        profile=args.profile,
        config_file=args.config_file,
        sync_display_name=args.sync_display_name,
        dry_run=args.dry_run,
        overwrite=args.overwrite,
    )


def validate_config(config: LoaderConfig) -> None:
    """Validate loader configuration before OCI operations.

    Args:
        config: Loader configuration.

    Raises:
        ValueError: If a configuration value is invalid.
    """

    if not config.directory.exists():
        raise ValueError(f"directory does not exist: {config.directory}")
    if not config.directory.is_dir():
        raise ValueError(f"directory is not a directory: {config.directory}")

    required_values = {
        "namespace": config.namespace,
        "bucket": config.bucket,
        "connector-id": config.connector_id,
    }
    for field_name, value in required_values.items():
        if not value.strip():
            raise ValueError(f"{field_name} must not be empty.")

    normalize_prefix(config.prefix)


def discover_documents(
    directory: Path, prefix: str = ""
) -> tuple[list[DocumentFile], int]:
    """Discover supported documents below a directory.

    Args:
        directory: Root directory to scan recursively.
        prefix: Optional Object Storage object prefix.

    Returns:
        tuple[list[DocumentFile], int]: Supported files and ignored file count.
    """

    normalized_prefix = normalize_prefix(prefix)
    documents: list[DocumentFile] = []
    ignored = 0

    for path in sorted(directory.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            ignored += 1
            continue

        relative_name = path.relative_to(directory).as_posix()
        documents.append(
            DocumentFile(path=path, object_name=f"{normalized_prefix}{relative_name}")
        )

    return documents, ignored


def upload_documents(
    object_storage_client: ObjectStorageClientProtocol,
    config: LoaderConfig,
    documents: Iterable[DocumentFile],
) -> LoadSummary:
    """Upload discovered documents to Object Storage.

    Args:
        object_storage_client: OCI Object Storage client.
        config: Loader configuration.
        documents: Documents to upload.

    Returns:
        LoadSummary: Upload summary.
    """

    document_list = list(documents)
    summary = LoadSummary(planned=len(document_list))

    for document in document_list:
        try:
            if not config.overwrite and object_exists(
                object_storage_client,
                config.namespace,
                config.bucket,
                document.object_name,
            ):
                summary.skipped += 1
                continue

            with document.path.open("rb") as file_handle:
                object_storage_client.put_object(
                    config.namespace,
                    config.bucket,
                    document.object_name,
                    file_handle,
                )
            summary.uploaded += 1
        except Exception as exc:  # pylint: disable=broad-exception-caught
            summary.failed += 1
            summary.errors.append(
                f"{document.path} -> {document.object_name}: {format_error(exc)}"
            )

    return summary


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

    return trigger_shared_file_sync(
        generative_ai_client,
        connector_id,
        display_name or build_default_sync_display_name(),
        details_factory or load_file_sync_details_class(),
    )


def load_documents(
    config: LoaderConfig,
    object_storage_client: ObjectStorageClientProtocol,
    generative_ai_client: GenerativeAiClientProtocol,
    details_factory: Any | None = None,
) -> LoadSummary:
    """Run document discovery, upload, and sync trigger.

    Args:
        config: Loader configuration.
        object_storage_client: OCI Object Storage client.
        generative_ai_client: OCI Generative AI client.
        details_factory: Optional file sync details class or factory for tests.

    Returns:
        LoadSummary: Complete load summary.

    Raises:
        ValueError: If validation fails or there are no supported files.
    """

    validate_config(config)
    documents, ignored = discover_documents(config.directory, config.prefix)
    if not documents and not config.dry_run:
        raise ValueError("directory does not contain supported document files.")

    summary = LoadSummary(planned=len(documents), ignored=ignored)

    if config.dry_run:
        return summary

    upload_summary = upload_documents(object_storage_client, config, documents)
    upload_summary.ignored = ignored

    if upload_summary.failed:
        return upload_summary

    try:
        file_sync = trigger_file_sync(
            generative_ai_client,
            config.connector_id,
            config.sync_display_name,
            details_factory,
        )
    except Exception as exc:  # pylint: disable=broad-exception-caught
        upload_summary.failed += 1
        upload_summary.errors.append(f"sync trigger failed: {format_error(exc)}")
        return upload_summary

    upload_summary.sync_id = getattr(file_sync, "id", None)
    upload_summary.sync_lifecycle_state = getattr(file_sync, "lifecycle_state", None)
    upload_summary.sync_trigger_type = getattr(file_sync, "trigger_type", None)
    return upload_summary


def load_oci_config(config_file: str | None, profile: str) -> dict[str, Any]:
    """Load an OCI SDK configuration dictionary.

    Args:
        config_file: Optional OCI config file path.
        profile: OCI config profile name.

    Returns:
        dict[str, Any]: OCI SDK config.

    Raises:
        RuntimeError: If the OCI SDK or configuration cannot be loaded.
    """

    try:
        import oci  # pylint: disable=import-outside-toplevel
    except ImportError as exc:
        raise RuntimeError("The oci package is required for document loading.") from exc

    try:
        if config_file:
            return oci.config.from_file(
                file_location=os.path.expanduser(config_file),
                profile_name=profile,
            )
        return oci.config.from_file(profile_name=profile)
    except Exception as exc:  # pylint: disable=broad-exception-caught
        location = config_file or "~/.oci/config"
        raise RuntimeError(
            f"Unable to load OCI config profile '{profile}' from {location}: {exc}"
        ) from exc


def build_oci_clients(config: LoaderConfig) -> tuple[Any, Any]:
    """Build OCI Object Storage and Generative AI clients.

    Args:
        config: Loader configuration.

    Returns:
        tuple[Any, Any]: Object Storage client and Generative AI client.

    Raises:
        RuntimeError: If the OCI SDK is unavailable or misconfigured.
    """

    try:
        import oci  # pylint: disable=import-outside-toplevel
    except ImportError as exc:
        raise RuntimeError("The oci package is required for document loading.") from exc

    oci_config = load_oci_config(config.config_file, config.profile)
    object_storage_client = oci.object_storage.ObjectStorageClient(oci_config)
    generative_ai_client = oci.generative_ai.GenerativeAiClient(oci_config)
    return object_storage_client, generative_ai_client


def print_plan(
    config: LoaderConfig, documents: list[DocumentFile], ignored: int
) -> None:
    """Print planned document loader operations.

    Args:
        config: Loader configuration.
        documents: Documents planned for upload.
        ignored: Ignored unsupported file count.
    """

    print("Document loader plan")
    print("--------------------")
    print(f"Directory   : {config.directory}")
    print(f"Namespace   : {config.namespace}")
    print(f"Bucket      : {config.bucket}")
    print(f"Prefix      : {normalize_prefix(config.prefix) or '(none)'}")
    print(f"Connector   : {config.connector_id}")
    print(f"Supported   : {len(documents)}")
    print(f"Ignored     : {ignored}")
    for document in documents:
        print(f" - {document.path} -> {document.object_name}")


def print_summary(summary: LoadSummary) -> None:
    """Print a document loader summary.

    Args:
        summary: Load summary to print.
    """

    print("Document loader summary")
    print("-----------------------")
    print(f"Planned : {summary.planned}")
    print(f"Uploaded: {summary.uploaded}")
    print(f"Skipped : {summary.skipped}")
    print(f"Ignored : {summary.ignored}")
    print(f"Failed  : {summary.failed}")

    if summary.sync_id:
        print(f"Sync id : {summary.sync_id}")
    if summary.sync_lifecycle_state:
        print(f"Sync lifecycle: {summary.sync_lifecycle_state}")
    if summary.sync_trigger_type:
        print(f"Sync trigger  : {summary.sync_trigger_type}")

    if summary.errors:
        print("")
        print("Errors")
        print("------")
        for error in summary.errors:
            print(f"- {error}")


def main(argv: list[str] | None = None) -> int:
    """Run the document loader command-line program.

    Args:
        argv: Optional argument list. Uses process arguments when omitted.

    Returns:
        int: Process exit code.
    """

    try:
        config = parse_args(argv)
        validate_config(config)
        documents, ignored = discover_documents(config.directory, config.prefix)

        if config.dry_run:
            print_plan(config, documents, ignored)
            return 0

        if not documents:
            raise ValueError("directory does not contain supported document files.")

        object_storage_client, generative_ai_client = build_oci_clients(config)
        summary = load_documents(config, object_storage_client, generative_ai_client)
        print_summary(summary)
        return 1 if summary.failed else 0
    except (RuntimeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
