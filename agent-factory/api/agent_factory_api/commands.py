"""
Author: L. Saetta
Date last modified: 2026-06-17
License: MIT
Description: Command planning helpers for Agent Factory deployment runs.
"""

from __future__ import annotations

# pylint: disable=duplicate-code

from typing import Any

DEFAULT_WAIT_STATE = "SUCCEEDED"
GENERATED_ARTIFACT_DIR = "agent-factory/generated"
COMPARTMENT_OCID_PREFIX = "ocid1.compartment."
GENAI_PROJECT_OCID_PREFIX = "ocid1.generativeaiproject."
REGION_KEYS = {
    "eu-frankfurt-1": "fra",
    "us-chicago-1": "ord",
}

AGENT_RUNTIME_ENVIRONMENT_VARIABLES = (
    "OCI_REGION",
    "OCI_COMPARTMENT_ID",
    "OCI_PROJECT_ID",
    "OCI_MODEL_ID",
    "OCI_VECTOR_STORE_ID",
    "OPENAI_API_KEY",
    "FILE_SEARCH_MAX_NUM_RESULTS",
    "RESPONSES_TIMEOUT_SECONDS",
    "STREAM_FINALIZATION_MODE",
)


def build_deployment_plan(payload: dict[str, Any], dry_run: bool) -> dict[str, Any]:
    """Build commands and JSON artifacts for an Agent Factory run.

    Args:
        payload: Normalized deployment payload.
        dry_run: Whether to build non-mutating check commands.

    Returns:
        dict[str, Any]: Command plan, image reference, runtime environment, and
        JSON artifacts.
    """

    resolved_identifiers = build_resolved_identifiers(payload)
    runtime_environment = build_agent_runtime_environment(payload, resolved_identifiers)
    redacted_environment = redact_runtime_environment(runtime_environment)
    artifacts = build_hosted_application_artifacts(
        payload,
        redacted_environment,
        resolved_identifiers,
    )
    image_reference = build_image_reference(payload)
    commands = (
        _build_dry_run_commands(
            payload, artifacts, image_reference, resolved_identifiers
        )
        if dry_run
        else _build_apply_commands(
            payload,
            artifacts,
            image_reference,
            resolved_identifiers,
        )
    )
    return {
        "commands": commands,
        "image_reference": image_reference,
        "resolved_identifiers": resolved_identifiers,
        "runtime_environment": runtime_environment,
        "redacted_runtime_environment": redacted_environment,
        "artifacts": artifacts,
    }


def build_dry_run_commands(payload: dict[str, Any]) -> list[list[str]]:
    """Build non-mutating validation commands for an Agent Factory dry run.

    Args:
        payload: Normalized deployment payload.

    Returns:
        list[list[str]]: Structured command arguments.
    """

    image_reference = build_image_reference(payload)
    resolved_identifiers = build_resolved_identifiers(payload)
    artifacts = build_hosted_application_artifacts(
        payload,
        redact_runtime_environment(
            build_agent_runtime_environment(payload, resolved_identifiers)
        ),
        resolved_identifiers,
    )

    return _build_dry_run_commands(
        payload,
        artifacts,
        image_reference,
        resolved_identifiers,
    )


def _build_dry_run_commands(
    payload: dict[str, Any],
    artifacts: dict[str, Any],
    image_reference: str,
    resolved_identifiers: dict[str, str],
) -> list[list[str]]:
    """Build non-mutating validation commands from prepared artifacts.

    Args:
        payload: Normalized deployment payload.
        artifacts: Generated Hosted Application JSON artifacts.
        image_reference: Final OCIR image reference.
        resolved_identifiers: Resource identifiers resolved from names or OCIDs.

    Returns:
        list[list[str]]: Structured command arguments.
    """

    compartment_id = resolved_identifiers["compartment_id"]
    namespace_name = resolved_identifiers["object_storage_namespace"]
    ocir_registry = build_ocir_registry(payload)
    connector_command = [
        "python",
        "-m",
        "agent_factory_api.control_plane_check",
        "data-sync-connector",
        "--region",
        payload["region"],
        "--mode",
        payload["connector_mode"],
        "--name-or-id",
        payload.get("connector_name") or "<skipped>",
    ]

    return [
        _build_compartment_resolution_command(payload),
        _build_genai_project_resolution_command(payload, compartment_id),
        [
            "oci",
            "--region",
            payload["region"],
            "--output",
            "json",
            "os",
            "bucket",
            "get",
            "--namespace-name",
            namespace_name,
            "--bucket-name",
            payload["bucket_name"],
        ],
        [
            "python",
            "-m",
            "agent_factory_api.control_plane_check",
            "vector-store",
            "--region",
            payload["region"],
            "--name-or-id",
            payload["vector_store_name"],
        ],
        connector_command,
        [
            "docker",
            "build",
            "--platform",
            "linux/amd64",
            "-f",
            "Dockerfile",
            "-t",
            image_reference,
            ".",
        ],
        [
            "oci",
            "--region",
            payload["region"],
            "--output",
            "json",
            "artifacts",
            "container",
            "repository",
            "list",
            "--compartment-id",
            compartment_id,
            "--display-name",
            payload["container_repository_name"],
            "--all",
        ],
        _build_docker_login_command(payload, ocir_registry),
        [
            "docker",
            "manifest",
            "inspect",
            image_reference,
        ],
        [
            "oci",
            "--region",
            payload["region"],
            "--output",
            "json",
            "generative-ai",
            "hosted-application-collection",
            "list-hosted-applications",
            "--compartment-id",
            compartment_id,
            "--all",
        ],
        [
            "oci",
            "--region",
            payload["region"],
            "--output",
            "json",
            "generative-ai",
            "hosted-deployment",
            "create-hosted-deployment-single-docker-artifact",
            "--hosted-application-id",
            "<hosted-application-ocid-from-create-response>",
            "--active-artifact-container-uri",
            artifacts["create-hosted-deployment.json"]["containerUri"],
            "--active-artifact-tag",
            artifacts["create-hosted-deployment.json"]["artifactTag"],
            "--display-name",
            artifacts["create-hosted-deployment.json"]["displayName"],
            "--compartment-id",
            compartment_id,
            "--wait-for-state",
            DEFAULT_WAIT_STATE,
        ],
        [
            "oci",
            "--region",
            payload["region"],
            "--output",
            "json",
            "generative-ai",
            "hosted-deployment",
            "get",
            "--hosted-deployment-id",
            "<hosted-deployment-ocid>",
        ],
        _build_health_check_command(),
    ]


def build_apply_commands(payload: dict[str, Any]) -> list[list[str]]:
    """Build mutating command plan for a real deployment run.

    Args:
        payload: Normalized deployment payload.

    Returns:
        list[list[str]]: Structured command arguments.
    """

    image_reference = build_image_reference(payload)
    resolved_identifiers = build_resolved_identifiers(payload)
    artifacts = build_hosted_application_artifacts(
        payload,
        redact_runtime_environment(
            build_agent_runtime_environment(payload, resolved_identifiers)
        ),
        resolved_identifiers,
    )

    return _build_apply_commands(
        payload,
        artifacts,
        image_reference,
        resolved_identifiers,
    )


def _build_apply_commands(
    payload: dict[str, Any],
    artifacts: dict[str, Any],
    image_reference: str,
    resolved_identifiers: dict[str, str],
) -> list[list[str]]:
    """Build mutating command plan from prepared artifacts.

    Args:
        payload: Normalized deployment payload.
        artifacts: Generated Hosted Application JSON artifacts.
        image_reference: Final OCIR image reference.
        resolved_identifiers: Resource identifiers resolved from names or OCIDs.

    Returns:
        list[list[str]]: Structured command arguments.
    """

    compartment_id = resolved_identifiers["compartment_id"]
    ocir_registry = build_ocir_registry(payload)
    connector_command = [
        "python",
        "-m",
        "agent_factory_api.control_plane_apply",
        "data-sync-connector",
        "--region",
        payload["region"],
        "--mode",
        payload["connector_mode"],
        "--name-or-id",
        payload.get("connector_name") or "<skipped>",
    ]

    return [
        _build_compartment_resolution_command(payload),
        _build_genai_project_resolution_command(payload, compartment_id),
        [
            "oci",
            "os",
            "bucket",
            "create",
            "--compartment-id",
            compartment_id,
            "--name",
            payload["bucket_name"],
        ],
        [
            "python",
            "-m",
            "agent_factory_api.control_plane_apply",
            "vector-store",
            "--region",
            payload["region"],
            "--mode",
            payload["vector_store_mode"],
            "--name-or-id",
            payload["vector_store_name"],
        ],
        connector_command,
        [
            "docker",
            "build",
            "--platform",
            "linux/amd64",
            "-t",
            image_reference,
            "-f",
            "Dockerfile",
            ".",
        ],
        [
            "oci",
            "--region",
            payload["region"],
            "--output",
            "json",
            "artifacts",
            "container",
            "repository",
            "create",
            "--display-name",
            payload["container_repository_name"],
            "--compartment-id",
            compartment_id,
        ],
        _build_docker_login_command(payload, ocir_registry),
        [
            "docker",
            "push",
            image_reference,
        ],
        [
            "oci",
            "--region",
            payload["region"],
            "--output",
            "json",
            "generative-ai",
            "hosted-application",
            "create",
            "--display-name",
            artifacts["create-hosted-application.json"]["displayName"],
            "--compartment-id",
            compartment_id,
            "--inbound-auth-config",
            _file_uri("hosted-application-inbound-auth-config.json"),
            "--networking-config",
            _file_uri("hosted-application-networking-config.json"),
            "--environment-variables",
            _file_uri("hosted-application-environment-variables.json"),
            "--wait-for-state",
            DEFAULT_WAIT_STATE,
        ],
        [
            "oci",
            "--region",
            payload["region"],
            "--output",
            "json",
            "generative-ai",
            "hosted-deployment",
            "create-hosted-deployment-single-docker-artifact",
            "--hosted-application-id",
            "<hosted-application-ocid-from-create-response>",
            "--active-artifact-container-uri",
            artifacts["create-hosted-deployment.json"]["containerUri"],
            "--active-artifact-tag",
            artifacts["create-hosted-deployment.json"]["artifactTag"],
            "--display-name",
            artifacts["create-hosted-deployment.json"]["displayName"],
            "--compartment-id",
            compartment_id,
            "--wait-for-state",
            DEFAULT_WAIT_STATE,
        ],
        [
            "oci",
            "--region",
            payload["region"],
            "--output",
            "json",
            "generative-ai",
            "hosted-deployment",
            "get",
            "--hosted-deployment-id",
            "<hosted-deployment-ocid>",
        ],
        _build_health_check_command(),
    ]


def _build_health_check_command() -> list[str]:
    """Build a portable health check command for the hosted agent.

    Returns:
        list[str]: Python command that validates the health endpoint without
        requiring curl to be installed in the Agent Factory API container.
    """

    return [
        "python",
        "-c",
        (
            "import sys, urllib.request; "
            "urllib.request.urlopen(sys.argv[1], timeout=30).read()"
        ),
        "<deployed-health-endpoint>/health",
    ]


def build_image_reference(payload: dict[str, Any]) -> str:
    """Build the target OCI Container Registry image reference.

    Args:
        payload: Normalized deployment payload.

    Returns:
        str: Image reference placeholder suitable for display and later execution.
    """

    repository = payload["container_repository_name"].strip("/")
    tenancy_namespace = str(
        payload.get("object_storage_namespace") or "<tenancy-namespace>"
    )
    return (
        f"{build_ocir_registry(payload)}"
        f"/{tenancy_namespace}/{repository}:"
        f"{payload['container_image_tag']}"
    )


def build_ocir_registry(payload: dict[str, Any]) -> str:
    """Build the target OCIR registry hostname for a selected OCI region.

    Args:
        payload: Normalized deployment payload.

    Returns:
        str: OCIR registry hostname.

    Raises:
        ValueError: If the region does not have a configured region key.
    """

    region = str(payload["region"])
    region_key = REGION_KEYS.get(region)
    if not region_key:
        raise ValueError(f"Unsupported OCI region for OCIR registry: {region}")
    return f"{region_key}.ocir.io"


def build_hosted_application_artifacts(
    payload: dict[str, Any],
    environment: dict[str, str],
    resolved_identifiers: dict[str, str],
) -> dict[str, Any]:
    """Build OCI CLI JSON artifacts using the deployer-compatible shape.

    Args:
        payload: Normalized deployment payload.
        environment: Runtime environment variables safe for dry-run responses.
        resolved_identifiers: Resource identifiers resolved from names or OCIDs.

    Returns:
        dict[str, Any]: Artifact filenames mapped to JSON payloads.
    """

    image_reference = build_image_reference(payload)
    compartment_id = resolved_identifiers["compartment_id"]
    container_uri, tag = image_reference.rsplit(":", maxsplit=1)
    return {
        "hosted-application-inbound-auth-config.json": (
            _build_inbound_auth_config(payload)
        ),
        "hosted-application-networking-config.json": {
            "inboundNetworkingConfig": {
                "endpointMode": "PUBLIC",
            },
            "outboundNetworkingConfig": {
                "networkMode": "MANAGED",
            },
        },
        "hosted-application-environment-variables.json": [
            {"name": name, "type": "PLAINTEXT", "value": value}
            for name, value in environment.items()
        ],
        "hosted-deployment-active-artifact.json": {
            "artifactType": "SIMPLE_DOCKER_ARTIFACT",
            "containerUri": container_uri,
            "tag": tag,
        },
        "create-hosted-application.json": {
            "compartmentId": compartment_id,
            "createIfMissing": True,
            "displayName": payload["hosted_application_name"],
            "jsonFiles": {
                "inboundAuthConfig": _artifact_path(
                    "hosted-application-inbound-auth-config.json"
                ),
                "networkingConfig": _artifact_path(
                    "hosted-application-networking-config.json"
                ),
                "environmentVariables": _artifact_path(
                    "hosted-application-environment-variables.json"
                ),
            },
            "updateIfExists": False,
        },
        "create-hosted-deployment.json": {
            "activate": True,
            "activeArtifact": _artifact_path("hosted-deployment-active-artifact.json"),
            "artifactTag": tag,
            "compartmentId": compartment_id,
            "containerUri": container_uri,
            "createNewVersion": True,
            "displayName": payload["deployment_name"],
            "imageUri": image_reference,
        },
    }


def _build_inbound_auth_config(payload: dict[str, Any]) -> dict[str, Any]:
    """Build the Hosted Application inbound authentication configuration.

    Args:
        payload: Normalized deployment payload.

    Returns:
        dict[str, Any]: OCI CLI JSON payload for inbound authentication.
    """

    if not payload.get("jwt_protection_enabled"):
        return {"inboundAuthConfigType": "NO_AUTH_CONFIG"}

    return {
        "inboundAuthConfigType": "IDCS_AUTH_CONFIG",
        "idcsConfig": {
            "domainUrl": str(payload["identity_domain_url"]).rstrip("/"),
            "scope": str(payload["auth_scope"]),
            "audience": str(payload["auth_audience"]),
        },
    }


def build_agent_runtime_environment(
    payload: dict[str, Any],
    resolved_identifiers: dict[str, str] | None = None,
) -> dict[str, str]:
    """Build environment variables required by the deployed RAG agent.

    Args:
        payload: Normalized deployment payload.
        resolved_identifiers: Resource identifiers resolved from names or OCIDs.

    Returns:
        dict[str, str]: Agent runtime environment variables for Hosted
        Application deployment creation.
    """

    identifiers = resolved_identifiers or build_resolved_identifiers(payload)
    return {
        "OCI_REGION": str(payload["region"]),
        "OCI_COMPARTMENT_ID": identifiers["compartment_id"],
        "OCI_PROJECT_ID": identifiers["genai_project_id"],
        "OCI_MODEL_ID": str(payload["model_id"]),
        "OCI_VECTOR_STORE_ID": identifiers["vector_store_id"],
        "OPENAI_API_KEY": str(payload["openai_api_key"]),
        "FILE_SEARCH_MAX_NUM_RESULTS": str(payload["file_search_max_num_results"]),
        "RESPONSES_TIMEOUT_SECONDS": str(payload["responses_timeout_seconds"]),
        "STREAM_FINALIZATION_MODE": str(payload["stream_finalization_mode"]),
    }


def redact_runtime_environment(environment: dict[str, str]) -> dict[str, str]:
    """Redact secret values from runtime environment output.

    Args:
        environment: Agent runtime environment variables.

    Returns:
        dict[str, str]: Environment variables safe for API responses.
    """

    redacted = dict(environment)
    if redacted.get("OPENAI_API_KEY"):
        redacted["OPENAI_API_KEY"] = "********"
    return redacted


def build_resolved_identifiers(payload: dict[str, Any]) -> dict[str, str]:
    """Build resolved resource identifiers for command planning.

    Args:
        payload: Normalized deployment payload.

    Returns:
        dict[str, str]: Resolved or placeholder OCIDs used after lookup steps.
    """

    return {
        "compartment_id": _resolved_compartment_id(payload),
        "genai_project_id": _resolved_genai_project_id(payload),
        "object_storage_namespace": _resolved_object_storage_namespace(payload),
        "vector_store_id": _resolved_vector_store_id(payload),
        "connector_id": _resolved_connector_id(payload),
    }


def _resolved_compartment_id(payload: dict[str, Any]) -> str:
    """Return the compartment OCID or the placeholder produced by resolution.

    Args:
        payload: Normalized deployment payload.

    Returns:
        str: Compartment OCID value for downstream OCI commands.
    """

    compartment = str(payload["compartment"])
    if compartment.startswith(COMPARTMENT_OCID_PREFIX):
        return compartment
    return "<resolved-compartment-ocid>"


def _resolved_vector_store_id(payload: dict[str, Any]) -> str:
    """Return the Vector Store identifier or the placeholder produced by resolution.

    Args:
        payload: Normalized deployment payload.

    Returns:
        str: Vector Store identifier for the deployed agent environment.
    """

    vector_store_name = str(payload["vector_store_name"])
    if vector_store_name.startswith(("ocid1.", "vs_")):
        return vector_store_name
    return "<created-or-resolved-vector-store-ocid>"


def _resolved_genai_project_id(payload: dict[str, Any]) -> str:
    """Return the GenAI project OCID or the placeholder produced by resolution.

    Args:
        payload: Normalized deployment payload.

    Returns:
        str: GenAI project OCID value for the deployed agent environment.
    """

    project = str(payload["genai_project"])
    if project.startswith(GENAI_PROJECT_OCID_PREFIX):
        return project
    return "<resolved-genai-project-ocid>"


def _resolved_object_storage_namespace(payload: dict[str, Any]) -> str:
    """Return the Object Storage namespace or the placeholder from resolution.

    Args:
        payload: Normalized deployment payload.

    Returns:
        str: Object Storage namespace for bucket commands and connector setup.
    """

    return str(payload.get("object_storage_namespace") or "<resolved-namespace>")


def _resolved_connector_id(payload: dict[str, Any]) -> str:
    """Return the connector OCID or the placeholder produced by resolution.

    Args:
        payload: Normalized deployment payload.

    Returns:
        str: Connector OCID value or a skip marker.
    """

    if payload["connector_mode"] == "skip":
        return "<skipped>"
    connector_name = str(payload.get("connector_name") or "")
    if connector_name.startswith("ocid1."):
        return connector_name
    return "<created-or-resolved-data-sync-connector-ocid>"


def _build_compartment_resolution_command(payload: dict[str, Any]) -> list[str]:
    """Build the command that resolves a compartment name or validates an OCID.

    Args:
        payload: Normalized deployment payload.

    Returns:
        list[str]: OCI CLI command arguments.
    """

    compartment = str(payload["compartment"])
    command = [
        "oci",
        "--region",
        payload["region"],
        "--output",
        "json",
        "iam",
        "compartment",
    ]
    if compartment.startswith(COMPARTMENT_OCID_PREFIX):
        return [
            *command,
            "get",
            "--compartment-id",
            compartment,
        ]
    return [
        *command,
        "list",
        "--name",
        compartment,
        "--compartment-id-in-subtree",
        "true",
        "--access-level",
        "ANY",
        "--include-root",
        "--all",
    ]


def _build_docker_login_command(
    payload: dict[str, Any], ocir_registry: str
) -> list[str]:
    """Build the Docker login command for OCI Container Registry.

    Args:
        payload: Normalized deployment payload.
        ocir_registry: Target OCIR registry hostname.

    Returns:
        list[str]: Docker login command arguments with the password redacted.
    """

    return [
        "docker",
        "login",
        ocir_registry,
        "--username",
        str(payload["ocir_username"]),
        "--password",
        "********",
    ]


def _build_genai_project_resolution_command(
    payload: dict[str, Any], compartment_id: str
) -> list[str]:
    """Build the command that resolves a GenAI project name or validates an OCID.

    Args:
        payload: Normalized deployment payload.
        compartment_id: Resolved compartment OCID or dry-run placeholder.

    Returns:
        list[str]: OCI CLI command arguments.
    """

    project = str(payload["genai_project"])
    command = [
        "oci",
        "--region",
        payload["region"],
        "--output",
        "json",
        "generative-ai",
        "project",
    ]
    if project.startswith(GENAI_PROJECT_OCID_PREFIX):
        return [
            *command,
            "get",
            "--project-id",
            project,
        ]
    return [
        *command,
        "list",
        "--compartment-id",
        compartment_id,
        "--display-name",
        project,
        "--all",
    ]


def _artifact_path(filename: str) -> str:
    """Return the relative path used by generated dry-run artifacts.

    Args:
        filename: Artifact filename.

    Returns:
        str: Relative artifact path.
    """

    return f"{GENERATED_ARTIFACT_DIR}/{filename}"


def _file_uri(filename: str) -> str:
    """Return an OCI CLI file URI for a generated dry-run artifact.

    Args:
        filename: Artifact filename.

    Returns:
        str: OCI CLI file URI.
    """

    return f"file://{_artifact_path(filename)}"
