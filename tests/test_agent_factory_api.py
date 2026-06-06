"""
Author: L. Saetta
Date last modified: 2026-06-06
License: MIT
Description: Unit tests for the Agent Factory FastAPI skeleton.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

AGENT_FACTORY_API_PATH = Path(__file__).resolve().parents[1] / "agent-factory" / "api"
sys.path.insert(0, str(AGENT_FACTORY_API_PATH))

from agent_factory_api.app import RUNS, app  # pylint: disable=wrong-import-position


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
    assert "docker buildx build" in payload["commands_text"]
    assert "docker manifest inspect" in payload["commands_text"]
    assert (
        payload["outputs"]["image_reference"]
        == "eu-frankfurt-1.ocir.io/<tenancy-namespace>/"
        "oci-rag-agent-blueprint-agent:0.1.0"
    )
    assert any(step["step_id"] == "docker-build" for step in payload["steps"])


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
