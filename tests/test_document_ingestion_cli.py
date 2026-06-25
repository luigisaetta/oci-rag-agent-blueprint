"""
Author: L. Saetta
Date last modified: 2026-06-25
License: MIT
Description: Unit tests for the document ingestion command-line client.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from clients import document_ingestion_cli


class FakeResponse:
    """Context manager response for fake urlopen calls."""

    def __init__(self, payload: dict[str, object]) -> None:
        """Initialize the fake response."""

        self.payload = payload

    def __enter__(self) -> "FakeResponse":
        """Enter the fake response context."""

        return self

    def __exit__(self, *_args: object) -> None:
        """Exit the fake response context."""

    def read(self) -> bytes:
        """Return encoded JSON response bytes."""

        return json.dumps(self.payload).encode("utf-8")


def test_build_ingestions_endpoint_accepts_base_or_full_url() -> None:
    """Test ingestion endpoint construction."""

    assert (
        document_ingestion_cli.build_ingestions_endpoint("http://localhost:8080")
        == "http://localhost:8080/documents/ingestions"
    )
    assert (
        document_ingestion_cli.build_ingestions_endpoint(
            "http://localhost:8080/documents/ingestions"
        )
        == "http://localhost:8080/documents/ingestions"
    )


def test_build_status_endpoint() -> None:
    """Test status endpoint construction."""

    assert (
        document_ingestion_cli.build_status_endpoint(
            "http://localhost:8080",
            "sync-123",
        )
        == "http://localhost:8080/documents/ingestions/sync-123"
    )


def test_build_upload_file_parts_validates_files(tmp_path: Path) -> None:
    """Test file part construction validates paths."""

    document = tmp_path / "guide.md"
    document.write_text("# Guide", encoding="utf-8")

    parts = document_ingestion_cli.build_upload_file_parts([str(document)])

    assert parts[0].field_name == "files"
    assert parts[0].file_path == document
    assert parts[0].filename == "guide.md"
    assert parts[0].content_type == "text/markdown"


def test_build_upload_file_parts_rejects_missing_files(tmp_path: Path) -> None:
    """Test missing upload files are rejected."""

    with pytest.raises(ValueError, match="file does not exist"):
        document_ingestion_cli.build_upload_file_parts([str(tmp_path / "missing.md")])


def test_encode_multipart_form_includes_fields_and_file(tmp_path: Path) -> None:
    """Test multipart request body construction."""

    document = tmp_path / "guide.md"
    document.write_text("# Guide", encoding="utf-8")
    file_part = document_ingestion_cli.UploadFilePart(
        field_name="files",
        file_path=document,
        filename="guide.md",
        content_type="text/markdown",
    )

    body, content_type = document_ingestion_cli.encode_multipart_form(
        {"prefix": "docs", "overwrite": "true"},
        [file_part],
        boundary="boundary",
    )

    assert content_type == "multipart/form-data; boundary=boundary"
    assert b'name="prefix"' in body
    assert b"docs" in body
    assert b'filename="guide.md"' in body
    assert b"# Guide" in body


def test_submit_document_ingestion_sends_multipart_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test submit sends multipart upload request and parses response."""

    captured_request: dict[str, Any] = {}
    document = tmp_path / "guide.md"
    document.write_text("# Guide", encoding="utf-8")
    file_parts = document_ingestion_cli.build_upload_file_parts([str(document)])

    def fake_urlopen(http_request: Any, timeout: int) -> FakeResponse:
        captured_request["url"] = http_request.full_url
        captured_request["method"] = http_request.get_method()
        captured_request["timeout"] = timeout
        captured_request["body"] = http_request.data
        captured_request["authorization"] = http_request.headers["Authorization"]
        captured_request["content_type"] = http_request.headers["Content-type"]
        return FakeResponse({"status": "submitted", "job_id": "sync-123"})

    monkeypatch.setattr(document_ingestion_cli.request, "urlopen", fake_urlopen)

    payload = document_ingestion_cli.submit_document_ingestion(
        document_ingestion_cli.SubmitIngestionRequest(
            endpoint="http://localhost:8080/documents/ingestions",
            file_parts=file_parts,
            prefix="docs",
            sync_display_name="manual-sync",
            overwrite=True,
            access_token="jwt-token",
        )
    )

    assert payload == {"status": "submitted", "job_id": "sync-123"}
    assert captured_request["url"] == "http://localhost:8080/documents/ingestions"
    assert captured_request["method"] == "POST"
    assert captured_request["timeout"] == 300
    assert captured_request["authorization"] == "Bearer jwt-token"
    assert "multipart/form-data" in captured_request["content_type"]
    assert b"manual-sync" in captured_request["body"]
    assert b"# Guide" in captured_request["body"]


def test_get_document_ingestion_status_sends_get_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test status sends a GET request and parses response."""

    captured_request: dict[str, Any] = {}

    def fake_urlopen(http_request: Any, timeout: int) -> FakeResponse:
        captured_request["url"] = http_request.full_url
        captured_request["method"] = http_request.get_method()
        captured_request["timeout"] = timeout
        captured_request["authorization"] = http_request.headers["Authorization"]
        return FakeResponse({"job_id": "sync-123", "lifecycle_state": "SUCCEEDED"})

    monkeypatch.setattr(document_ingestion_cli.request, "urlopen", fake_urlopen)

    payload = document_ingestion_cli.get_document_ingestion_status(
        "http://localhost:8080/documents/ingestions/sync-123",
        access_token="jwt-token",
    )

    assert payload == {"job_id": "sync-123", "lifecycle_state": "SUCCEEDED"}
    assert captured_request["url"].endswith("/documents/ingestions/sync-123")
    assert captured_request["method"] == "GET"
    assert captured_request["timeout"] == 120
    assert captured_request["authorization"] == "Bearer jwt-token"


def test_wait_for_document_ingestion_stops_on_terminal_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test polling stops when the job reaches a terminal state."""

    responses = [
        {"job_id": "sync-123", "lifecycle_state": "IN_PROGRESS"},
        {"job_id": "sync-123", "lifecycle_state": "SUCCEEDED"},
    ]
    sleep_calls: list[float] = []
    monkeypatch.setattr(
        document_ingestion_cli,
        "get_document_ingestion_status",
        lambda endpoint, access_token=None: responses.pop(0),
    )
    monkeypatch.setattr(document_ingestion_cli.time, "sleep", sleep_calls.append)

    payload = document_ingestion_cli.wait_for_document_ingestion(
        "http://localhost:8080",
        "sync-123",
        interval_seconds=0.1,
        timeout_seconds=10,
    )

    assert payload == {"job_id": "sync-123", "lifecycle_state": "SUCCEEDED"}
    assert sleep_calls == [0.1]


def test_main_submit_uses_idcs_and_wait(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Test submit command orchestrates token, upload, and wait."""

    document = tmp_path / "guide.md"
    document.write_text("# Guide", encoding="utf-8")
    monkeypatch.setattr(
        document_ingestion_cli,
        "build_client_environment",
        lambda env_file: {"env_file": env_file},
    )
    monkeypatch.setattr(
        document_ingestion_cli,
        "maybe_fetch_idcs_access_token",
        lambda auth, environment: f"token:{auth}:{environment['env_file']}",
    )
    monkeypatch.setattr(
        document_ingestion_cli,
        "submit_document_ingestion",
        lambda ingestion_request: {
            "status": "submitted",
            "job_id": "sync-123",
            "endpoint": ingestion_request.endpoint,
            "access_token": ingestion_request.access_token,
            "files": [part.filename for part in ingestion_request.file_parts],
        },
    )
    monkeypatch.setattr(
        document_ingestion_cli,
        "wait_for_document_ingestion",
        lambda base_url, job_id, **kwargs: {
            "job_id": job_id,
            "lifecycle_state": "SUCCEEDED",
            "access_token": kwargs["access_token"],
        },
    )

    exit_code = document_ingestion_cli.main(
        [
            "--base-url",
            "http://localhost:8080",
            "--auth",
            "idcs",
            "--env-file",
            ".env.test",
            "submit",
            "--file",
            str(document),
            "--wait",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert '"status": "submitted"' in captured.out
    assert '"lifecycle_state": "SUCCEEDED"' in captured.out
    assert '"access_token": "token:idcs:.env.test"' in captured.out


def test_main_status_command(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Test status command renders job status."""

    monkeypatch.setattr(
        document_ingestion_cli,
        "build_client_environment",
        lambda env_file: {"env_file": env_file},
    )
    monkeypatch.setattr(
        document_ingestion_cli,
        "maybe_fetch_idcs_access_token",
        lambda auth, environment: None,
    )
    monkeypatch.setattr(
        document_ingestion_cli,
        "get_document_ingestion_status",
        lambda endpoint, access_token=None: {
            "job_id": "sync-123",
            "lifecycle_state": "SUCCEEDED",
            "endpoint": endpoint,
        },
    )

    exit_code = document_ingestion_cli.main(
        ["--base-url", "http://localhost:8080", "status", "sync-123"]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert '"job_id": "sync-123"' in captured.out
    assert '"lifecycle_state": "SUCCEEDED"' in captured.out
