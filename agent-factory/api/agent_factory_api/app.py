"""
Author: L. Saetta
Date last modified: 2026-06-06
License: MIT
Description: FastAPI backend skeleton for Agent Factory deployment orchestration.
"""

from __future__ import annotations

# pylint: disable=duplicate-code

from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse

from agent_factory_api.commands import build_apply_commands, build_dry_run_commands
from agent_factory_api.models import (
    DeploymentRun,
    FactoryStep,
    format_commands,
    redact_payload,
    utc_now,
    validate_deployment_payload,
)

RUNS: dict[str, DeploymentRun] = {}

app = FastAPI(title="Agent Factory API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/factory/health")
def health() -> dict[str, str]:
    """Return Agent Factory backend health.

    Returns:
        dict[str, str]: Health response.
    """

    return {"status": "ok"}


@app.post("/factory/deployments")
async def create_deployment(request: Request) -> JSONResponse:
    """Create an Agent Factory deployment run.

    Args:
        request: FastAPI request containing the deployment payload.

    Returns:
        JSONResponse: Deployment run status or validation errors.
    """

    try:
        payload = await request.json()
    except ValueError:
        return JSONResponse(
            {"error": "Invalid JSON payload.", "field_errors": {}},
            status_code=400,
        )

    if not isinstance(payload, dict):
        return JSONResponse(
            {"error": "Payload must be a JSON object.", "field_errors": {}},
            status_code=400,
        )

    validation = validate_deployment_payload(payload)
    if validation.errors:
        return JSONResponse(
            {
                "error": "Deployment input validation failed.",
                "field_errors": validation.errors,
            },
            status_code=400,
        )

    assert validation.payload is not None
    deployment_run = _create_run(validation.payload)
    RUNS[deployment_run.deployment_run_id] = deployment_run
    return JSONResponse(deployment_run.to_dict(), status_code=201)


@app.get("/factory/deployments/{deployment_run_id}")
def get_deployment(deployment_run_id: str) -> dict[str, Any]:
    """Return an Agent Factory deployment run by ID.

    Args:
        deployment_run_id: Deployment run identifier.

    Returns:
        dict[str, Any]: Deployment run status.

    Raises:
        HTTPException: If the deployment run does not exist.
    """

    deployment_run = RUNS.get(deployment_run_id)
    if deployment_run is None:
        raise HTTPException(status_code=404, detail="Deployment run not found.")

    return deployment_run.to_dict()


@app.get("/factory/deployments/{deployment_run_id}/commands")
def get_deployment_commands(deployment_run_id: str) -> PlainTextResponse:
    """Return deployment commands as a downloadable shell script.

    Args:
        deployment_run_id: Deployment run identifier.

    Returns:
        PlainTextResponse: Shell script content.

    Raises:
        HTTPException: If the deployment run does not exist.
    """

    deployment_run = RUNS.get(deployment_run_id)
    if deployment_run is None:
        raise HTTPException(status_code=404, detail="Deployment run not found.")

    return PlainTextResponse(
        format_commands(deployment_run.commands),
        media_type="text/x-shellscript",
        headers={
            "Content-Disposition": (
                f'attachment; filename="agent-factory-{deployment_run_id}.sh"'
            )
        },
    )


def _create_run(payload: dict[str, Any]) -> DeploymentRun:
    """Create an in-memory deployment run from a validated payload.

    Args:
        payload: Normalized deployment payload.

    Returns:
        DeploymentRun: Completed skeleton deployment run.
    """

    dry_run = bool(payload["dry_run"])
    commands = (
        build_dry_run_commands(payload) if dry_run else build_apply_commands(payload)
    )
    now = utc_now()
    steps = _build_steps(payload, commands)
    status = "succeeded"

    for step in steps:
        step.status = "succeeded"
        step.started_at = now
        step.ended_at = now

    outputs = {
        "image_reference": commands[7][3] if dry_run else commands[4][6],
        "hosted_application_name": payload["hosted_application_name"],
        "deployment_name": payload["deployment_name"],
        "endpoint_url": None,
        "note": (
            "Dry run completed without OCI writes."
            if dry_run
            else "Skeleton run completed without executing OCI writes."
        ),
    }

    return DeploymentRun(
        deployment_run_id=str(uuid4()),
        dry_run=dry_run,
        status=status,
        submitted_at=now,
        completed_at=now,
        request=redact_payload(payload),
        steps=steps,
        commands=commands,
        outputs=outputs,
    )


def _build_steps(
    payload: dict[str, Any], commands: list[list[str]]
) -> list[FactoryStep]:
    """Build ordered Agent Factory workflow steps.

    Args:
        payload: Normalized deployment payload.
        commands: Generated command plan.

    Returns:
        list[FactoryStep]: Ordered workflow steps.
    """

    connector_status = "skipped" if payload["connector_mode"] == "skip" else "pending"

    return [
        FactoryStep("validate-input", "Validate deployment inputs"),
        FactoryStep(
            "resolve-compartment",
            "Resolve target compartment",
            command=commands[0],
        ),
        FactoryStep(
            "bucket",
            "Create or reuse Object Storage bucket",
            command=commands[1],
        ),
        FactoryStep(
            "vector-store",
            "Create or reuse Vector Store",
            command=commands[2],
        ),
        FactoryStep(
            "data-sync-connector",
            "Create, reuse, or skip Data Sync Connector",
            status=connector_status,
            command=commands[3],
        ),
        FactoryStep(
            "docker-build",
            "Build RAG agent backend image",
            command=commands[4],
        ),
        FactoryStep(
            "registry",
            "Check or prepare OCI Container Registry",
            command=commands[5],
        ),
        FactoryStep(
            "registry-login",
            "Authenticate Docker to OCI Container Registry",
            command=commands[6],
        ),
        FactoryStep(
            "docker-push",
            "Push image to OCI Container Registry",
            command=commands[7],
        ),
        FactoryStep(
            "hosted-application",
            "Create OCI Enterprise AI Hosted Application",
            command=commands[8],
        ),
        FactoryStep(
            "hosted-deployment",
            "Create Hosted Application deployment",
            command=commands[9],
        ),
        FactoryStep(
            "deployment-readiness",
            "Wait for Hosted Application deployment readiness",
            command=commands[10],
        ),
        FactoryStep(
            "health",
            "Validate deployed health endpoint",
            command=commands[11],
        ),
    ]
