"""
Author: L. Saetta
Date last modified: 2026-06-07
License: MIT
Description: FastAPI backend skeleton for Agent Factory deployment orchestration.
"""

from __future__ import annotations

# pylint: disable=duplicate-code

from typing import Any
from uuid import uuid4

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse

from agent_factory_api.commands import (
    build_deployment_plan,
    redact_runtime_environment,
)
from agent_factory_api.models import (
    DeploymentRun,
    FactoryStep,
    format_commands,
    redact_payload,
    utc_now,
    validate_deployment_payload,
)
from agent_factory_api.resources import (
    FoundationResourcesResult,
    ResourceProvisioningError,
    provision_foundation_resources,
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
async def create_deployment(
    request: Request, background_tasks: BackgroundTasks
) -> JSONResponse:
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
    if bool(validation.payload["dry_run"]):
        deployment_run = _create_run(validation.payload)
    else:
        deployment_run = _create_live_run(validation.payload)
        background_tasks.add_task(
            _execute_live_run,
            deployment_run.deployment_run_id,
            validation.payload,
        )
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
    now = utc_now()
    resource_result: FoundationResourcesResult | None = None
    plan_payload = dict(payload)

    try:
        if not dry_run:
            resource_result = provision_foundation_resources(payload)
            plan_payload["compartment"] = resource_result.compartment_id
            plan_payload["vector_store_name"] = (
                resource_result.vector_store.vector_store_id
            )
            if resource_result.connector is not None:
                plan_payload["connector_name"] = resource_result.connector.connector_id
    except ResourceProvisioningError as exc:
        return _failed_resource_run(payload, dry_run, now, str(exc))

    plan = build_deployment_plan(plan_payload, dry_run)
    commands = plan["commands"]
    steps = _build_steps(plan_payload, commands)
    status = "succeeded"

    for step in steps:
        if step.status != "skipped":
            step.status = "succeeded"
        step.started_at = now
        step.ended_at = now

    if resource_result is not None:
        _attach_resource_outputs(steps, resource_result)

    return DeploymentRun(
        deployment_run_id=str(uuid4()),
        dry_run=dry_run,
        status=status,
        submitted_at=now,
        completed_at=now,
        request=redact_payload(payload),
        steps=steps,
        commands=commands,
        outputs=_build_run_outputs(
            plan_payload=plan_payload,
            plan=plan,
            resource_result=resource_result,
            dry_run=dry_run,
        ),
    )


def _create_live_run(payload: dict[str, Any]) -> DeploymentRun:
    """Create an in-memory live deployment run before execution starts.

    Args:
        payload: Normalized deployment payload.

    Returns:
        DeploymentRun: Initial live run state.
    """

    now = utc_now()
    plan = build_deployment_plan(payload, dry_run=False)
    steps = _build_steps(payload, plan["commands"])
    _set_step_status(steps, "validate-input", "succeeded", timestamp=now)

    return DeploymentRun(
        deployment_run_id=str(uuid4()),
        dry_run=False,
        status="running",
        submitted_at=now,
        completed_at=None,
        request=redact_payload(payload),
        steps=steps,
        commands=plan["commands"],
        outputs={
            "image_reference": plan["image_reference"],
            "hosted_application_name": payload["hosted_application_name"],
            "deployment_name": payload["deployment_name"],
            "endpoint_url": None,
            "resolved_identifiers": plan["resolved_identifiers"],
            "runtime_environment": redact_runtime_environment(
                plan["runtime_environment"]
            ),
            "dry_run_artifacts": plan["artifacts"],
            "note": "Live deployment started. Resource provisioning is in progress.",
        },
    )


def _execute_live_run(deployment_run_id: str, payload: dict[str, Any]) -> None:
    """Execute a live Agent Factory run and update its status incrementally.

    Args:
        deployment_run_id: Deployment run identifier.
        payload: Normalized deployment payload.
    """

    deployment_run = RUNS[deployment_run_id]

    def update_progress(
        step_id: str, status: str, outputs: dict[str, Any] | None
    ) -> None:
        _set_step_status(
            deployment_run.steps,
            step_id,
            status,
            outputs=outputs,
            timestamp=utc_now(),
        )

    try:
        resource_result = provision_foundation_resources(
            payload,
            progress_callback=update_progress,
        )
    except ResourceProvisioningError as exc:
        _mark_live_run_failed(deployment_run, payload, str(exc))
        return
    except Exception as exc:  # pylint: disable=broad-exception-caught
        _mark_live_run_failed(deployment_run, payload, f"Unexpected error: {exc}")
        return

    plan_payload = dict(payload)
    plan_payload["compartment"] = resource_result.compartment_id
    plan_payload["vector_store_name"] = resource_result.vector_store.vector_store_id
    if resource_result.connector is not None:
        plan_payload["connector_name"] = resource_result.connector.connector_id

    plan = build_deployment_plan(plan_payload, dry_run=False)
    deployment_run.commands = plan["commands"]
    _refresh_step_commands(
        deployment_run.steps, _build_steps(plan_payload, plan["commands"])
    )
    _complete_planned_steps(deployment_run.steps, timestamp=utc_now())
    _attach_resource_outputs(deployment_run.steps, resource_result)
    deployment_run.outputs = _build_run_outputs(
        plan_payload=plan_payload,
        plan=plan,
        resource_result=resource_result,
        dry_run=False,
    )
    deployment_run.status = "succeeded"
    deployment_run.completed_at = utc_now()


def _build_run_outputs(
    *,
    plan_payload: dict[str, Any],
    plan: dict[str, Any],
    resource_result: FoundationResourcesResult | None,
    dry_run: bool,
) -> dict[str, Any]:
    """Build non-secret deployment run outputs.

    Args:
        plan_payload: Payload used to build the final command plan.
        plan: Generated command plan.
        resource_result: Live resource provisioning result, if any.
        dry_run: Whether this was a dry run.

    Returns:
        dict[str, Any]: Run outputs safe for API responses.
    """

    outputs = {
        "image_reference": plan["image_reference"],
        "hosted_application_name": plan_payload["hosted_application_name"],
        "deployment_name": plan_payload["deployment_name"],
        "endpoint_url": None,
        "resolved_identifiers": plan["resolved_identifiers"],
        "runtime_environment": redact_runtime_environment(plan["runtime_environment"]),
        "dry_run_artifacts": plan["artifacts"],
        "note": (
            "Dry run completed without OCI writes."
            if dry_run
            else (
                "Object Storage bucket, Vector Store, and Data Sync Connector "
                "were provisioned; "
                "remaining deployment actions are still planned only."
            )
        ),
    }

    if resource_result is not None:
        outputs["foundation_resources"] = {
            "compartment_id": resource_result.compartment_id,
            "bucket": {
                "bucket_name": resource_result.bucket.bucket_name,
                "namespace_name": resource_result.bucket.namespace_name,
                "lifecycle_state": resource_result.bucket.lifecycle_state,
                "created": resource_result.bucket.created,
            },
            "vector_store": {
                "vector_store_id": resource_result.vector_store.vector_store_id,
                "name": resource_result.vector_store.name,
                "created": resource_result.vector_store.created,
            },
            "connector": (
                {
                    "connector_id": resource_result.connector.connector_id,
                    "name": resource_result.connector.name,
                    "lifecycle_state": resource_result.connector.lifecycle_state,
                    "created": resource_result.connector.created,
                    "skipped": resource_result.connector.skipped,
                }
                if resource_result.connector is not None
                else None
            ),
        }

    return outputs


def _failed_resource_run(
    payload: dict[str, Any], dry_run: bool, timestamp: str, error_message: str
) -> DeploymentRun:
    """Build a failed deployment run for bucket or Vector Store errors.

    Args:
        payload: Normalized deployment payload.
        dry_run: Whether the run was requested as a dry run.
        timestamp: Completion timestamp.
        error_message: Sanitized provisioning error.

    Returns:
        DeploymentRun: Failed run state.
    """

    plan = build_deployment_plan(payload, dry_run)
    steps = _build_steps(payload, plan["commands"])
    failed_step_id = _failed_resource_step_id(error_message)
    for step in steps:
        if step.step_id == failed_step_id:
            step.status = "failed"
            step.started_at = timestamp
            step.ended_at = timestamp
            step.error = error_message
            break

    return DeploymentRun(
        deployment_run_id=str(uuid4()),
        dry_run=dry_run,
        status="failed",
        submitted_at=timestamp,
        completed_at=timestamp,
        request=redact_payload(payload),
        steps=steps,
        commands=plan["commands"],
        outputs={
            "image_reference": plan["image_reference"],
            "hosted_application_name": payload["hosted_application_name"],
            "deployment_name": payload["deployment_name"],
            "endpoint_url": None,
            "resolved_identifiers": plan["resolved_identifiers"],
            "runtime_environment": redact_runtime_environment(
                plan["runtime_environment"]
            ),
            "dry_run_artifacts": plan["artifacts"],
            "note": "Resource provisioning failed before deployment planning.",
        },
        error=error_message,
    )


def _mark_live_run_failed(
    deployment_run: DeploymentRun, payload: dict[str, Any], error_message: str
) -> None:
    """Mark a live deployment run as failed.

    Args:
        deployment_run: Run state to update.
        payload: Normalized deployment payload.
        error_message: Sanitized provisioning error.
    """

    timestamp = utc_now()
    failed_step_id = _failed_resource_step_id(error_message)
    _set_step_status(
        deployment_run.steps,
        failed_step_id,
        "failed",
        error=error_message,
        timestamp=timestamp,
    )
    plan = build_deployment_plan(payload, dry_run=False)
    deployment_run.status = "failed"
    deployment_run.completed_at = timestamp
    deployment_run.outputs = {
        "image_reference": plan["image_reference"],
        "hosted_application_name": payload["hosted_application_name"],
        "deployment_name": payload["deployment_name"],
        "endpoint_url": None,
        "resolved_identifiers": plan["resolved_identifiers"],
        "runtime_environment": redact_runtime_environment(plan["runtime_environment"]),
        "dry_run_artifacts": plan["artifacts"],
        "note": "Resource provisioning failed before deployment planning.",
    }
    deployment_run.error = error_message


def _attach_resource_outputs(
    steps: list[FactoryStep], resource_result: FoundationResourcesResult
) -> None:
    """Attach bucket and Vector Store outputs to workflow steps.

    Args:
        steps: Workflow steps for the run.
        resource_result: Provisioned foundation resources.
    """

    for step in steps:
        if step.step_id == "bucket":
            step.outputs = {
                "bucket_name": resource_result.bucket.bucket_name,
                "namespace_name": resource_result.bucket.namespace_name,
                "created": resource_result.bucket.created,
            }
        if step.step_id == "vector-store":
            step.outputs = {
                "vector_store_id": resource_result.vector_store.vector_store_id,
                "name": resource_result.vector_store.name,
                "created": resource_result.vector_store.created,
            }
        if step.step_id == "data-sync-connector":
            step.outputs = (
                {
                    "connector_id": resource_result.connector.connector_id,
                    "name": resource_result.connector.name,
                    "created": resource_result.connector.created,
                    "skipped": resource_result.connector.skipped,
                }
                if resource_result.connector is not None
                else {"skipped": True}
            )


def _set_step_status(  # pylint: disable=too-many-arguments
    steps: list[FactoryStep],
    step_id: str,
    status: str,
    *,
    timestamp: str,
    outputs: dict[str, Any] | None = None,
    error: str | None = None,
) -> None:
    """Update a workflow step status in place.

    Args:
        steps: Workflow steps for the run.
        step_id: Target step identifier.
        status: New step status.
        timestamp: Update timestamp.
        outputs: Optional non-secret step outputs.
        error: Optional sanitized step error.
    """

    step = _find_step(steps, step_id)
    if step is None:
        return
    if step.started_at is None:
        step.started_at = timestamp
    step.status = status  # type: ignore[assignment]
    if status in {"succeeded", "failed", "skipped"}:
        step.ended_at = timestamp
    if outputs is not None:
        step.outputs = outputs
    if error is not None:
        step.error = error


def _complete_planned_steps(steps: list[FactoryStep], *, timestamp: str) -> None:
    """Mark planned-only remaining steps as completed.

    Args:
        steps: Workflow steps for the run.
        timestamp: Completion timestamp.
    """

    for step in steps:
        if step.status == "pending":
            _set_step_status(steps, step.step_id, "succeeded", timestamp=timestamp)


def _refresh_step_commands(
    steps: list[FactoryStep], planned_steps: list[FactoryStep]
) -> None:
    """Refresh workflow commands after live resource identifiers are resolved.

    Args:
        steps: Existing run steps to mutate.
        planned_steps: Steps built from the final command plan.
    """

    commands_by_step_id = {
        planned_step.step_id: planned_step.command for planned_step in planned_steps
    }
    for step in steps:
        if step.step_id in commands_by_step_id:
            step.command = commands_by_step_id[step.step_id]


def _find_step(steps: list[FactoryStep], step_id: str) -> FactoryStep | None:
    """Return a step by identifier.

    Args:
        steps: Workflow steps for the run.
        step_id: Target step identifier.

    Returns:
        FactoryStep | None: Matching step, if present.
    """

    for step in steps:
        if step.step_id == step_id:
            return step
    return None


def _failed_resource_step_id(error_message: str) -> str:
    """Return the workflow step that best matches a provisioning error.

    Args:
        error_message: Sanitized provisioning error message.

    Returns:
        str: Failed resource step identifier.
    """

    normalized_error = error_message.lower()
    if "compartment" in normalized_error:
        return "resolve-compartment"
    if "bucket" in normalized_error:
        return "bucket"
    if "connector" in normalized_error:
        return "data-sync-connector"
    return "vector-store"


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
            "runtime-environment",
            "Generate Hosted Application runtime environment",
            command=commands[9],
        ),
        FactoryStep(
            "hosted-deployment",
            "Create Hosted Application deployment",
            command=commands[10],
        ),
        FactoryStep(
            "deployment-readiness",
            "Wait for Hosted Application deployment readiness",
            command=commands[11],
        ),
        FactoryStep(
            "health",
            "Validate deployed health endpoint",
            command=commands[12],
        ),
    ]
