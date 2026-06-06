"""
Author: L. Saetta
Date last modified: 2026-06-06
License: MIT
Description: Command planning helpers for Agent Factory deployment runs.
"""

from __future__ import annotations

from typing import Any


def build_dry_run_commands(payload: dict[str, Any]) -> list[list[str]]:
    """Build non-mutating validation commands for an Agent Factory dry run.

    Args:
        payload: Normalized deployment payload.

    Returns:
        list[list[str]]: Structured command arguments.
    """

    image_reference = build_image_reference(payload)

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
        [
            "oci",
            "iam",
            "compartment",
            "get",
            "--compartment-id",
            payload["compartment"],
        ],
        [
            "oci",
            "os",
            "bucket",
            "get",
            "--namespace-name",
            "<object-storage-namespace>",
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
            "buildx",
            "build",
            "--platform",
            "linux/amd64",
            "--check",
            "-f",
            "Dockerfile",
            ".",
        ],
        [
            "oci",
            "artifacts",
            "container",
            "repository",
            "get",
            "--repository-name",
            payload["container_repository_name"],
        ],
        [
            "docker",
            "login",
            f"{payload['region']}.ocir.io",
        ],
        [
            "docker",
            "manifest",
            "inspect",
            image_reference,
        ],
        [
            "oci",
            "generative-ai",
            "hosted-application",
            "list",
            "--compartment-id",
            payload["compartment"],
        ],
        [
            "oci",
            "generative-ai",
            "hosted-application-deployment",
            "list",
            "--compartment-id",
            payload["compartment"],
        ],
        [
            "oci",
            "generative-ai",
            "work-request",
            "list",
            "--compartment-id",
            payload["compartment"],
        ],
        [
            "curl",
            "-fsS",
            "<deployed-health-endpoint>/health",
        ],
    ]


def build_apply_commands(payload: dict[str, Any]) -> list[list[str]]:
    """Build mutating command plan for a real deployment run.

    Args:
        payload: Normalized deployment payload.

    Returns:
        list[list[str]]: Structured command arguments.
    """

    image_reference = build_image_reference(payload)

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
        [
            "oci",
            "iam",
            "compartment",
            "get",
            "--compartment-id",
            payload["compartment"],
        ],
        [
            "oci",
            "os",
            "bucket",
            "create",
            "--compartment-id",
            payload["compartment"],
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
            "buildx",
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
            "artifacts",
            "container",
            "repository",
            "create",
            "--display-name",
            payload["container_repository_name"],
            "--compartment-id",
            payload["compartment"],
        ],
        [
            "docker",
            "login",
            f"{payload['region']}.ocir.io",
        ],
        [
            "docker",
            "push",
            image_reference,
        ],
        [
            "oci",
            "generative-ai",
            "hosted-application",
            "create",
            "--display-name",
            payload["hosted_application_name"],
            "--compartment-id",
            payload["compartment"],
        ],
        [
            "oci",
            "generative-ai",
            "hosted-application-deployment",
            "create",
            "--display-name",
            payload["deployment_name"],
            "--image",
            image_reference,
        ],
        [
            "oci",
            "generative-ai",
            "hosted-application-deployment",
            "get",
            "--deployment-id",
            "<deployment-ocid>",
        ],
        [
            "curl",
            "-fsS",
            "<deployed-health-endpoint>/health",
        ],
    ]


def build_image_reference(payload: dict[str, Any]) -> str:
    """Build the target OCI Container Registry image reference.

    Args:
        payload: Normalized deployment payload.

    Returns:
        str: Image reference placeholder suitable for display and later execution.
    """

    repository = payload["container_repository_name"].strip("/")
    return (
        f"{payload['region']}.ocir.io/<tenancy-namespace>/{repository}:"
        f"{payload['container_image_tag']}"
    )
