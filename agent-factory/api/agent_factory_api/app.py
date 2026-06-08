"""
Author: L. Saetta
Date last modified: 2026-06-08
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
    build_ocir_registry,
    redact_runtime_environment,
)
from agent_factory_api.executor import (
    CommandExecutionError,
    execute_live_deployment_commands,
)
from agent_factory_api.models import (
    DeploymentRun,
    FactoryStep,
    SUPPORTED_REGIONS,
    format_commands,
    redact_payload,
    utc_now,
    validate_deployment_payload,
)
from agent_factory_api.resources import (
    FoundationResourcesResult,
    ResourceProvisioningError,
    preflight_foundation_resources,
    provision_foundation_resources,
    validate_ocir_login,
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


@app.post("/factory/ocir-login/check")
async def check_ocir_login(request: Request) -> JSONResponse:
    """Validate submitted OCIR Docker credentials without creating resources.

    Args:
        request: FastAPI request containing region and OCIR credentials.

    Returns:
        JSONResponse: Validation status or structured field errors.
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

    validation_errors = _validate_ocir_login_check_payload(payload)
    if validation_errors:
        return JSONResponse(
            {
                "error": "OCIR credential validation input failed.",
                "field_errors": validation_errors,
            },
            status_code=400,
        )

    normalized_payload = {
        "region": str(payload["region"]).strip(),
        "ocir_username": str(payload["ocir_username"]).strip(),
        "ocir_password": str(payload["ocir_password"]).strip(),
    }
    try:
        result = validate_ocir_login(
            registry=build_ocir_registry(normalized_payload),
            username=normalized_payload["ocir_username"],
            password=normalized_payload["ocir_password"],
        )
    except ResourceProvisioningError as exc:
        return JSONResponse(
            {
                "status": "failed",
                "error": str(exc),
                "field_errors": {},
            },
            status_code=400,
        )

    return JSONResponse(
        {
            "status": "succeeded",
            "message": "OCIR Docker login succeeded.",
            "ocir_registry": result["ocir_registry"],
            "ocir_username": result["ocir_username"],
        }
    )


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


def _validate_ocir_login_check_payload(payload: dict[str, Any]) -> dict[str, str]:
    """Validate the minimal payload required for OCIR login checks.

    Args:
        payload: Raw JSON payload.

    Returns:
        dict[str, str]: Validation errors keyed by field name.
    """

    errors: dict[str, str] = {}
    for field_name in ("region", "ocir_username", "ocir_password"):
        value = payload.get(field_name)
        if not isinstance(value, str) or not value.strip():
            errors[field_name] = "This field is required."

    region = str(payload.get("region", "")).strip()
    if region and region not in SUPPORTED_REGIONS:
        accepted = ", ".join(sorted(SUPPORTED_REGIONS))
        errors["region"] = f"Expected one of: {accepted}."

    return errors


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
    ocir_login_result: dict[str, str] | None = None
    plan_payload = dict(payload)

    try:
        if dry_run:
            resource_result = preflight_foundation_resources(payload)
        else:
            resource_result = provision_foundation_resources(payload)
        if resource_result is not None:
            plan_payload["compartment"] = resource_result.compartment_id
            plan_payload["genai_project"] = resource_result.project.project_id
            plan_payload["object_storage_namespace"] = (
                resource_result.bucket.namespace_name
            )
            plan_payload["vector_store_name"] = (
                resource_result.vector_store.vector_store_id
            )
            if resource_result.connector is not None:
                plan_payload["connector_name"] = resource_result.connector.connector_id
        if dry_run:
            ocir_login_result = validate_ocir_login(
                registry=build_ocir_registry(plan_payload),
                username=str(plan_payload["ocir_username"]),
                password=str(plan_payload["ocir_password"]),
            )
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
    if ocir_login_result is not None:
        _attach_ocir_login_outputs(steps, ocir_login_result)

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
    plan_payload["genai_project"] = resource_result.project.project_id
    plan_payload["object_storage_namespace"] = resource_result.bucket.namespace_name
    plan_payload["vector_store_name"] = resource_result.vector_store.vector_store_id
    if resource_result.connector is not None:
        plan_payload["connector_name"] = resource_result.connector.connector_id

    plan = build_deployment_plan(plan_payload, dry_run=False)
    deployment_run.commands = plan["commands"]
    planned_steps = _build_steps(plan_payload, plan["commands"])
    _refresh_step_commands(deployment_run.steps, planned_steps)
    _attach_resource_outputs(deployment_run.steps, resource_result)
    try:
        execution_outputs = execute_live_deployment_commands(
            plan_payload,
            _commands_by_step_id(planned_steps),
            update_progress,
        )
    except CommandExecutionError as exc:
        _mark_live_run_failed(deployment_run, plan_payload, str(exc), exc.step_id)
        return
    deployment_run.outputs = _build_run_outputs(
        plan_payload=plan_payload,
        plan=plan,
        resource_result=resource_result,
        dry_run=False,
        execution_outputs=execution_outputs,
    )
    deployment_run.status = "succeeded"
    deployment_run.completed_at = utc_now()


def _build_run_outputs(
    *,
    plan_payload: dict[str, Any],
    plan: dict[str, Any],
    resource_result: FoundationResourcesResult | None,
    dry_run: bool,
    execution_outputs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build non-secret deployment run outputs.

    Args:
        plan_payload: Payload used to build the final command plan.
        plan: Generated command plan.
        resource_result: Live resource provisioning result, if any.
        dry_run: Whether this was a dry run.
        execution_outputs: Non-secret outputs from live command execution.

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
            "Dry run completed with read-only OCI checks and without OCI writes."
            if dry_run
            else (
                "Deployment workflow completed with live Docker, OCIR, and "
                "Hosted Application operations."
            )
        ),
    }
    if execution_outputs:
        outputs.update(
            {
                "endpoint_url": execution_outputs.get("endpoint_url"),
                "hosted_application_id": execution_outputs.get("hosted_application_id"),
                "hosted_deployment_id": execution_outputs.get("hosted_deployment_id"),
            }
        )

    if resource_result is not None:
        outputs["foundation_resources"] = {
            "compartment_id": resource_result.compartment_id,
            "genai_project": {
                "project_id": resource_result.project.project_id,
                "name": resource_result.project.name,
            },
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
    deployment_run: DeploymentRun,
    payload: dict[str, Any],
    error_message: str,
    failed_step_id: str | None = None,
) -> None:
    """Mark a live deployment run as failed.

    Args:
        deployment_run: Run state to update.
        payload: Normalized deployment payload.
        error_message: Sanitized provisioning error.
        failed_step_id: Explicit failed step identifier, if known.
    """

    timestamp = utc_now()
    failed_step_id = failed_step_id or _failed_resource_step_id(error_message)
    _set_step_status(
        deployment_run.steps,
        failed_step_id,
        "failed",
        error=error_message,
        timestamp=timestamp,
    )
    _mark_running_steps_failed(
        deployment_run.steps,
        error_message=error_message,
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
        "note": (
            "Live deployment failed before completion. Previously completed "
            "steps may have created resources."
        ),
    }
    deployment_run.error = error_message


def _commands_by_step_id(steps: list[FactoryStep]) -> dict[str, list[str]]:
    """Return commands keyed by workflow step identifier.

    Args:
        steps: Workflow steps with attached commands.

    Returns:
        dict[str, list[str]]: Command arguments keyed by step identifier.
    """

    return {step.step_id: step.command for step in steps if step.command is not None}


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
        if step.step_id == "resolve-genai-project":
            step.outputs = {
                "genai_project_id": resource_result.project.project_id,
                "name": resource_result.project.name,
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


def _attach_ocir_login_outputs(
    steps: list[FactoryStep], ocir_login_result: dict[str, str]
) -> None:
    """Attach OCIR login validation outputs to workflow steps.

    Args:
        steps: Workflow steps for the run.
        ocir_login_result: Non-secret Docker login validation result.
    """

    step = _find_step(steps, "registry-login")
    if step is not None:
        step.outputs = ocir_login_result


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


def _mark_running_steps_failed(
    steps: list[FactoryStep], *, error_message: str, timestamp: str
) -> None:
    """Fail any step still marked running after a run-level failure.

    Args:
        steps: Workflow steps for the run.
        error_message: Sanitized run error.
        timestamp: Failure timestamp.
    """

    for step in steps:
        if step.status == "running":
            step.status = "failed"
            step.ended_at = timestamp
            if step.error is None:
                step.error = error_message


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
    if "project" in normalized_error:
        return "resolve-genai-project"
    if "bucket" in normalized_error:
        return "bucket"
    if "connector" in normalized_error:
        return "data-sync-connector"
    if "ocir" in normalized_error or "docker" in normalized_error:
        return "registry-login"
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
            "resolve-genai-project",
            "Resolve GenAI project",
            command=commands[1],
        ),
        FactoryStep(
            "bucket",
            "Create or reuse Object Storage bucket",
            command=commands[2],
        ),
        FactoryStep(
            "vector-store",
            "Create or reuse Vector Store",
            command=commands[3],
        ),
        FactoryStep(
            "data-sync-connector",
            "Create, reuse, or skip Data Sync Connector",
            status=connector_status,
            command=commands[4],
        ),
        FactoryStep(
            "docker-build",
            "Build RAG agent backend image",
            command=commands[5],
        ),
        FactoryStep(
            "registry",
            "Check or prepare OCI Container Registry",
            command=commands[6],
        ),
        FactoryStep(
            "registry-login",
            "Authenticate Docker to OCI Container Registry",
            command=commands[7],
        ),
        FactoryStep(
            "docker-push",
            "Push image to OCI Container Registry",
            command=commands[8],
        ),
        FactoryStep(
            "runtime-environment",
            "Generate Hosted Application runtime environment",
        ),
        FactoryStep(
            "hosted-application",
            "Create OCI Enterprise AI Hosted Application",
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
