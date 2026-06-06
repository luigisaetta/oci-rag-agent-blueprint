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
from agent_factory_api.commands import (  # pylint: disable=wrong-import-position
    AGENT_RUNTIME_ENVIRONMENT_VARIABLES,
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
        payload["outputs"]["image_reference"]
        == "eu-frankfurt-1.ocir.io/<tenancy-namespace>/"
        "oci-rag-agent-blueprint-agent:0.1.0"
    )
    runtime_environment = payload["outputs"]["runtime_environment"]
    assert set(runtime_environment) == set(AGENT_RUNTIME_ENVIRONMENT_VARIABLES)
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
            "eu-frankfurt-1.ocir.io/<tenancy-namespace>/"
            "oci-rag-agent-blueprint-agent"
        ),
        "tag": "0.1.0",
    }
    assert any(step["step_id"] == "docker-build" for step in payload["steps"])
    assert any(step["step_id"] == "runtime-environment" for step in payload["steps"])


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


def test_agent_factory_apply_plan_passes_runtime_environment_to_deployment() -> None:
    """Test real deployment command plan includes runtime environment injection."""

    RUNS.clear()
    client = TestClient(app)
    request_payload = _valid_payload()
    request_payload["dry_run"] = False
    request_payload["vector_store_name"] = "ocid1.vectorstore.oc1..example"

    response = client.post("/factory/deployments", json=request_payload)

    assert response.status_code == 201
    payload = response.json()
    assert "--environment-variables" in payload["commands_text"]
    assert "hosted-application-environment-variables.json" in (payload["commands_text"])
    assert "hosted-deployment create" in payload["commands_text"]
    runtime_environment = payload["outputs"]["runtime_environment"]
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
