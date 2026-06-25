"""
Author: L. Saetta
Date last modified: 2026-06-25
License: MIT
Description: Unit tests for agent-managed connector document ingestion endpoints.
"""

from __future__ import annotations

# pylint: disable=duplicate-code,too-few-public-methods,too-many-instance-attributes

from dataclasses import dataclass
from datetime import datetime, timezone
import sys
from types import SimpleNamespace
from typing import Any

from fastapi.testclient import TestClient

from agent.document_ingestion import build_oci_document_ingestion_clients
from agent.main import app


class FakeNotFoundError(Exception):
    """Fake OCI 404 error."""

    status = 404


class FakeServiceError(Exception):
    """Fake non-404 OCI service error."""

    status = 500
    message = "service failed"


class FakeObjectStorageClient:
    """Fake Object Storage client for ingestion endpoint tests."""

    def __init__(self, existing_objects: set[str] | None = None) -> None:
        """Initialize fake Object Storage state.

        Args:
            existing_objects: Object names that already exist.
        """

        self.existing_objects = existing_objects or set()
        self.head_calls: list[str] = []
        self.put_calls: list[tuple[str, bytes]] = []

    def head_object(
        self, namespace_name: str, bucket_name: str, object_name: str
    ) -> None:
        """Record existence checks and raise for missing objects."""

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
        """Record uploaded bytes."""

        del namespace_name, bucket_name
        self.put_calls.append((object_name, put_object_body.read()))


@dataclass
class FakeFileSync:
    """Fake connector file sync resource."""

    id: str
    lifecycle_state: str
    trigger_type: str = "MANUAL"
    display_name: str = "manual-sync"
    vector_store_connector_id: str = "connector-id"
    lifecycle_details: str | None = None
    time_created: datetime | None = None
    time_updated: datetime | None = None


@dataclass
class FakeResponse:
    """Fake OCI SDK response wrapper."""

    data: Any


class FakeGenerativeAiClient:
    """Fake Generative AI client for ingestion endpoint tests."""

    def __init__(self, status_not_found: bool = False) -> None:
        """Initialize fake Generative AI state."""

        self.status_not_found = status_not_found
        self.create_details: Any | None = None
        self.status_job_ids: list[str] = []

    def create_vector_store_connector_file_sync(self, details: Any) -> FakeResponse:
        """Record sync creation details and return a fake job."""

        self.create_details = details
        return FakeResponse(
            FakeFileSync(
                id="sync-123",
                lifecycle_state="ACCEPTED",
                display_name=details.display_name,
            )
        )

    def get_vector_store_connector_file_sync(self, file_sync_id: str) -> FakeResponse:
        """Return fake connector sync status."""

        self.status_job_ids.append(file_sync_id)
        if self.status_not_found:
            raise FakeNotFoundError()
        return FakeResponse(
            FakeFileSync(
                id=file_sync_id,
                lifecycle_state="SUCCEEDED",
                display_name="manual-sync",
                time_created=datetime(2026, 6, 25, 12, 30, tzinfo=timezone.utc),
                time_updated=datetime(2026, 6, 25, 12, 35, tzinfo=timezone.utc),
            )
        )


class FakeOciServiceClient:
    """Fake OCI service client that records config and keyword arguments."""

    def __init__(self, config: dict[str, Any], **kwargs: Any) -> None:
        """Initialize fake service client."""

        self.config = config
        self.kwargs = kwargs


@dataclass
class FakeDetails:
    """Fake CreateVectorStoreConnectorFileSyncDetails replacement."""

    vector_store_connector_id: str
    display_name: str


def test_document_ingestion_endpoint_is_disabled_by_default(
    monkeypatch: Any,
) -> None:
    """Test document ingestion endpoints return 404 when disabled."""

    monkeypatch.delenv("DOCUMENT_INGESTION_ENABLED", raising=False)
    object_storage_client = FakeObjectStorageClient()
    generative_ai_client = FakeGenerativeAiClient()
    _set_ingestion_client_factory(object_storage_client, generative_ai_client)
    client = TestClient(app)

    response = client.post(
        "/documents/ingestions",
        files={"files": ("guide.md", b"# Guide", "text/markdown")},
    )

    assert response.status_code == 404
    assert response.json()["error"] == "Document ingestion is not enabled."
    assert not object_storage_client.put_calls
    assert generative_ai_client.create_details is None


def test_submit_document_ingestion_uploads_files_and_starts_connector_job(
    monkeypatch: Any,
) -> None:
    """Test successful submission uploads documents and starts a sync job."""

    _set_ingestion_env(monkeypatch)
    object_storage_client = FakeObjectStorageClient()
    generative_ai_client = FakeGenerativeAiClient()
    _set_ingestion_client_factory(object_storage_client, generative_ai_client)
    client = TestClient(app)

    response = client.post(
        "/documents/ingestions",
        data={"prefix": "product-docs", "sync_display_name": "manual-sync"},
        files=[
            ("files", ("guide.md", b"# Guide", "text/markdown")),
            ("files", ("faq.txt", b"FAQ", "text/plain")),
        ],
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "submitted",
        "job_id": "sync-123",
        "connector_id": "connector-id",
        "namespace": "namespace",
        "bucket": "bucket",
        "uploaded_objects": ["product-docs/guide.md", "product-docs/faq.txt"],
        "job_lifecycle_state": "ACCEPTED",
        "job_trigger_type": "MANUAL",
        "job_display_name": "manual-sync",
    }
    assert object_storage_client.put_calls == [
        ("product-docs/guide.md", b"# Guide"),
        ("product-docs/faq.txt", b"FAQ"),
    ]
    assert generative_ai_client.create_details == FakeDetails(
        vector_store_connector_id="connector-id",
        display_name="manual-sync",
    )


def test_submit_document_ingestion_rejects_missing_files(monkeypatch: Any) -> None:
    """Test missing multipart files return a predictable validation error."""

    _set_ingestion_env(monkeypatch)
    object_storage_client = FakeObjectStorageClient()
    generative_ai_client = FakeGenerativeAiClient()
    _set_ingestion_client_factory(object_storage_client, generative_ai_client)
    client = TestClient(app)

    response = client.post("/documents/ingestions", data={"prefix": "docs"})

    assert response.status_code == 400
    assert response.json()["error"] == "At least one document is required."
    assert not object_storage_client.put_calls


def test_submit_document_ingestion_rejects_unsupported_file(
    monkeypatch: Any,
) -> None:
    """Test unsupported files are rejected before uploads."""

    _set_ingestion_env(monkeypatch)
    object_storage_client = FakeObjectStorageClient()
    generative_ai_client = FakeGenerativeAiClient()
    _set_ingestion_client_factory(object_storage_client, generative_ai_client)
    client = TestClient(app)

    response = client.post(
        "/documents/ingestions",
        files={"files": ("image.png", b"png", "image/png")},
    )

    assert response.status_code == 400
    assert "unsupported document extension" in response.json()["error"]
    assert not object_storage_client.put_calls
    assert generative_ai_client.create_details is None


def test_submit_document_ingestion_uses_default_prefix(
    monkeypatch: Any,
) -> None:
    """Test runtime default prefix is used when request prefix is omitted."""

    _set_ingestion_env(monkeypatch)
    monkeypatch.setenv("DOCUMENT_INGESTION_DEFAULT_PREFIX", "runtime-docs")
    object_storage_client = FakeObjectStorageClient()
    generative_ai_client = FakeGenerativeAiClient()
    _set_ingestion_client_factory(object_storage_client, generative_ai_client)
    client = TestClient(app)

    response = client.post(
        "/documents/ingestions",
        files={"files": ("guide.md", b"# Guide", "text/markdown")},
    )

    assert response.status_code == 200
    assert response.json()["uploaded_objects"] == ["runtime-docs/guide.md"]
    assert object_storage_client.put_calls == [("runtime-docs/guide.md", b"# Guide")]


def test_submit_document_ingestion_rejects_duplicate_object_names(
    monkeypatch: Any,
) -> None:
    """Test duplicate target object names are rejected before uploads."""

    _set_ingestion_env(monkeypatch)
    object_storage_client = FakeObjectStorageClient()
    generative_ai_client = FakeGenerativeAiClient()
    _set_ingestion_client_factory(object_storage_client, generative_ai_client)
    client = TestClient(app)

    response = client.post(
        "/documents/ingestions",
        files=[
            ("files", ("guide.md", b"first", "text/markdown")),
            ("files", ("guide.md", b"second", "text/markdown")),
        ],
    )

    assert response.status_code == 400
    assert "Duplicate target object name" in response.json()["error"]
    assert not object_storage_client.put_calls


def test_submit_document_ingestion_rejects_path_traversal(
    monkeypatch: Any,
) -> None:
    """Test unsafe path traversal filenames are rejected before uploads."""

    _set_ingestion_env(monkeypatch)
    object_storage_client = FakeObjectStorageClient()
    generative_ai_client = FakeGenerativeAiClient()
    _set_ingestion_client_factory(object_storage_client, generative_ai_client)
    client = TestClient(app)

    response = client.post(
        "/documents/ingestions",
        files={"files": ("../guide.md", b"# Guide", "text/markdown")},
    )

    assert response.status_code == 400
    assert "path traversal" in response.json()["error"]
    assert not object_storage_client.put_calls


def test_submit_document_ingestion_rejects_existing_object_without_overwrite(
    monkeypatch: Any,
) -> None:
    """Test existing staged objects return a conflict by default."""

    _set_ingestion_env(monkeypatch)
    object_storage_client = FakeObjectStorageClient(existing_objects={"guide.md"})
    generative_ai_client = FakeGenerativeAiClient()
    _set_ingestion_client_factory(object_storage_client, generative_ai_client)
    client = TestClient(app)

    response = client.post(
        "/documents/ingestions",
        files={"files": ("guide.md", b"# Guide", "text/markdown")},
    )

    assert response.status_code == 409
    assert "already exist" in response.json()["error"]
    assert not object_storage_client.put_calls
    assert generative_ai_client.create_details is None


def test_submit_document_ingestion_allows_overwrite(
    monkeypatch: Any,
) -> None:
    """Test overwrite mode uploads even when an object already exists."""

    _set_ingestion_env(monkeypatch)
    object_storage_client = FakeObjectStorageClient(existing_objects={"guide.md"})
    generative_ai_client = FakeGenerativeAiClient()
    _set_ingestion_client_factory(object_storage_client, generative_ai_client)
    client = TestClient(app)

    response = client.post(
        "/documents/ingestions",
        data={"overwrite": "true"},
        files={"files": ("guide.md", b"# Guide", "text/markdown")},
    )

    assert response.status_code == 200
    assert not object_storage_client.head_calls
    assert object_storage_client.put_calls == [("guide.md", b"# Guide")]


def test_get_document_ingestion_status_returns_connector_job_state(
    monkeypatch: Any,
) -> None:
    """Test connector job status is returned from OCI."""

    _set_ingestion_env(monkeypatch)
    object_storage_client = FakeObjectStorageClient()
    generative_ai_client = FakeGenerativeAiClient()
    _set_ingestion_client_factory(object_storage_client, generative_ai_client)
    client = TestClient(app)

    response = client.get("/documents/ingestions/sync-123")

    assert response.status_code == 200
    assert response.json() == {
        "job_id": "sync-123",
        "connector_id": "connector-id",
        "lifecycle_state": "SUCCEEDED",
        "display_name": "manual-sync",
        "time_created": "2026-06-25T12:30:00+00:00",
        "time_updated": "2026-06-25T12:35:00+00:00",
        "trigger_type": "MANUAL",
    }
    assert generative_ai_client.status_job_ids == ["sync-123"]


def test_get_document_ingestion_status_returns_404_for_missing_job(
    monkeypatch: Any,
) -> None:
    """Test missing connector jobs return 404."""

    _set_ingestion_env(monkeypatch)
    object_storage_client = FakeObjectStorageClient()
    generative_ai_client = FakeGenerativeAiClient(status_not_found=True)
    _set_ingestion_client_factory(object_storage_client, generative_ai_client)
    client = TestClient(app)

    response = client.get("/documents/ingestions/missing-sync")

    assert response.status_code == 404
    assert "was not found" in response.json()["error"]


def test_document_ingestion_oci_clients_use_resource_principal(
    monkeypatch: Any,
) -> None:
    """Test OCI client factory supports Resource Principal authentication."""

    signer = object()
    fake_oci = SimpleNamespace(
        auth=SimpleNamespace(
            signers=SimpleNamespace(get_resource_principals_signer=lambda: signer)
        ),
        object_storage=SimpleNamespace(ObjectStorageClient=FakeOciServiceClient),
        generative_ai=SimpleNamespace(GenerativeAiClient=FakeOciServiceClient),
    )
    monkeypatch.setitem(sys.modules, "oci", fake_oci)
    monkeypatch.setenv("OCI_AUTH_MODE", "resource_principal")
    monkeypatch.setenv("OCI_REGION", "eu-frankfurt-1")

    object_storage_client, generative_ai_client = build_oci_document_ingestion_clients()

    assert object_storage_client.config == {"region": "eu-frankfurt-1"}
    assert object_storage_client.kwargs == {"signer": signer}
    assert generative_ai_client.config == {"region": "eu-frankfurt-1"}
    assert generative_ai_client.kwargs == {"signer": signer}


def test_document_ingestion_oci_clients_can_use_config_file(
    monkeypatch: Any,
) -> None:
    """Test OCI client factory supports local config-file authentication."""

    config_calls: list[dict[str, str]] = []

    def fake_from_file(file_location: str, profile_name: str) -> dict[str, str]:
        config_calls.append(
            {"file_location": file_location, "profile_name": profile_name}
        )
        return {"region": "eu-frankfurt-1", "profile": profile_name}

    fake_oci = SimpleNamespace(
        config=SimpleNamespace(from_file=fake_from_file),
        object_storage=SimpleNamespace(ObjectStorageClient=FakeOciServiceClient),
        generative_ai=SimpleNamespace(GenerativeAiClient=FakeOciServiceClient),
    )
    monkeypatch.setitem(sys.modules, "oci", fake_oci)
    monkeypatch.setenv("OCI_AUTH_MODE", "config_file")
    monkeypatch.setenv("OCI_CONFIG_FILE", "/tmp/oci-config")
    monkeypatch.setenv("OCI_PROFILE", "LOCAL")

    object_storage_client, generative_ai_client = build_oci_document_ingestion_clients()

    assert config_calls == [
        {"file_location": "/tmp/oci-config", "profile_name": "LOCAL"}
    ]
    assert object_storage_client.config == {
        "region": "eu-frankfurt-1",
        "profile": "LOCAL",
    }
    assert object_storage_client.kwargs == {}
    assert generative_ai_client.config == {
        "region": "eu-frankfurt-1",
        "profile": "LOCAL",
    }
    assert generative_ai_client.kwargs == {}


def test_document_ingestion_oci_clients_reject_openai_api_key_mode(
    monkeypatch: Any,
) -> None:
    """Test OpenAI-compatible API key mode cannot authenticate OCI uploads."""

    fake_oci = SimpleNamespace()
    monkeypatch.setitem(sys.modules, "oci", fake_oci)
    monkeypatch.setenv("OCI_AUTH_MODE", "openai_api_key")

    try:
        build_oci_document_ingestion_clients()
    except RuntimeError as exc:
        assert "openai_api_key cannot authenticate Object Storage" in str(exc)
    else:
        raise AssertionError("Expected RuntimeError for openai_api_key mode.")


def _set_ingestion_env(monkeypatch: Any) -> None:
    """Set required document ingestion environment variables."""

    monkeypatch.setenv("DOCUMENT_INGESTION_ENABLED", "true")
    monkeypatch.setenv("OCI_AUTH_MODE", "resource_principal")
    monkeypatch.setenv("OCI_DOCUMENT_NAMESPACE", "namespace")
    monkeypatch.setenv("OCI_DOCUMENT_BUCKET", "bucket")
    monkeypatch.setenv("OCI_VECTOR_STORE_CONNECTOR_ID", "connector-id")


def _set_ingestion_client_factory(
    object_storage_client: FakeObjectStorageClient,
    generative_ai_client: FakeGenerativeAiClient,
) -> None:
    """Configure fake OCI clients on the FastAPI application."""

    app.state.document_ingestion_client_factory = lambda: (
        object_storage_client,
        generative_ai_client,
    )
    app.state.file_sync_details_factory = lambda: FakeDetails
