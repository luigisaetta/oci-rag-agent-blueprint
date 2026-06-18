"""
Author: L. Saetta
Date last modified: 2026-06-17
License: MIT
Description: Unit tests for the Agent Factory FastAPI skeleton.
"""

from __future__ import annotations

# pylint: disable=duplicate-code,too-few-public-methods,too-many-lines

import sys
import subprocess
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

AGENT_FACTORY_API_PATH = Path(__file__).resolve().parents[1] / "agent-factory" / "api"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_FACTORY_API_PATH))

import agent_factory_api.resources as factory_resources  # pylint: disable=wrong-import-position
import agent_factory_api.executor as factory_executor  # pylint: disable=wrong-import-position
from agent_factory_api.app import (  # pylint: disable=wrong-import-position
    RUNS,
    _build_hosted_application_urls,
    app,
)
from agent_factory_api.commands import (  # pylint: disable=wrong-import-position
    AGENT_RUNTIME_ENVIRONMENT_VARIABLES,
    build_resolved_identifiers,
)
from agent_factory_api.executor import (  # pylint: disable=wrong-import-position
    CommandExecutionError,
    _extract_identifier,
    _find_existing_hosted_application_id,
    _load_json_output,
    _replace_placeholders,
)
from agent_factory_api.resources import (  # pylint: disable=wrong-import-position
    BucketResult,
    ConnectorResult,
    FoundationResourcesResult,
    ObjectStorageBucketManager,
    ProjectResult,
    ResourceProvisioningError,
    VectorStoreConnectorManager,
    VectorStoreManager,
    VectorStoreResult,
    _build_control_plane_base_url,
    _load_oci_config,
    _resolve_compartment_name,
    _resolve_control_plane_auth_mode,
    _validate_oci_auth_config,
    preflight_foundation_resources,
    provision_foundation_resources,
    resolve_genai_project,
)


def test_agent_factory_health_endpoint() -> None:
    """Test Agent Factory health endpoint."""

    client = TestClient(app)

    response = client.get("/factory/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_agent_factory_compose_api_container_can_use_docker() -> None:
    """Test Agent Factory API image and Compose expose Docker CLI access."""

    api_dockerfile = (PROJECT_ROOT / "agent-factory" / "api" / "Dockerfile").read_text(
        encoding="utf-8"
    )
    api_requirements = (
        PROJECT_ROOT / "agent-factory" / "api" / "requirements.txt"
    ).read_text(encoding="utf-8")
    compose_file = (PROJECT_ROOT / "agent-factory" / "docker-compose.yml").read_text(
        encoding="utf-8"
    )
    start_script = (PROJECT_ROOT / "start_factory.sh").read_text(encoding="utf-8")
    stop_script = (PROJECT_ROOT / "stop_factory.sh").read_text(encoding="utf-8")

    assert "docker.io docker-cli" in api_dockerfile
    assert "oci-cli" in api_requirements
    assert compose_file.startswith('version: "2.4"')
    assert not compose_file.startswith("name:")
    assert ":-" not in compose_file
    assert "AGENT_FACTORY_REPO_ROOT: /workspace" in compose_file
    assert "- ..:/workspace:ro" in compose_file
    assert "/var/run/docker.sock:/var/run/docker.sock" in compose_file
    assert '-p "${COMPOSE_PROJECT_NAME}"' in start_script
    assert '-p "${COMPOSE_PROJECT_NAME}"' in stop_script
    assert "docker compose version" in start_script
    assert "docker compose version" in stop_script
    assert start_script.index("docker compose version") < start_script.index(
        "command -v docker-compose"
    )
    assert stop_script.index("docker compose version") < stop_script.index(
        "command -v docker-compose"
    )
    assert 'export OCI_PROFILE="${OCI_PROFILE:-DEFAULT}"' in start_script
    assert 'export OCI_AUTH_MODE="${OCI_AUTH_MODE:-user_principal}"' in start_script
    assert "build --no-cache factory-api" in start_script
    assert "up -d --build --force-recreate" in start_script


def test_agent_factory_ui_derives_remote_backend_url() -> None:
    """Test UI can target the host that served it instead of localhost only."""

    page_source = (PROJECT_ROOT / "agent-factory" / "ui" / "app" / "page.js").read_text(
        encoding="utf-8"
    )

    assert "window.location.hostname" in page_source
    assert ":8081/factory/deployments" in page_source
    assert "LOCAL_BACKEND_URL" in page_source


def test_agent_factory_ui_exposes_ocir_login_check() -> None:
    """Test UI exposes a direct OCIR credential check action."""

    page_source = (PROJECT_ROOT / "agent-factory" / "ui" / "app" / "page.js").read_text(
        encoding="utf-8"
    )

    assert "Check credentials" in page_source
    assert "/factory/ocir-login/check" in page_source
    assert "ocirLoginCheck" in page_source


def test_agent_factory_ui_exposes_local_ocir_credential_storage() -> None:
    """Test UI can save and reload OCIR credentials locally."""

    page_source = (PROJECT_ROOT / "agent-factory" / "ui" / "app" / "page.js").read_text(
        encoding="utf-8"
    )

    assert "OCIR_CREDENTIALS_STORAGE_KEY" in page_source
    assert "window.localStorage.setItem" in page_source
    assert "window.localStorage.getItem" in page_source
    assert "window.localStorage.removeItem" in page_source
    assert "Save locally" in page_source
    assert "Load saved" in page_source
    assert "Forget" in page_source
    saved_payload = page_source.split("JSON.stringify({", 1)[1].split("})", 1)[0]
    assert "ocir_username" in saved_payload
    assert "ocir_password" in saved_payload
    assert "region" not in saved_payload


def test_agent_factory_checks_ocir_login_credentials(monkeypatch) -> None:
    """Test OCIR login check endpoint validates Docker credentials directly."""

    client = TestClient(app)

    def fake_validate_ocir_login(**kwargs: Any) -> dict[str, str]:
        return {
            "ocir_registry": str(kwargs["registry"]),
            "ocir_username": str(kwargs["username"]),
        }

    monkeypatch.setattr(
        "agent_factory_api.app.validate_ocir_login",
        fake_validate_ocir_login,
    )

    response = client.post(
        "/factory/ocir-login/check",
        json={
            "region": "eu-frankfurt-1",
            "ocir_username": " test-ocir-user ",
            "ocir_password": " test-ocir-password ",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload == {
        "status": "succeeded",
        "message": "OCIR Docker login succeeded.",
        "ocir_registry": "fra.ocir.io",
        "ocir_username": "test-ocir-user",
    }
    assert "test-ocir-password" not in response.text


def test_agent_factory_ocir_login_check_returns_actionable_failure(
    monkeypatch,
) -> None:
    """Test OCIR login check endpoint returns sanitized login failures."""

    client = TestClient(app)

    def fake_validate_ocir_login(**kwargs: Any) -> dict[str, str]:
        _ = kwargs
        raise ResourceProvisioningError(
            "OCIR Docker login failed for fra.ocir.io: unauthorized"
        )

    monkeypatch.setattr(
        "agent_factory_api.app.validate_ocir_login",
        fake_validate_ocir_login,
    )

    response = client.post(
        "/factory/ocir-login/check",
        json={
            "region": "eu-frankfurt-1",
            "ocir_username": "test-ocir-user",
            "ocir_password": "test-ocir-password",
        },
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["status"] == "failed"
    assert payload["error"] == "OCIR Docker login failed for fra.ocir.io: unauthorized"
    assert "test-ocir-password" not in response.text


def test_agent_factory_dry_run_generates_redacted_command_plan(monkeypatch) -> None:
    """Test dry-run deployment planning without secret exposure."""

    RUNS.clear()
    client = TestClient(app)
    _install_fake_preflight(monkeypatch)

    response = client.post("/factory/deployments", json=_valid_payload())

    assert response.status_code == 201
    payload = response.json()
    assert payload["dry_run"] is True
    assert payload["status"] == "succeeded"
    assert payload["request"]["openai_api_key"] == "********"
    assert payload["request"]["ocir_password"] == "********"
    assert "test-api-key" not in response.text
    assert "test-ocir-password" not in response.text
    assert "docker build --platform linux/amd64" in payload["commands_text"]
    assert "docker manifest inspect" in payload["commands_text"]
    assert "curl -fsS" not in payload["commands_text"]
    assert "urllib.request.urlopen" in payload["commands_text"]
    assert "json.tool" not in payload["commands_text"]
    assert "--wait-for-state SUCCEEDED" in payload["commands_text"]
    assert "hosted-application-collection list-hosted-applications" in (
        payload["commands_text"]
    )
    assert "hosted-deployment create-hosted-deployment-single-docker-artifact" in (
        payload["commands_text"]
    )
    assert "--active-artifact-container-uri" in payload["commands_text"]
    assert "--active-artifact-tag" in payload["commands_text"]
    assert "--active-artifact " not in payload["commands_text"]
    assert (
        payload["outputs"]["image_reference"] == "fra.ocir.io/test-namespace/"
        "oci-rag-agent-blueprint-agent:0.1.0"
    )
    assert "<tenancy-namespace>" not in payload["commands_text"]
    runtime_environment = payload["outputs"]["runtime_environment"]
    assert set(runtime_environment) == set(AGENT_RUNTIME_ENVIRONMENT_VARIABLES)
    assert payload["outputs"]["resolved_identifiers"] == {
        "compartment_id": "ocid1.compartment.oc1..example",
        "genai_project_id": "ocid1.generativeaiproject.oc1..example",
        "object_storage_namespace": "test-namespace",
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
        "containerUri": "fra.ocir.io/test-namespace/oci-rag-agent-blueprint-agent",
        "tag": "0.1.0",
    }
    assert any(step["step_id"] == "docker-build" for step in payload["steps"])
    runtime_environment_step = next(
        step for step in payload["steps"] if step["step_id"] == "runtime-environment"
    )
    assert runtime_environment_step["command"] is None
    registry_login_step = next(
        step for step in payload["steps"] if step["step_id"] == "registry-login"
    )
    assert registry_login_step["outputs"] == {
        "ocir_registry": "fra.ocir.io",
        "ocir_username": "test-ocir-user",
    }


def test_agent_factory_dry_run_generates_idcs_auth_config(monkeypatch) -> None:
    """Test dry-run planning for IDCS-protected Hosted Applications."""

    RUNS.clear()
    client = TestClient(app)
    _install_fake_preflight(monkeypatch)
    request_payload = _valid_payload()
    request_payload.update(
        {
            "jwt_protection_enabled": True,
            "identity_domain_compartment": "Security",
            "identity_domain_url": "https://idcs-example.identity.oraclecloud.com",
            "auth_scope": "/.default",
            "auth_audience": "rag-agent",
        }
    )

    response = client.post("/factory/deployments", json=request_payload)

    assert response.status_code == 201
    payload = response.json()
    inbound_auth_config = payload["outputs"]["dry_run_artifacts"][
        "hosted-application-inbound-auth-config.json"
    ]
    assert inbound_auth_config == {
        "inboundAuthConfigType": "IDCS_AUTH_CONFIG",
        "idcsConfig": {
            "domainUrl": "https://idcs-example.identity.oraclecloud.com",
            "scope": "rag-agent/.default",
            "audience": "rag-agent",
        },
    }
    assert payload["request"]["identity_domain_compartment"] == "Security"
    assert payload["request"]["identity_domain_url"] == (
        "https://idcs-example.identity.oraclecloud.com"
    )


def test_agent_factory_strips_surrounding_text_input_whitespace(monkeypatch) -> None:
    """Test pasted text values are normalized before planning and login checks."""

    RUNS.clear()
    client = TestClient(app)
    _install_fake_preflight(monkeypatch)
    request_payload = _valid_payload()
    request_payload["ocir_username"] = " test-ocir-user "
    request_payload["ocir_password"] = " test-ocir-password "
    request_payload["container_repository_name"] = " oci-rag-agent-blueprint-agent "

    captured_login: dict[str, str] = {}

    def fake_validate_ocir_login(**kwargs: Any) -> dict[str, str]:
        captured_login["username"] = str(kwargs["username"])
        captured_login["password"] = str(kwargs["password"])
        return {
            "ocir_registry": str(kwargs["registry"]),
            "ocir_username": str(kwargs["username"]),
        }

    monkeypatch.setattr(
        "agent_factory_api.app.validate_ocir_login",
        fake_validate_ocir_login,
    )

    response = client.post("/factory/deployments", json=request_payload)

    assert response.status_code == 201
    payload = response.json()
    assert captured_login == {
        "username": "test-ocir-user",
        "password": "test-ocir-password",
    }
    assert payload["request"]["ocir_username"] == "test-ocir-user"
    assert (
        payload["outputs"]["image_reference"]
        == "fra.ocir.io/test-namespace/oci-rag-agent-blueprint-agent:0.1.0"
    )


def test_agent_factory_resolves_names_before_downstream_commands(monkeypatch) -> None:
    """Test names are converted to OCID placeholders for downstream commands."""

    RUNS.clear()
    client = TestClient(app)
    _install_fake_preflight(
        monkeypatch,
        compartment_id="ocid1.compartment.oc1..resolved",
        project_id="ocid1.generativeaiproject.oc1..resolved",
    )
    request_payload = _valid_payload()
    request_payload["compartment"] = "lsaetta"
    request_payload["genai_project"] = "agent-factory-project"

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
        "get",
        "--compartment-id",
        "ocid1.compartment.oc1..resolved",
    ]
    assert commands[1] == [
        "oci",
        "--region",
        "eu-frankfurt-1",
        "--output",
        "json",
        "generative-ai",
        "project",
        "get",
        "--project-id",
        "ocid1.generativeaiproject.oc1..resolved",
    ]
    assert payload["outputs"]["resolved_identifiers"]["compartment_id"] == (
        "ocid1.compartment.oc1..resolved"
    )
    assert payload["outputs"]["resolved_identifiers"]["genai_project_id"] == (
        "ocid1.generativeaiproject.oc1..resolved"
    )
    assert payload["outputs"]["runtime_environment"]["OCI_COMPARTMENT_ID"] == (
        "ocid1.compartment.oc1..resolved"
    )
    assert payload["outputs"]["runtime_environment"]["OCI_PROJECT_ID"] == (
        "ocid1.generativeaiproject.oc1..resolved"
    )
    assert (
        payload["outputs"]["dry_run_artifacts"]["create-hosted-application.json"][
            "compartmentId"
        ]
        == "ocid1.compartment.oc1..resolved"
    )
    assert (
        payload["outputs"]["dry_run_artifacts"]["create-hosted-deployment.json"][
            "compartmentId"
        ]
        == "ocid1.compartment.oc1..resolved"
    )
    assert "--namespace-name test-namespace" in payload["commands_text"]
    assert (
        "--compartment-id ocid1.compartment.oc1..resolved" in payload["commands_text"]
    )


def test_agent_factory_requires_auth_fields_when_jwt_is_enabled() -> None:
    """Test JWT protection requires Identity Domain auth settings."""

    client = TestClient(app)
    request_payload = _valid_payload()
    request_payload["jwt_protection_enabled"] = True

    response = client.post("/factory/deployments", json=request_payload)

    assert response.status_code == 400
    field_errors = response.json()["field_errors"]
    assert field_errors == {
        "identity_domain_compartment": "This field is required when auth is enabled.",
        "identity_domain_url": "This field is required when auth is enabled.",
        "auth_scope": "This field is required when auth is enabled.",
        "auth_audience": "This field is required when auth is enabled.",
    }


def test_agent_factory_rejects_identity_domain_display_name_for_auth() -> None:
    """Test IDCS auth requires the exact Identity Domain URL."""

    client = TestClient(app)
    request_payload = _valid_payload()
    request_payload.update(
        {
            "jwt_protection_enabled": True,
            "identity_domain_compartment": "Security",
            "identity_domain_url": "OracleIdentityCloudService",
            "auth_scope": "urn:opc:resource:consumer::all",
            "auth_audience": "rag-agent",
        }
    )

    response = client.post("/factory/deployments", json=request_payload)

    assert response.status_code == 400
    assert response.json()["field_errors"]["identity_domain_url"] == (
        "Identity Domain URL must be the exact https:// URL from OCI Console."
    )


def test_agent_factory_rejects_unsupported_options() -> None:
    """Test first-version disabled options are rejected."""

    client = TestClient(app)
    request_payload = _valid_payload()
    request_payload["endpoint_visibility"] = "private"
    request_payload["network_mode"] = "custom"

    response = client.post("/factory/deployments", json=request_payload)

    assert response.status_code == 400
    field_errors = response.json()["field_errors"]
    assert "endpoint_visibility" in field_errors
    assert "network_mode" in field_errors


def test_agent_factory_dry_run_fails_on_invalid_ocir_credentials(monkeypatch) -> None:
    """Test dry-run validates OCIR Docker credentials."""

    RUNS.clear()
    client = TestClient(app)
    _install_fake_preflight(monkeypatch)

    def fake_validate_ocir_login(**kwargs: Any) -> dict[str, str]:
        _ = kwargs
        raise ResourceProvisioningError(
            "OCIR Docker login failed for fra.ocir.io: unauthorized"
        )

    monkeypatch.setattr(
        "agent_factory_api.app.validate_ocir_login",
        fake_validate_ocir_login,
    )

    response = client.post("/factory/deployments", json=_valid_payload())

    assert response.status_code == 201
    payload = response.json()
    assert payload["status"] == "failed"
    assert payload["error"] == (
        "OCIR Docker login failed for fra.ocir.io: unauthorized"
    )
    registry_login_step = next(
        step for step in payload["steps"] if step["step_id"] == "registry-login"
    )
    assert registry_login_step["status"] == "failed"
    assert "test-ocir-password" not in response.text


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


def test_agent_factory_uses_region_key_for_ocir_registry(monkeypatch) -> None:
    """Test OCIR image references use the OCI region key, not region name."""

    RUNS.clear()
    client = TestClient(app)
    _install_fake_preflight(monkeypatch)
    request_payload = _valid_payload()
    request_payload["region"] = "us-chicago-1"
    request_payload["model_id"] = "google.gemini-2.5-pro"

    response = client.post("/factory/deployments", json=request_payload)

    assert response.status_code == 201
    payload = response.json()
    assert payload["outputs"]["image_reference"] == (
        "ord.ocir.io/test-namespace/oci-rag-agent-blueprint-agent:0.1.0"
    )
    assert "docker login ord.ocir.io --username test-ocir-user" in (
        payload["commands_text"]
    )
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


def test_agent_factory_returns_saved_run_and_commands(monkeypatch) -> None:
    """Test deployment run status and command script endpoints."""

    RUNS.clear()
    client = TestClient(app)
    _install_fake_preflight(monkeypatch)

    create_response = client.post("/factory/deployments", json=_valid_payload())
    deployment_run_id = create_response.json()["deployment_run_id"]

    status_response = client.get(f"/factory/deployments/{deployment_run_id}")
    commands_response = client.get(f"/factory/deployments/{deployment_run_id}/commands")

    assert status_response.status_code == 200
    assert commands_response.status_code == 200
    assert commands_response.text.startswith("#!/usr/bin/env bash")


def test_agent_factory_treats_vector_store_service_id_as_resolved() -> None:
    """Test Vector Store service IDs are valid runtime identifiers."""

    request_payload = _valid_payload()
    request_payload["vector_store_name"] = "vs_fra_1234567890"

    identifiers = build_resolved_identifiers(request_payload)

    assert identifiers["vector_store_id"] == "vs_fra_1234567890"


def test_agent_factory_extracts_hosted_application_id_from_work_request() -> None:
    """Test Hosted Application ID extraction skips unrelated OCIDs."""

    command_output = {
        "data": {
            "compartment-id": "ocid1.compartment.oc1..example",
            "id": "ocid1.generativeaiworkrequest.oc1..example",
            "resources": [
                {
                    "entity-type": "HOSTED_APPLICATION",
                    "identifier": "ocid1.generativeaihostedapplication.oc1..example",
                }
            ],
        }
    }

    assert (
        _extract_identifier(command_output, entity_type="HOSTED_APPLICATION")
        == "ocid1.generativeaihostedapplication.oc1..example"
    )


def test_agent_factory_extracts_direct_hosted_application_id() -> None:
    """Test Hosted Application ID extraction ignores compartment IDs."""

    command_output = {
        "data": {
            "compartment-id": "ocid1.compartment.oc1..example",
            "id": "ocid1.generativeaihostedapplication.oc1..example",
            "lifecycle-state": "ACTIVE",
        }
    }

    assert (
        _extract_identifier(command_output, entity_type="HOSTED_APPLICATION")
        == "ocid1.generativeaihostedapplication.oc1..example"
    )


def test_agent_factory_extracts_direct_hosted_deployment_id() -> None:
    """Test Hosted Deployment ID extraction ignores application IDs."""

    command_output = {
        "data": {
            "hosted-application-id": (
                "ocid1.generativeaihostedapplication.oc1..example"
            ),
            "id": "ocid1.generativeaihosteddeployment.oc1..example",
            "compartment-id": "ocid1.compartment.oc1..example",
        }
    }

    assert (
        _extract_identifier(command_output, entity_type="HOSTED_DEPLOYMENT")
        == "ocid1.generativeaihosteddeployment.oc1..example"
    )


def test_agent_factory_loads_oci_json_output_with_status_prefix() -> None:
    """Test OCI CLI JSON parsing tolerates informational text prefixes."""

    result = subprocess.CompletedProcess(
        ["oci"],
        0,
        stdout='Action completed. Waiting briefly...\n{"data": {"id": "ocid1.test"}}',
        stderr="",
    )

    assert _load_json_output(
        "hosted-deployment",
        result,
        secrets=[],
    ) == {"data": {"id": "ocid1.test"}}


def test_agent_factory_finds_existing_hosted_application(monkeypatch) -> None:
    """Test live deployment reuses an existing non-deleted Hosted Application."""

    commands: list[list[str]] = []
    events: list[tuple[str, str, dict[str, Any] | None]] = []

    def fake_run_command(
        command: list[str], **kwargs: Any
    ) -> subprocess.CompletedProcess[str]:
        _ = kwargs
        commands.append(command)
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=(
                '{"data": {"items": ['
                '{"display-name": "agent-factory-app", '
                '"id": "ocid1.generativeaihostedapplication.oc1..existing", '
                '"lifecycle-state": "ACTIVE"}'
                "]}}"
            ),
            stderr="",
        )

    monkeypatch.setattr(
        "agent_factory_api.executor._run_command",
        fake_run_command,
    )

    hosted_application_id = _find_existing_hosted_application_id(
        payload=_valid_payload(),
        compartment_id="ocid1.compartment.oc1..example",
        progress_callback=lambda step_id, status, outputs: events.append(
            (step_id, status, outputs)
        ),
        cwd=PROJECT_ROOT,
        secrets=[],
    )

    assert hosted_application_id == (
        "ocid1.generativeaihostedapplication.oc1..existing"
    )
    assert commands[0][6:9] == [
        "hosted-application-collection",
        "list-hosted-applications",
        "--compartment-id",
    ]
    assert events[-1] == (
        "hosted-application",
        "succeeded",
        {
            "hosted_application_id": (
                "ocid1.generativeaihostedapplication.oc1..existing"
            ),
            "reused": True,
            "display_name": "agent-factory-app",
            "lifecycle_state": "ACTIVE",
        },
    )


def test_agent_factory_waits_for_existing_creating_hosted_application(
    monkeypatch,
) -> None:
    """Test existing non-active Hosted Applications are waited before reuse."""

    commands: list[list[str]] = []
    events: list[tuple[str, str, dict[str, Any] | None]] = []

    def fake_run_command(
        command: list[str], **kwargs: Any
    ) -> subprocess.CompletedProcess[str]:
        _ = kwargs
        commands.append(command)
        if "list-hosted-applications" in command:
            stdout = (
                '{"data": {"items": ['
                '{"display-name": "agent-factory-app", '
                '"id": "ocid1.generativeaihostedapplication.oc1..creating", '
                '"lifecycle-state": "CREATING"}'
                "]}}"
            )
        else:
            stdout = (
                '{"data": {'
                '"id": "ocid1.generativeaihostedapplication.oc1..creating", '
                '"lifecycle-state": "ACTIVE"'
                "}}"
            )
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(
        "agent_factory_api.executor._run_command",
        fake_run_command,
    )

    hosted_application_id = _find_existing_hosted_application_id(
        payload=_valid_payload(),
        compartment_id="ocid1.compartment.oc1..example",
        progress_callback=lambda step_id, status, outputs: events.append(
            (step_id, status, outputs)
        ),
        cwd=PROJECT_ROOT,
        secrets=[],
    )

    assert hosted_application_id == (
        "ocid1.generativeaihostedapplication.oc1..creating"
    )
    assert commands[1] == [
        "oci",
        "--region",
        "eu-frankfurt-1",
        "--output",
        "json",
        "generative-ai",
        "hosted-application",
        "get",
        "--hosted-application-id",
        "ocid1.generativeaihostedapplication.oc1..creating",
        "--wait-for-state",
        "SUCCEEDED",
    ]
    assert events[-1][0:2] == ("hosted-application", "succeeded")
    assert events[-1][2]["lifecycle_state"] == "ACTIVE"


def test_agent_factory_apply_plan_passes_runtime_environment_to_deployment(
    monkeypatch,
) -> None:
    """Test real deployment command plan includes runtime environment injection."""

    RUNS.clear()
    client = TestClient(app)
    request_payload = _valid_payload()
    request_payload["dry_run"] = False
    request_payload["vector_store_name"] = "ocid1.vectorstore.oc1..example"
    _install_fake_live_executor(monkeypatch)

    def fake_provision(
        payload: dict[str, Any],
        progress_callback: Any | None = None,
    ) -> FoundationResourcesResult:
        _ = progress_callback
        return FoundationResourcesResult(
            compartment_id=payload["compartment"],
            project=ProjectResult(
                project_id=payload["genai_project"],
                name="agent-factory-project",
            ),
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
        )

    monkeypatch.setattr(
        "agent_factory_api.app.provision_foundation_resources",
        fake_provision,
    )

    response = client.post("/factory/deployments", json=request_payload)

    assert response.status_code == 201
    assert response.json()["status"] == "running"
    payload = _fetch_run(client, response.json()["deployment_run_id"])
    assert payload["status"] == "succeeded"
    assert "--environment-variables" in payload["commands_text"]
    assert "hosted-application-environment-variables.json" in (payload["commands_text"])
    assert "hosted-deployment create-hosted-deployment-single-docker-artifact" in (
        payload["commands_text"]
    )
    assert "--wait-for-state SUCCEEDED" in payload["commands_text"]
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
    _install_fake_live_executor(monkeypatch)

    def fake_provision(
        payload: dict[str, Any],
        progress_callback: Any | None = None,
    ) -> FoundationResourcesResult:
        assert payload["bucket_name"] == "agent-factory-docs"
        assert payload["vector_store_name"] == "agent-factory-vector-store"
        _notify_fake_resource_progress(progress_callback)
        return FoundationResourcesResult(
            compartment_id="ocid1.compartment.oc1..example",
            project=ProjectResult(
                project_id="ocid1.generativeaiproject.oc1..example",
                name="agent-factory-project",
            ),
            bucket=BucketResult(
                bucket_name="agent-factory-docs",
                namespace_name="test-namespace",
                lifecycle_state="ACTIVE",
                created=True,
            ),
            vector_store=VectorStoreResult(
                vector_store_id="vs_fra_created",
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
    assert payload["status"] == "running"
    payload = _fetch_run(client, payload["deployment_run_id"])
    assert payload["status"] == "succeeded"
    assert payload["outputs"]["resolved_identifiers"]["compartment_id"] == (
        "ocid1.compartment.oc1..example"
    )
    assert payload["outputs"]["resolved_identifiers"]["genai_project_id"] == (
        "ocid1.generativeaiproject.oc1..example"
    )
    assert payload["outputs"]["resolved_identifiers"]["vector_store_id"] == (
        "vs_fra_created"
    )
    assert payload["outputs"]["runtime_environment"]["OCI_VECTOR_STORE_ID"] == (
        "vs_fra_created"
    )
    environment_by_name = {
        item["name"]: item
        for item in payload["outputs"]["dry_run_artifacts"][
            "hosted-application-environment-variables.json"
        ]
    }
    assert environment_by_name["OCI_VECTOR_STORE_ID"]["value"] == ("vs_fra_created")
    assert "<created-or-resolved-vector-store-ocid>" not in str(
        payload["outputs"]["dry_run_artifacts"]
    )
    assert payload["outputs"]["resolved_identifiers"]["connector_id"] == (
        "ocid1.vectorstoreconnector.oc1..created"
    )
    assert payload["outputs"]["foundation_resources"]["compartment_id"] == (
        "ocid1.compartment.oc1..example"
    )
    assert payload["outputs"]["foundation_resources"]["genai_project"] == {
        "project_id": "ocid1.generativeaiproject.oc1..example",
        "name": "agent-factory-project",
    }
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
    assert payload["outputs"]["hosted_application_id"] == (
        "ocid1.generativeaihostedapplication.oc1..example"
    )
    assert payload["outputs"]["hosted_deployment_id"] == (
        "ocid1.generativeaihosteddeployment.oc1..example"
    )
    assert payload["outputs"]["hosted_application_invoke_url"] == (
        "https://inference.generativeai.eu-frankfurt-1.oci.oraclecloud.com/"
        "20251112/hostedApplications/"
        "ocid1.generativeaihostedapplication.oc1..example/actions/invoke"
    )
    assert payload["outputs"]["hosted_application_health_url"] == (
        "https://inference.generativeai.eu-frankfurt-1.oci.oraclecloud.com/"
        "20251112/hostedApplications/"
        "ocid1.generativeaihostedapplication.oc1..example/actions/invoke/health"
    )
    assert payload["outputs"]["hosted_application_responses_url"] == (
        "https://inference.generativeai.eu-frankfurt-1.oci.oraclecloud.com/"
        "20251112/hostedApplications/"
        "ocid1.generativeaihostedapplication.oc1..example/actions/invoke/responses"
    )


def test_agent_factory_builds_hosted_application_invoke_urls() -> None:
    """Test Hosted Application invoke URLs are derived from region and OCID."""

    urls = _build_hosted_application_urls(
        region="us-chicago-1",
        hosted_application_id="ocid1.generativeaihostedapplication.oc1..sample",
    )

    assert urls == {
        "hosted_application_invoke_url": (
            "https://inference.generativeai.us-chicago-1.oci.oraclecloud.com/"
            "20251112/hostedApplications/"
            "ocid1.generativeaihostedapplication.oc1..sample/actions/invoke"
        ),
        "hosted_application_health_url": (
            "https://inference.generativeai.us-chicago-1.oci.oraclecloud.com/"
            "20251112/hostedApplications/"
            "ocid1.generativeaihostedapplication.oc1..sample/actions/invoke/health"
        ),
        "hosted_application_responses_url": (
            "https://inference.generativeai.us-chicago-1.oci.oraclecloud.com/"
            "20251112/hostedApplications/"
            "ocid1.generativeaihostedapplication.oc1..sample/actions/invoke/responses"
        ),
    }


def test_agent_factory_apply_fails_when_live_command_execution_fails(
    monkeypatch,
) -> None:
    """Test live deployments do not mark planned commands as completed."""

    RUNS.clear()
    client = TestClient(app)
    request_payload = _valid_payload()
    request_payload["dry_run"] = False

    def fake_provision(
        payload: dict[str, Any],
        progress_callback: Any | None = None,
    ) -> FoundationResourcesResult:
        _notify_fake_resource_progress(progress_callback)
        return FoundationResourcesResult(
            compartment_id="ocid1.compartment.oc1..example",
            project=ProjectResult(
                project_id="ocid1.generativeaiproject.oc1..example",
                name="agent-factory-project",
            ),
            bucket=BucketResult(
                bucket_name=payload["bucket_name"],
                namespace_name="test-namespace",
                lifecycle_state="ACTIVE",
                created=False,
            ),
            vector_store=VectorStoreResult(
                vector_store_id="ocid1.vectorstore.oc1..example",
                name=payload["vector_store_name"],
                created=False,
            ),
            connector=ConnectorResult(
                connector_id="ocid1.vectorstoreconnector.oc1..example",
                name=payload["connector_name"],
                lifecycle_state="ACTIVE",
                created=False,
            ),
        )

    def fake_execute(
        payload: dict[str, Any],
        commands_by_step_id: dict[str, list[str]],
        progress_callback: Any,
    ) -> dict[str, Any]:
        _ = payload
        assert "docker-build" in commands_by_step_id
        progress_callback("docker-build", "running", None)
        raise CommandExecutionError("docker-build", "docker build failed")

    monkeypatch.setattr(
        "agent_factory_api.app.provision_foundation_resources",
        fake_provision,
    )
    monkeypatch.setattr(
        "agent_factory_api.app.execute_live_deployment_commands",
        fake_execute,
    )

    response = client.post("/factory/deployments", json=request_payload)

    assert response.status_code == 201
    payload = _fetch_run(client, response.json()["deployment_run_id"])
    steps_by_id = {step["step_id"]: step for step in payload["steps"]}
    assert payload["status"] == "failed"
    assert payload["error"] == "docker build failed"
    assert steps_by_id["docker-build"]["status"] == "failed"
    assert steps_by_id["registry"]["status"] == "pending"
    assert payload["outputs"]["note"].startswith("Live deployment failed")


def test_agent_factory_apply_preserves_partial_outputs_after_health_failure(
    monkeypatch,
) -> None:
    """Test UI outputs keep Hosted Application details when health fails."""

    RUNS.clear()
    client = TestClient(app)
    request_payload = _valid_payload()
    request_payload["dry_run"] = False

    def fake_provision(
        payload: dict[str, Any],
        progress_callback: Any | None = None,
    ) -> FoundationResourcesResult:
        _notify_fake_resource_progress(progress_callback)
        return FoundationResourcesResult(
            compartment_id="ocid1.compartment.oc1..example",
            project=ProjectResult(
                project_id="ocid1.generativeaiproject.oc1..example",
                name=payload["genai_project"],
            ),
            bucket=BucketResult(
                bucket_name=payload["bucket_name"],
                namespace_name="test-namespace",
                lifecycle_state="ACTIVE",
                created=False,
            ),
            vector_store=VectorStoreResult(
                vector_store_id="vs_fra_example",
                name=payload["vector_store_name"],
                created=False,
            ),
            connector=ConnectorResult(
                connector_id="ocid1.vectorstoreconnector.oc1..example",
                name=payload["connector_name"],
                lifecycle_state="ACTIVE",
                created=False,
            ),
        )

    def fake_execute(
        payload: dict[str, Any],
        commands_by_step_id: dict[str, list[str]],
        progress_callback: Any,
    ) -> dict[str, Any]:
        _ = payload, commands_by_step_id
        progress_callback("health", "running", None)
        raise CommandExecutionError(
            "health",
            "health could not start",
            partial_outputs={
                "hosted_application_id": (
                    "ocid1.generativeaihostedapplication.oc1..example"
                ),
                "hosted_deployment_id": (
                    "ocid1.generativeaihosteddeployment.oc1..example"
                ),
                "endpoint_url": "https://agent.example.test/actions/invoke",
            },
        )

    monkeypatch.setattr(
        "agent_factory_api.app.provision_foundation_resources",
        fake_provision,
    )
    monkeypatch.setattr(
        "agent_factory_api.app.execute_live_deployment_commands",
        fake_execute,
    )

    response = client.post("/factory/deployments", json=request_payload)

    assert response.status_code == 201
    payload = _fetch_run(client, response.json()["deployment_run_id"])
    assert payload["status"] == "failed"
    assert payload["outputs"]["endpoint_url"] == (
        "https://agent.example.test/actions/invoke"
    )
    assert payload["outputs"]["hosted_application_id"] == (
        "ocid1.generativeaihostedapplication.oc1..example"
    )
    assert payload["outputs"]["hosted_deployment_id"] == (
        "ocid1.generativeaihosteddeployment.oc1..example"
    )
    assert payload["outputs"]["hosted_application_responses_url"].endswith(
        "/actions/invoke/responses"
    )


def test_live_deployment_failure_does_not_leave_running_steps(
    monkeypatch,
) -> None:
    """Test unexpected step identifiers do not leave UI-visible running steps."""

    RUNS.clear()
    client = TestClient(app)
    request_payload = _valid_payload()
    request_payload["dry_run"] = False

    def fake_provision(
        payload: dict[str, Any],
        progress_callback: Any | None = None,
    ) -> FoundationResourcesResult:
        _notify_fake_resource_progress(progress_callback)
        return FoundationResourcesResult(
            compartment_id="ocid1.compartment.oc1..example",
            project=ProjectResult(
                project_id="ocid1.generativeaiproject.oc1..example",
                name="agent-factory-project",
            ),
            bucket=BucketResult(
                bucket_name=payload["bucket_name"],
                namespace_name="test-namespace",
                lifecycle_state="ACTIVE",
                created=False,
            ),
            vector_store=VectorStoreResult(
                vector_store_id="ocid1.vectorstore.oc1..example",
                name=payload["vector_store_name"],
                created=False,
            ),
            connector=ConnectorResult(
                connector_id="ocid1.vectorstoreconnector.oc1..example",
                name=payload["connector_name"],
                lifecycle_state="ACTIVE",
                created=False,
            ),
        )

    def fake_execute(
        payload: dict[str, Any],
        commands_by_step_id: dict[str, list[str]],
        progress_callback: Any,
    ) -> dict[str, Any]:
        _ = payload, commands_by_step_id
        progress_callback("registry", "running", None)
        raise CommandExecutionError("oci", "Repository create failed")

    monkeypatch.setattr(
        "agent_factory_api.app.provision_foundation_resources",
        fake_provision,
    )
    monkeypatch.setattr(
        "agent_factory_api.app.execute_live_deployment_commands",
        fake_execute,
    )

    response = client.post("/factory/deployments", json=request_payload)

    assert response.status_code == 201
    payload = _fetch_run(client, response.json()["deployment_run_id"])
    steps_by_id = {step["step_id"]: step for step in payload["steps"]}
    assert payload["status"] == "failed"
    assert payload["error"] == "Repository create failed"
    assert steps_by_id["registry"]["status"] == "failed"
    assert steps_by_id["registry"]["error"] == "Repository create failed"
    assert all(step["status"] != "running" for step in payload["steps"])


def test_registry_step_reuses_existing_ocir_repository(monkeypatch) -> None:
    """Test OCIR repository create conflicts are treated as successful reuse."""

    progress_events: list[tuple[str, str, dict[str, Any] | None]] = []

    def fake_run_command(*args: Any, **kwargs: Any) -> Any:
        _ = args
        raise CommandExecutionError(
            str(kwargs["step_id"]),
            "ServiceError: code: NAMESPACE_CONFLICT message: Repository already exists.",
        )

    def capture_progress(
        step_id: str,
        status: str,
        outputs: dict[str, Any] | None,
    ) -> None:
        progress_events.append((step_id, status, outputs))

    monkeypatch.setattr(factory_executor, "_run_command", fake_run_command)

    result = factory_executor._run_step(  # pylint: disable=protected-access
        "registry",
        ["oci", "artifacts", "container", "repository", "create"],
        capture_progress,
        payload=_valid_payload(),
        cwd=PROJECT_ROOT,
    )

    assert result.returncode == 0
    assert progress_events[0] == ("registry", "running", None)
    assert progress_events[1][0:2] == ("registry", "succeeded")
    assert progress_events[1][2] == {
        "created": False,
        "reused": True,
        "message": "OCI Container Registry repository already exists.",
        "repository": "oci-rag-agent-blueprint-agent",
    }


def test_foundation_resource_provisioning_waits_before_connector(monkeypatch) -> None:
    """Test connector creation starts only after bucket and Vector Store are ready."""

    events: list[str] = []
    object_storage_client = SequencedObjectStorageClient(events)
    control_plane_client = SequencedControlPlaneClient(events)
    connector_client = SequencedConnectorClient(events)

    monkeypatch.setattr(
        factory_resources,
        "resolve_compartment_id",
        lambda *, compartment, region: "ocid1.compartment.oc1..example",
    )
    monkeypatch.setattr(
        factory_resources,
        "create_object_storage_client",
        lambda *, region: object_storage_client,
    )
    monkeypatch.setattr(
        factory_resources,
        "create_control_plane_client",
        lambda *, region, compartment_id: control_plane_client,
    )
    monkeypatch.setattr(
        factory_resources,
        "create_oci_genai_client",
        lambda *, region: connector_client,
    )

    request_payload = _valid_payload()
    request_payload["genai_project"] = "agent-factory-project"

    result = provision_foundation_resources(request_payload)

    assert result.connector is not None
    assert events == [
        "list_projects",
        "get_namespace",
        "get_bucket_missing",
        "create_bucket",
        "wait_bucket",
        "list_vector_stores",
        "create_vector_store",
        "wait_vector_store",
        "list_connector",
        "create_connector",
    ]


def test_dry_run_preflight_resolves_read_only_resources(monkeypatch) -> None:
    """Test dry-run preflight resolves names and namespace without writes."""

    events: list[str] = []
    object_storage_client = SequencedObjectStorageClient(events)
    control_plane_client = SequencedControlPlaneClient(events)
    connector_client = SequencedConnectorClient(events)

    monkeypatch.setattr(
        factory_resources,
        "resolve_compartment_id",
        lambda *, compartment, region: "ocid1.compartment.oc1..example",
    )
    monkeypatch.setattr(
        factory_resources,
        "create_object_storage_client",
        lambda *, region: object_storage_client,
    )
    monkeypatch.setattr(
        factory_resources,
        "create_control_plane_client",
        lambda *, region, compartment_id: control_plane_client,
    )
    monkeypatch.setattr(
        factory_resources,
        "create_oci_genai_client",
        lambda *, region: connector_client,
    )

    request_payload = _valid_payload()
    request_payload["genai_project"] = "agent-factory-project"

    result = preflight_foundation_resources(request_payload)

    assert result.compartment_id == "ocid1.compartment.oc1..example"
    assert result.project.project_id == "ocid1.generativeaiproject.oc1..example"
    assert result.bucket.namespace_name == "test-namespace"
    assert result.vector_store.vector_store_id == (
        "<created-or-resolved-vector-store-ocid>"
    )
    assert result.connector is not None
    assert result.connector.connector_id == (
        "<created-or-resolved-data-sync-connector-ocid>"
    )
    assert events == [
        "list_projects",
        "get_namespace",
        "get_bucket_missing",
        "list_vector_stores",
        "list_connector",
    ]


def test_agent_factory_apply_uses_resolved_compartment_id(monkeypatch) -> None:
    """Test non-dry-run planning uses the live resolved compartment OCID."""

    RUNS.clear()
    client = TestClient(app)
    request_payload = _valid_payload()
    request_payload["dry_run"] = False
    request_payload["compartment"] = "lsaetta"
    _install_fake_live_executor(monkeypatch)

    def fake_provision(
        payload: dict[str, Any],
        progress_callback: Any | None = None,
    ) -> FoundationResourcesResult:
        assert payload["compartment"] == "lsaetta"
        _notify_fake_resource_progress(
            progress_callback,
            compartment_id="ocid1.compartment.oc1..resolved",
        )
        return FoundationResourcesResult(
            compartment_id="ocid1.compartment.oc1..resolved",
            project=ProjectResult(
                project_id="ocid1.generativeaiproject.oc1..resolved",
                name="agent-factory-project",
            ),
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
    assert payload["status"] == "running"
    payload = _fetch_run(client, payload["deployment_run_id"])
    assert payload["status"] == "succeeded"
    assert payload["outputs"]["resolved_identifiers"]["compartment_id"] == (
        "ocid1.compartment.oc1..resolved"
    )
    assert payload["outputs"]["runtime_environment"]["OCI_COMPARTMENT_ID"] == (
        "ocid1.compartment.oc1..resolved"
    )
    assert payload["outputs"]["runtime_environment"]["OCI_PROJECT_ID"] == (
        "ocid1.generativeaiproject.oc1..resolved"
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


def test_connector_manager_ignores_deleted_connector_when_creating() -> None:
    """Test create mode ignores deleted connectors with the requested name."""

    client = FakeConnectorClient(
        connectors=[
            {
                "id": "ocid1.vectorstoreconnector.oc1..deleted",
                "display_name": "agent-factory-connector",
                "lifecycle_state": "DELETED",
            }
        ]
    )
    manager = VectorStoreConnectorManager(client)

    result = manager.create_reuse_or_skip(
        compartment_id="ocid1.compartment.oc1..example",
        connector_name="agent-factory-connector",
        mode="create",
        vector_store_id="ocid1.vectorstore.oc1..created",
        namespace_name="test-namespace",
        bucket_name="agent-factory-docs",
    )

    assert result is not None
    assert result.created is True
    assert result.lifecycle_state == "ACTIVE"
    assert client.created_details is not None


def test_connector_manager_rejects_deleted_connector_when_reusing() -> None:
    """Test reuse mode rejects deleted connectors with the requested name."""

    client = FakeConnectorClient(
        connectors=[
            {
                "id": "ocid1.vectorstoreconnector.oc1..deleted",
                "display_name": "agent-factory-connector",
                "lifecycle_state": "DELETED",
            }
        ]
    )
    manager = VectorStoreConnectorManager(client)

    with pytest.raises(ResourceProvisioningError, match="DELETED"):
        manager.create_reuse_or_skip(
            compartment_id="ocid1.compartment.oc1..example",
            connector_name="agent-factory-connector",
            mode="reuse",
            vector_store_id="ocid1.vectorstore.oc1..created",
            namespace_name="test-namespace",
            bucket_name="agent-factory-docs",
        )


def test_connector_manager_requires_post_create_verification(monkeypatch) -> None:
    """Test connector create fails when the connector cannot be verified."""

    monkeypatch.setenv("AGENT_FACTORY_RESOURCE_WAIT_INTERVAL_SECONDS", "0.001")
    monkeypatch.setenv("AGENT_FACTORY_RESOURCE_WAIT_TIMEOUT_SECONDS", "0.01")
    client = UnverifiableConnectorClient()
    manager = VectorStoreConnectorManager(client)

    with pytest.raises(ResourceProvisioningError, match="was not verified"):
        manager.create_reuse_or_skip(
            compartment_id="ocid1.compartment.oc1..example",
            connector_name="agent-factory-connector",
            mode="create",
            vector_store_id="ocid1.vectorstore.oc1..created",
            namespace_name="test-namespace",
            bucket_name="agent-factory-docs",
        )


def test_deployment_readiness_waits_past_creating_state(monkeypatch) -> None:
    """Test Hosted Deployment readiness does not accept CREATING as ready."""

    states = iter(["CREATING", "ACTIVE"])
    seen_events: list[tuple[str, str, dict[str, Any] | None]] = []

    def fake_run_json_step(*args: Any, **kwargs: Any) -> dict[str, Any]:
        _ = args, kwargs
        return {"data": {"lifecycle-state": next(states)}}

    monkeypatch.setattr(factory_executor, "_run_json_step", fake_run_json_step)
    monkeypatch.setattr(factory_executor.time, "sleep", lambda _: None)

    output = (
        factory_executor._wait_for_deployment_ready(  # pylint: disable=protected-access
            command=["oci", "generative-ai", "hosted-deployment", "get"],
            progress_callback=lambda step_id, status, outputs: seen_events.append(
                (step_id, status, outputs)
            ),
            cwd=PROJECT_ROOT,
            secrets=[],
        )
    )

    assert output == {"data": {"lifecycle-state": "ACTIVE"}}
    assert (
        "deployment-readiness",
        "running",
        {"lifecycle_state": "CREATING", "waiting": True},
    ) in seen_events


def test_deployment_readiness_fails_terminal_state(monkeypatch) -> None:
    """Test Hosted Deployment readiness fails on terminal failed states."""

    def fake_run_json_step(*args: Any, **kwargs: Any) -> dict[str, Any]:
        _ = args, kwargs
        return {"data": {"lifecycle-state": "FAILED"}}

    monkeypatch.setattr(factory_executor, "_run_json_step", fake_run_json_step)

    with pytest.raises(CommandExecutionError, match="FAILED"):
        factory_executor._wait_for_deployment_ready(  # pylint: disable=protected-access
            command=["oci", "generative-ai", "hosted-deployment", "get"],
            progress_callback=lambda *_: None,
            cwd=PROJECT_ROOT,
            secrets=[],
        )


def test_executor_replaces_embedded_placeholders() -> None:
    """Test placeholder replacement also works inside command arguments."""

    command = [
        "python",
        "-c",
        "print('ok')",
        "<deployed-health-endpoint>/health",
    ]

    assert _replace_placeholders(
        command,
        {"<deployed-health-endpoint>": "https://agent.example.test/actions/invoke"},
    ) == [
        "python",
        "-c",
        "print('ok')",
        "https://agent.example.test/actions/invoke/health",
    ]


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


def test_resolve_genai_project_returns_unique_match() -> None:
    """Test GenAI project name resolution returns the matching OCID."""

    client = FakeConnectorClient(
        projects=[
            {
                "id": "ocid1.generativeaiproject.oc1..resolved",
                "display_name": "agent-factory-project",
            }
        ]
    )

    result = resolve_genai_project(
        client=client,
        compartment_id="ocid1.compartment.oc1..example",
        project="agent-factory-project",
    )

    assert result == ProjectResult(
        project_id="ocid1.generativeaiproject.oc1..resolved",
        name="agent-factory-project",
    )
    assert client.project_list_kwargs == {"display_name": "agent-factory-project"}


def test_resolve_genai_project_supports_legacy_list_projects_alias() -> None:
    """Test project resolution still supports clients exposing the old alias."""

    client = LegacyProjectListClient()

    result = resolve_genai_project(
        client=client,
        compartment_id="ocid1.compartment.oc1..example",
        project="agent-factory-project",
    )

    assert result.project_id == "ocid1.generativeaiproject.oc1..legacy"


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
        "genai_project": "ocid1.generativeaiproject.oc1..example",
        "model_id": "openai.gpt-5.4",
        "openai_api_key": "test-api-key",
        "ocir_username": "test-ocir-user",
        "ocir_password": "test-ocir-password",
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
        self._created_bucket: dict[str, str] | None = None

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
            FakeNotFoundError: When the fake bucket has not been created yet.
        """

        if self._created_bucket is not None:
            return FakeResponse(self._created_bucket)
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
        self._created_bucket = {
            "name": "agent-factory-docs",
            "namespace": namespace_name,
            "lifecycle_state": "ACTIVE",
        }
        return FakeResponse(self._created_bucket)


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

    def __init__(
        self,
        projects: list[dict[str, str]] | None = None,
        connectors: list[dict[str, str]] | None = None,
    ) -> None:
        """Initialize the fake client."""

        self.created_details: Any | None = None
        self._created_connector: dict[str, str] | None = None
        self._connectors = connectors or []
        self._projects = projects or [
            {
                "id": "ocid1.generativeaiproject.oc1..example",
                "display_name": "agent-factory-project",
            }
        ]
        self.project_list_kwargs: dict[str, Any] | None = None

    def list_generative_ai_projects(
        self, compartment_id: str, **kwargs: Any
    ) -> FakeResponse:
        """Return fake GenAI projects.

        Args:
            compartment_id: Compartment OCID.
            kwargs: List filter arguments.

        Returns:
            FakeResponse: Project list response.
        """

        assert compartment_id == "ocid1.compartment.oc1..example"
        self.project_list_kwargs = kwargs
        return FakeResponse(FakeListData(self._projects))

    def list_vector_store_connectors(self, compartment_id: str) -> FakeResponse:
        """Return no existing connectors.

        Args:
            compartment_id: Compartment OCID.

        Returns:
            FakeResponse: Empty connector list response.
        """

        assert compartment_id == "ocid1.compartment.oc1..example"
        return FakeResponse(FakeListData(self._connectors))

    def create_vector_store_connector(self, create_details: Any) -> FakeResponse:
        """Create a fake connector.

        Args:
            create_details: OCI SDK create connector details.

        Returns:
            FakeResponse: Connector response.
        """

        self.created_details = create_details
        self._created_connector = {
            "id": "ocid1.vectorstoreconnector.oc1..created",
            "display_name": "agent-factory-connector",
            "lifecycle_state": "ACTIVE",
        }
        return FakeResponse(self._created_connector)

    def get_vector_store_connector(self, connector_id: str) -> FakeResponse:
        """Return the created connector by OCID.

        Args:
            connector_id: Connector OCID.

        Returns:
            FakeResponse: Connector response.

        Raises:
            FakeNotFoundError: If no connector has been created.
        """

        if self._created_connector is None:
            raise FakeNotFoundError(connector_id)
        assert connector_id == self._created_connector["id"]
        return FakeResponse(self._created_connector)


class UnverifiableConnectorClient:
    """Fake connector client whose create response is never verifiable."""

    def list_vector_store_connectors(self, compartment_id: str) -> FakeResponse:
        """Return no connectors.

        Args:
            compartment_id: Compartment OCID.

        Returns:
            FakeResponse: Empty connector list response.
        """

        assert compartment_id == "ocid1.compartment.oc1..example"
        return FakeResponse(FakeListData([]))

    def create_vector_store_connector(self, create_details: Any) -> FakeResponse:
        """Return a create response for an unverifiable connector.

        Args:
            create_details: OCI SDK create connector details.

        Returns:
            FakeResponse: Connector create response.
        """

        _ = create_details
        return FakeResponse(
            {
                "id": "ocid1.vectorstoreconnector.oc1..missing",
                "display_name": "agent-factory-connector",
                "lifecycle_state": "CREATING",
            }
        )

    def get_vector_store_connector(self, connector_id: str) -> FakeResponse:
        """Always report the connector as missing.

        Args:
            connector_id: Connector OCID.

        Raises:
            FakeNotFoundError: Always raised.
        """

        raise FakeNotFoundError(connector_id)


class SequencedObjectStorageClient:
    """Fake Object Storage client that records dependency order."""

    def __init__(self, events: list[str]) -> None:
        """Initialize the fake client.

        Args:
            events: Shared event list.
        """

        self._events = events
        self._created = False

    def get_namespace(self) -> FakeResponse:
        """Return a fake namespace response.

        Returns:
            FakeResponse: Namespace response.
        """

        self._events.append("get_namespace")
        return FakeResponse("test-namespace")

    def get_bucket(self, namespace_name: str, bucket_name: str) -> FakeResponse:
        """Return the bucket only after create has completed.

        Args:
            namespace_name: Object Storage namespace.
            bucket_name: Bucket name.

        Returns:
            FakeResponse: Bucket response.

        Raises:
            FakeNotFoundError: If the bucket has not been created yet.
        """

        if not self._created:
            self._events.append("get_bucket_missing")
            raise FakeNotFoundError(f"{namespace_name}/{bucket_name}")
        self._events.append("wait_bucket")
        return FakeResponse(
            {
                "name": bucket_name,
                "namespace": namespace_name,
                "lifecycle_state": "ACTIVE",
            }
        )

    def create_bucket(
        self, namespace_name: str, create_bucket_details: Any
    ) -> FakeResponse:
        """Create the fake bucket.

        Args:
            namespace_name: Object Storage namespace.
            create_bucket_details: OCI SDK create details.

        Returns:
            FakeResponse: Bucket response.
        """

        self._events.append("create_bucket")
        self._created = True
        return FakeResponse(
            {
                "name": _resource_name_from_details(create_bucket_details),
                "namespace": namespace_name,
                "lifecycle_state": "CREATING",
            }
        )


class SequencedVectorStores:
    """Fake Vector Store API that records dependency order."""

    def __init__(self, events: list[str]) -> None:
        """Initialize the fake API.

        Args:
            events: Shared event list.
        """

        self._events = events

    def list(self) -> FakeResponse:
        """Return no Vector Stores.

        Returns:
            FakeResponse: Empty Vector Store list response.
        """

        self._events.append("list_vector_stores")
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
            dict[str, str]: Fake Vector Store response.
        """

        _ = description, expires_after, metadata
        self._events.append("create_vector_store")
        return {
            "id": "ocid1.vectorstore.oc1..created",
            "name": name,
            "status": "creating",
        }

    def retrieve(self, vector_store_id: str) -> dict[str, str]:
        """Return a ready fake Vector Store.

        Args:
            vector_store_id: Vector Store OCID.

        Returns:
            dict[str, str]: Ready Vector Store response.
        """

        self._events.append("wait_vector_store")
        return {
            "id": vector_store_id,
            "name": "agent-factory-vector-store",
            "status": "completed",
        }


class SequencedControlPlaneClient:
    """Fake control plane client that records dependency order."""

    def __init__(self, events: list[str]) -> None:
        """Initialize the fake client.

        Args:
            events: Shared event list.
        """

        self.vector_stores = SequencedVectorStores(events)


class SequencedConnectorClient:
    """Fake connector client that requires dependency readiness first."""

    def __init__(self, events: list[str]) -> None:
        """Initialize the fake client.

        Args:
            events: Shared event list.
        """

        self._events = events
        self._created_connector: dict[str, str] | None = None

    def list_generative_ai_projects(
        self, compartment_id: str, **kwargs: Any
    ) -> FakeResponse:
        """Return a matching GenAI project and record resolution order.

        Args:
            compartment_id: Compartment OCID.
            kwargs: List filter arguments.

        Returns:
            FakeResponse: Project list response.
        """

        assert compartment_id == "ocid1.compartment.oc1..example"
        assert kwargs == {"display_name": "agent-factory-project"}
        self._events.append("list_projects")
        return FakeResponse(
            FakeListData(
                [
                    {
                        "id": "ocid1.generativeaiproject.oc1..example",
                        "display_name": "agent-factory-project",
                    }
                ]
            )
        )

    def list_vector_store_connectors(self, compartment_id: str) -> FakeResponse:
        """Return no existing connectors.

        Args:
            compartment_id: Compartment OCID.

        Returns:
            FakeResponse: Empty connector list response.
        """

        assert compartment_id == "ocid1.compartment.oc1..example"
        self._events.append("list_connector")
        return FakeResponse(FakeListData([]))

    def create_vector_store_connector(self, create_details: Any) -> FakeResponse:
        """Create a connector only after dependencies are ready.

        Args:
            create_details: OCI SDK create connector details.

        Returns:
            FakeResponse: Connector response.
        """

        assert "wait_bucket" in self._events
        assert "wait_vector_store" in self._events
        self._events.append("create_connector")
        self._created_connector = {
            "id": "ocid1.vectorstoreconnector.oc1..created",
            "display_name": _resource_display_name_from_details(create_details),
            "lifecycle_state": "ACTIVE",
        }
        return FakeResponse(self._created_connector)

    def get_vector_store_connector(self, connector_id: str) -> FakeResponse:
        """Return the created connector by OCID.

        Args:
            connector_id: Connector OCID.

        Returns:
            FakeResponse: Connector response.

        Raises:
            FakeNotFoundError: If no connector has been created.
        """

        if self._created_connector is None:
            raise FakeNotFoundError(connector_id)
        assert connector_id == self._created_connector["id"]
        return FakeResponse(self._created_connector)


class LegacyProjectListClient:
    """Fake GenAI client exposing the legacy project list alias."""

    def list_projects(self, compartment_id: str, **kwargs: Any) -> FakeResponse:
        """Return fake projects through the legacy alias.

        Args:
            compartment_id: Compartment OCID.
            kwargs: List filter arguments.

        Returns:
            FakeResponse: Project list response.
        """

        assert compartment_id == "ocid1.compartment.oc1..example"
        assert kwargs == {"display_name": "agent-factory-project"}
        return FakeResponse(
            FakeListData(
                [
                    {
                        "id": "ocid1.generativeaiproject.oc1..legacy",
                        "display_name": "agent-factory-project",
                    }
                ]
            )
        )


def _resource_name_from_details(create_details: Any) -> str:
    """Return a resource name from fake OCI details.

    Args:
        create_details: OCI details model or dictionary.

    Returns:
        str: Resource name.
    """

    if isinstance(create_details, dict):
        return str(create_details["name"])
    return str(create_details.name)


def _resource_display_name_from_details(create_details: Any) -> str:
    """Return a display name from fake OCI details.

    Args:
        create_details: OCI details model or dictionary.

    Returns:
        str: Resource display name.
    """

    if isinstance(create_details, dict):
        return str(create_details["display_name"])
    return str(create_details.display_name)


def _fetch_run(client: TestClient, deployment_run_id: str) -> dict[str, Any]:
    """Fetch a saved Agent Factory run.

    Args:
        client: FastAPI test client.
        deployment_run_id: Deployment run identifier.

    Returns:
        dict[str, Any]: Run payload.
    """

    response = client.get(f"/factory/deployments/{deployment_run_id}")
    assert response.status_code == 200
    return response.json()


def _install_fake_preflight(
    monkeypatch,
    *,
    compartment_id: str = "ocid1.compartment.oc1..example",
    project_id: str = "ocid1.generativeaiproject.oc1..example",
    namespace_name: str = "test-namespace",
) -> None:
    """Install a fake read-only dry-run preflight.

    Args:
        monkeypatch: Pytest monkeypatch fixture.
        compartment_id: Compartment OCID reported by the fake resolver.
        project_id: GenAI project OCID reported by the fake resolver.
        namespace_name: Object Storage namespace reported by the fake resolver.
    """

    def fake_preflight(
        payload: dict[str, Any],
        progress_callback: Any | None = None,
    ) -> FoundationResourcesResult:
        _ = progress_callback
        return FoundationResourcesResult(
            compartment_id=compartment_id,
            project=ProjectResult(
                project_id=project_id,
                name="agent-factory-project",
            ),
            bucket=BucketResult(
                bucket_name=payload["bucket_name"],
                namespace_name=namespace_name,
                lifecycle_state=None,
                created=False,
            ),
            vector_store=VectorStoreResult(
                vector_store_id="<created-or-resolved-vector-store-ocid>",
                name=payload["vector_store_name"],
                created=False,
            ),
            connector=ConnectorResult(
                connector_id="<created-or-resolved-data-sync-connector-ocid>",
                name=payload["connector_name"],
                lifecycle_state=None,
                created=False,
            ),
        )

    monkeypatch.setattr(
        "agent_factory_api.app.preflight_foundation_resources",
        fake_preflight,
    )

    def fake_validate_ocir_login(**kwargs: Any) -> dict[str, str]:
        return {
            "ocir_registry": str(kwargs["registry"]),
            "ocir_username": str(kwargs["username"]),
        }

    monkeypatch.setattr(
        "agent_factory_api.app.validate_ocir_login",
        fake_validate_ocir_login,
    )


def _install_fake_live_executor(monkeypatch) -> None:
    """Install a fake live executor that simulates final deployment outputs.

    Args:
        monkeypatch: Pytest monkeypatch fixture.
    """

    def fake_execute(
        payload: dict[str, Any],
        commands_by_step_id: dict[str, list[str]],
        progress_callback: Any,
    ) -> dict[str, Any]:
        _ = payload
        for step_id in (
            "docker-build",
            "registry",
            "registry-login",
            "docker-push",
            "hosted-application",
            "hosted-deployment",
            "deployment-readiness",
            "health",
        ):
            assert step_id in commands_by_step_id
            progress_callback(step_id, "running", None)
            progress_callback(step_id, "succeeded", {"mocked": True})
        progress_callback("runtime-environment", "running", None)
        progress_callback("runtime-environment", "succeeded", {"mocked": True})
        return {
            "hosted_application_id": "ocid1.generativeaihostedapplication.oc1..example",
            "hosted_deployment_id": "ocid1.generativeaihosteddeployment.oc1..example",
            "endpoint_url": "https://agent.example.test",
        }

    monkeypatch.setattr(
        "agent_factory_api.app.execute_live_deployment_commands",
        fake_execute,
    )


def _notify_fake_resource_progress(
    progress_callback: Any | None,
    *,
    compartment_id: str = "ocid1.compartment.oc1..example",
) -> None:
    """Emit fake live provisioning progress events.

    Args:
        progress_callback: Optional app callback.
        compartment_id: Compartment OCID reported by the fake resolver.
    """

    if progress_callback is None:
        return
    progress_callback(
        "resolve-compartment",
        "succeeded",
        {"compartment_id": compartment_id},
    )
    progress_callback(
        "resolve-genai-project",
        "succeeded",
        {
            "genai_project_id": "ocid1.generativeaiproject.oc1..example",
            "name": "agent-factory-project",
        },
    )
    progress_callback(
        "bucket",
        "succeeded",
        {
            "bucket_name": "agent-factory-docs",
            "namespace_name": "test-namespace",
            "created": True,
        },
    )
    progress_callback(
        "vector-store",
        "succeeded",
        {
            "vector_store_id": "ocid1.vectorstore.oc1..created",
            "name": "agent-factory-vector-store",
            "created": True,
        },
    )
    progress_callback(
        "data-sync-connector",
        "succeeded",
        {
            "connector_id": "ocid1.vectorstoreconnector.oc1..created",
            "name": "agent-factory-connector",
            "created": True,
            "skipped": False,
        },
    )
