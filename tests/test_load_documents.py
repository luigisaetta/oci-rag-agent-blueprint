"""
Author: L. Saetta
Date last modified: 2026-06-24
License: MIT
Description: Unit tests for the local document loader management script.
"""

from __future__ import annotations

# pylint: disable=too-few-public-methods

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from management import load_documents


class FakeNotFoundError(Exception):
    """Fake OCI 404 error."""

    status = 404


class FakeServiceError(Exception):
    """Fake non-404 OCI service error."""

    status = 500
    message = "service failed"


class FakeObjectStorageClient:
    """Fake Object Storage client for upload tests."""

    def __init__(
        self,
        existing_objects: set[str] | None = None,
        failing_objects: set[str] | None = None,
    ) -> None:
        """Initialize the fake client.

        Args:
            existing_objects: Object names that should appear to exist.
            failing_objects: Object names whose upload should fail.
        """

        self.existing_objects = existing_objects or set()
        self.failing_objects = failing_objects or set()
        self.head_calls: list[str] = []
        self.put_calls: list[tuple[str, bytes]] = []

    def head_object(
        self, namespace_name: str, bucket_name: str, object_name: str
    ) -> None:
        """Record object existence checks.

        Args:
            namespace_name: Object Storage namespace.
            bucket_name: Object Storage bucket name.
            object_name: Object name.

        Raises:
            FakeNotFoundError: If the object does not exist.
        """

        del namespace_name, bucket_name
        self.head_calls.append(object_name)
        if object_name not in self.existing_objects:
            raise FakeNotFoundError()

    def put_object(
        self,
        namespace_name: str,
        bucket_name: str,
        object_name: str,
        put_object_body: Any,
    ) -> None:
        """Record uploads and optionally fail selected objects.

        Args:
            namespace_name: Object Storage namespace.
            bucket_name: Object Storage bucket name.
            object_name: Object name.
            put_object_body: File-like upload body.

        Raises:
            FakeServiceError: If the object is configured to fail.
        """

        del namespace_name, bucket_name
        if object_name in self.failing_objects:
            raise FakeServiceError()
        self.put_calls.append((object_name, put_object_body.read()))


@dataclass
class FakeFileSync:
    """Fake OCI file sync response data."""

    id: str
    lifecycle_state: str
    trigger_type: str


@dataclass
class FakeResponse:
    """Fake OCI SDK response wrapper."""

    data: Any


class FakeGenerativeAiClient:
    """Fake Generative AI client for file sync tests."""

    def __init__(self, fail: bool = False) -> None:
        """Initialize the fake client."""

        self.fail = fail
        self.details: Any | None = None

    def create_vector_store_connector_file_sync(self, details: Any) -> FakeResponse:
        """Record sync details and return a fake sync.

        Args:
            details: File sync details object.

        Returns:
            FakeResponse: Fake OCI response.
        """

        self.details = details
        if self.fail:
            raise FakeServiceError()
        return FakeResponse(
            FakeFileSync(
                id="sync-123",
                lifecycle_state="ACCEPTED",
                trigger_type="MANUAL",
            )
        )


@dataclass
class FakeDetails:
    """Fake CreateVectorStoreConnectorFileSyncDetails replacement."""

    vector_store_connector_id: str
    display_name: str


def write_file(path: Path, content: bytes = b"content") -> None:
    """Write a test file and create parent directories.

    Args:
        path: File path.
        content: File content.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def build_config(directory: Path, **overrides: Any) -> load_documents.LoaderConfig:
    """Build a default loader config for tests.

    Args:
        directory: Local document directory.
        overrides: Optional config value overrides.

    Returns:
        load_documents.LoaderConfig: Test loader config.
    """

    values = {
        "directory": directory,
        "namespace": "namespace",
        "bucket": "bucket",
        "connector_id": "connector-id",
    }
    values.update(overrides)
    return load_documents.LoaderConfig(**values)


def test_discover_documents_filters_supported_files_and_maps_object_names(
    tmp_path: Path,
) -> None:
    """Test discovery includes supported files and ignores unsupported files."""

    write_file(tmp_path / "guide.pdf")
    write_file(tmp_path / "nested" / "notes.MD")
    write_file(tmp_path / "nested" / "plain.txt")
    write_file(tmp_path / "image.png")

    documents, ignored = load_documents.discover_documents(tmp_path, "kb")

    assert ignored == 1
    assert [document.object_name for document in documents] == [
        "kb/guide.pdf",
        "kb/nested/notes.MD",
        "kb/nested/plain.txt",
    ]


def test_normalize_prefix_rejects_leading_slash() -> None:
    """Test prefix validation rejects absolute object-name-like prefixes."""

    with pytest.raises(ValueError, match="prefix must not start"):
        load_documents.normalize_prefix("/bad")


def test_parse_args_builds_loader_config(tmp_path: Path) -> None:
    """Test CLI arguments are parsed into a loader config."""

    config = load_documents.parse_args(
        [
            "--directory",
            str(tmp_path),
            "--namespace",
            "namespace",
            "--bucket",
            "bucket",
            "--connector-id",
            "connector-id",
            "--prefix",
            "docs",
            "--profile",
            "PROFILE",
            "--config-file",
            "/tmp/config",
            "--sync-display-name",
            "sync",
            "--dry-run",
            "--overwrite",
        ]
    )

    assert config == load_documents.LoaderConfig(
        directory=tmp_path,
        namespace="namespace",
        bucket="bucket",
        connector_id="connector-id",
        prefix="docs",
        profile="PROFILE",
        config_file="/tmp/config",
        sync_display_name="sync",
        dry_run=True,
        overwrite=True,
    )


def test_object_exists_reraises_non_404_errors() -> None:
    """Test object existence checks only suppress 404 errors."""

    class FailingHeadClient(FakeObjectStorageClient):
        """Fake client that raises a non-404 error for head requests."""

        def head_object(
            self, namespace_name: str, bucket_name: str, object_name: str
        ) -> None:
            """Raise a fake non-404 service error."""

            del namespace_name, bucket_name, object_name
            raise FakeServiceError()

    with pytest.raises(FakeServiceError):
        load_documents.object_exists(
            FailingHeadClient(),
            "namespace",
            "bucket",
            "object",
        )


def test_load_documents_dry_run_does_not_call_oci_clients(tmp_path: Path) -> None:
    """Test dry-run returns planned counts without OCI calls."""

    write_file(tmp_path / "guide.pdf")
    object_storage_client = FakeObjectStorageClient()
    generative_ai_client = FakeGenerativeAiClient()

    summary = load_documents.load_documents(
        build_config(tmp_path, dry_run=True),
        object_storage_client,
        generative_ai_client,
        FakeDetails,
    )

    assert summary.planned == 1
    assert summary.uploaded == 0
    assert not object_storage_client.put_calls
    assert generative_ai_client.details is None


def test_upload_documents_skips_existing_objects_by_default(tmp_path: Path) -> None:
    """Test existing objects are skipped unless overwrite is enabled."""

    write_file(tmp_path / "guide.pdf", b"pdf")
    document = load_documents.DocumentFile(tmp_path / "guide.pdf", "guide.pdf")
    object_storage_client = FakeObjectStorageClient(existing_objects={"guide.pdf"})

    summary = load_documents.upload_documents(
        object_storage_client,
        build_config(tmp_path),
        [document],
    )

    assert summary.skipped == 1
    assert summary.uploaded == 0
    assert not object_storage_client.put_calls


def test_upload_documents_overwrites_existing_objects(tmp_path: Path) -> None:
    """Test overwrite mode uploads even when an object exists."""

    write_file(tmp_path / "guide.pdf", b"pdf")
    document = load_documents.DocumentFile(tmp_path / "guide.pdf", "guide.pdf")
    object_storage_client = FakeObjectStorageClient(existing_objects={"guide.pdf"})

    summary = load_documents.upload_documents(
        object_storage_client,
        build_config(tmp_path, overwrite=True),
        [document],
    )

    assert summary.skipped == 0
    assert summary.uploaded == 1
    assert object_storage_client.put_calls == [("guide.pdf", b"pdf")]


def test_load_documents_triggers_sync_after_successful_uploads(tmp_path: Path) -> None:
    """Test a successful load creates a Vector Store connector file sync."""

    write_file(tmp_path / "guide.pdf", b"pdf")
    object_storage_client = FakeObjectStorageClient()
    generative_ai_client = FakeGenerativeAiClient()

    summary = load_documents.load_documents(
        build_config(tmp_path, sync_display_name="manual-sync"),
        object_storage_client,
        generative_ai_client,
        FakeDetails,
    )

    assert summary.uploaded == 1
    assert summary.sync_id == "sync-123"
    assert summary.sync_lifecycle_state == "ACCEPTED"
    assert summary.sync_trigger_type == "MANUAL"
    assert generative_ai_client.details == FakeDetails(
        vector_store_connector_id="connector-id",
        display_name="manual-sync",
    )


def test_trigger_file_sync_uses_default_display_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test sync trigger builds a default display name when none is provided."""

    monkeypatch.setattr(
        load_documents,
        "build_default_sync_display_name",
        lambda: "generated-sync-name",
    )
    generative_ai_client = FakeGenerativeAiClient()

    file_sync = load_documents.trigger_file_sync(
        generative_ai_client,
        "connector-id",
        details_factory=FakeDetails,
    )

    assert file_sync.id == "sync-123"
    assert generative_ai_client.details == FakeDetails(
        vector_store_connector_id="connector-id",
        display_name="generated-sync-name",
    )


def test_load_documents_does_not_trigger_sync_when_upload_fails(tmp_path: Path) -> None:
    """Test upload failures prevent sync job creation."""

    write_file(tmp_path / "guide.pdf", b"pdf")
    object_storage_client = FakeObjectStorageClient(failing_objects={"guide.pdf"})
    generative_ai_client = FakeGenerativeAiClient()

    summary = load_documents.load_documents(
        build_config(tmp_path),
        object_storage_client,
        generative_ai_client,
        FakeDetails,
    )

    assert summary.failed == 1
    assert summary.errors == [f"{tmp_path / 'guide.pdf'} -> guide.pdf: service failed"]
    assert generative_ai_client.details is None


def test_load_documents_reports_sync_trigger_failure(tmp_path: Path) -> None:
    """Test sync trigger errors are returned as loader failures."""

    write_file(tmp_path / "guide.pdf", b"pdf")
    object_storage_client = FakeObjectStorageClient()
    generative_ai_client = FakeGenerativeAiClient(fail=True)

    summary = load_documents.load_documents(
        build_config(tmp_path),
        object_storage_client,
        generative_ai_client,
        FakeDetails,
    )

    assert summary.uploaded == 1
    assert summary.failed == 1
    assert summary.errors == ["sync trigger failed: service failed"]


def test_validate_config_rejects_missing_directory(tmp_path: Path) -> None:
    """Test CLI validation rejects missing document directories."""

    with pytest.raises(ValueError, match="directory does not exist"):
        load_documents.validate_config(build_config(tmp_path / "missing"))


def test_main_dry_run_prints_plan(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Test dry-run CLI prints planned uploads and exits successfully."""

    write_file(tmp_path / "guide.pdf")

    exit_code = load_documents.main(
        [
            "--directory",
            str(tmp_path),
            "--namespace",
            "namespace",
            "--bucket",
            "bucket",
            "--connector-id",
            "connector-id",
            "--dry-run",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Document loader plan" in captured.out
    assert "guide.pdf" in captured.out


def test_main_success_uses_built_oci_clients(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Test successful CLI execution builds clients and prints a summary."""

    write_file(tmp_path / "guide.pdf")
    object_storage_client = FakeObjectStorageClient()
    generative_ai_client = FakeGenerativeAiClient()
    monkeypatch.setattr(
        load_documents,
        "build_oci_clients",
        lambda config: (object_storage_client, generative_ai_client),
    )
    monkeypatch.setattr(
        load_documents, "load_file_sync_details_class", lambda: FakeDetails
    )

    exit_code = load_documents.main(
        [
            "--directory",
            str(tmp_path),
            "--namespace",
            "namespace",
            "--bucket",
            "bucket",
            "--connector-id",
            "connector-id",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Document loader summary" in captured.out
    assert "Sync id : sync-123" in captured.out


def test_main_returns_non_zero_for_empty_directory(tmp_path: Path) -> None:
    """Test CLI exits with an error when no supported files exist."""

    assert (
        load_documents.main(
            [
                "--directory",
                str(tmp_path),
                "--namespace",
                "namespace",
                "--bucket",
                "bucket",
                "--connector-id",
                "connector-id",
            ]
        )
        == 1
    )
