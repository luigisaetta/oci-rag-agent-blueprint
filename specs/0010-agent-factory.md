# Agent Factory

## Purpose

This specification defines the Agent Factory application.

Agent Factory is an operational web application that guides a user through all
required steps to deploy the OCI RAG Agent backend into OCI Enterprise AI as a
Hosted Application deployment.

The application must collect deployment inputs, validate them, orchestrate OCI
resource creation or reuse, publish the agent backend container image to OCI
Container Registry, create the Hosted Application, create a deployment inside
that Hosted Application, and configure the deployed RAG agent to use the selected
OCI Vector Store.

The goal is to turn the current manual deployment process into a repeatable,
auditable, guided workflow.

## Scope

This specification covers:

- Agent Factory application structure.
- Backend orchestration responsibilities.
- Required implementation mechanisms for OCI resource operations.
- Next.js UI requirements.
- Required and optional deployment inputs.
- Sequential deployment workflow.
- OCI resource creation and reuse behavior.
- Container image build and registry publishing behavior.
- Hosted Application and deployment creation behavior.
- Runtime environment variables for the deployed RAG agent.
- Status, progress, error handling, and retry expectations.
- Initial exclusions for JWT protection and private networking.

This specification does not cover:

- Implementation details of every OCI SDK call.
- Full IAM policy automation.
- JWT-protected Hosted Application deployments.
- Private endpoint deployments.
- Custom VCN/subnet network setup.
- Multi-agent deployments.
- Cross-region deployment.
- Production approval workflows.
- Cost estimation.

## Related Specifications

- [Architecture Guidelines](0001-architecture-guidelines.md)
- [Agent Implementation](0003-agent-implementation.md)
- [Deployment](0004-deployment.md)
- [Reference UI](0006-reference-ui.md)
- [Security](0007-security.md)
- [Document Loading](0008-document-loading.md)
- [Agent Runtime Tuning](0009-agent-runtime-tuning.md)

## Official References

- [OCI Generative AI Hosted Applications and Deployments](https://docs.oracle.com/en-us/iaas/Content/generative-ai/applications-deployments.htm)

## Application Structure

Agent Factory must be implemented as a separate application from the RAG agent
runtime.

The application must include:

- A backend service that performs validation and orchestrates OCI operations.
- A Next.js UI that collects inputs, displays progress, and starts the deployment
  workflow.

The Agent Factory backend must not be deployed as part of the generated RAG agent
Hosted Application. It is a deployment tool, not part of the runtime serving
path for user RAG requests.

The Agent Factory UI must call the Agent Factory backend. It must not call OCI
control plane APIs directly from the browser.

## Local Docker Compose Deployment

Agent Factory must provide a Docker Compose deployment that is separate from the
RAG agent demo deployment.

The local Docker Compose deployment must include:

- A FastAPI backend container for the Agent Factory API.
- A Next.js frontend container for the Agent Factory UI.
- A Compose file format version compatible with Docker Compose v1 on Linux and
  Docker Compose v2 on macOS.
- A dedicated Compose project name passed by the helper scripts with
  `docker-compose -p agent-factory`, so it can be started and stopped without
  affecting the RAG agent demo deployment while remaining compatible with
  Docker Compose v1 on Linux.
- Root-level helper scripts named `start_factory.sh` and `stop_factory.sh`.
- Docker CLI installed in the Agent Factory API image, because the backend
  performs Docker login, build, and push operations.
- OCI CLI installed in the Agent Factory API image, because Hosted Application
  creation, deployment creation, and deployment polling are executed with OCI
  CLI commands.
- A read-only bind mount of the repository root into the API container, exposed
  through `AGENT_FACTORY_REPO_ROOT`, so live deployments can build the RAG agent
  backend image from the root `Dockerfile`.
- A bind mount of the host Docker socket at `/var/run/docker.sock` for local
  Compose runs, so the API container can use the host Docker daemon.

The helper scripts must start and stop only the Agent Factory services.
The helper scripts must prefer `docker compose` v2 when available and fall back
to `docker-compose` v1 only when the v2 plugin is not installed, because older
`docker-compose` clients can fail against newer Docker daemons.
The helper scripts must export default Compose interpolation variables before
invoking Compose, instead of relying on shell default interpolation syntax inside
the Compose file.
When `start_factory.sh --build` is used, the API container must be rebuilt and
recreated so changes to runtime tools such as Docker CLI are reflected in the
running service.

The default local ports must be:

| Service | Port |
| --- | --- |
| Agent Factory API | `8081` |
| Agent Factory UI | `3100` |

The UI container must be configurable with the backend API endpoint used by the
browser. The local default must point to `http://localhost:8081/factory/deployments`.
When the UI is opened from a non-localhost browser host, and no explicit backend
URL is configured, the UI must default the backend API endpoint to the current
browser hostname on port `8081`.

## Guided Region And Model Choices

The first implementation must use guided listbox controls for region and model
selection to avoid free-text errors.

Supported regions are:

| Region | OCIR region key |
| --- | --- |
| `eu-frankfurt-1` | `fra` |
| `us-chicago-1` | `ord` |

OCI control plane and runtime environment configuration must use the selected
region identifier, such as `eu-frankfurt-1`. OCI Container Registry image
references and Docker login commands must use the lower-case region key, such
as `fra.ocir.io` or `ord.ocir.io`.

Supported model IDs are:

| Display label | Model ID |
| --- | --- |
| GPT-5.4 | `openai.gpt-5.4` |
| Gemini 2.5 Pro | `google.gemini-2.5-pro` |
| OpenAI gpt-oss-120b | `openai.gpt-oss-120b` |

## Backend Responsibilities

The Agent Factory backend must provide an API for:

- Validating deployment input.
- Starting an Agent Factory deployment run.
- Returning deployment run status.
- Returning step-level progress and errors.
- Returning final resource identifiers and endpoint information.

The backend must orchestrate OCI operations in a deterministic sequence.

The backend must use the implementation mechanisms defined in
[Implementation Mechanisms](#implementation-mechanisms). OCI credentials and
signing configuration must be available only to the backend.

The backend must treat the submitted OpenAI-compatible API key as a secret.

The backend must not log:

- Full API key values.
- Full JWT confidential application secrets.
- Docker registry passwords or auth tokens.
- Complete OCI signing private key material.

The backend may log resource names, OCIDs, step names, status values, and
sanitized error summaries.

## Implementation Mechanisms

Agent Factory must use explicit mechanisms for each class of deployment action.

| Action | Required mechanism |
| --- | --- |
| Object Storage bucket creation and lookup | OCI Python SDK. |
| Vector Store creation and lookup | OCI Enterprise AI Vector Store control plane API. |
| Data Sync Connector creation and lookup | OCI Generative AI Python SDK control plane client. |
| RAG agent backend Docker image build | Docker CLI. |
| OCI Container Registry repository creation or lookup | OCI CLI unless later OCI SDK support is explicitly specified. |
| OCI Container Registry authentication | Docker CLI using an OCI-compatible registry login flow. |
| OCI Container Registry image push | Docker CLI. |
| OCI Enterprise AI Hosted Application creation | OCI CLI Hosted Application commands. |
| OCI Enterprise AI Hosted Application deployment creation | OCI CLI Hosted Application deployment commands. |
| Hosted Application deployment status polling | OCI CLI Hosted Application deployment commands. |

The backend must wrap Docker CLI and OCI CLI calls behind small internal helper
interfaces so command construction, argument validation, timeout handling, and
output parsing remain testable.

The backend must not build shell commands by concatenating untrusted strings.
Command arguments must be passed as structured argument lists to the process
runner.

The backend must capture command exit codes, standard output, and standard error
for diagnostics, but returned status payloads and logs must redact secrets.

Vector Store creation must use an OpenAI-compatible control plane client signed
with OCI authentication. The backend must construct the client with
`openai.OpenAI`, `httpx.Client`, and the `oci_genai_auth` authentication helpers.
The control plane endpoint must use this shape:

```text
https://generativeai.<region>.oci.oraclecloud.com/20231130/openai/v1
```

The client must set `api_key` to a non-empty placeholder value, attach the
`opc-compartment-id` header to the HTTP client, and select authentication from
`OCI_AUTH_MODE`. Supported values are `user_principal` and `session`, with
`user_principal` as the default.

The Vector Store create operation must call `client.vector_stores.create(...)`
with a resource name and may include description, expiration, and metadata. This
matches the OpenAI-compatible Vector Store API shape used by OCI Enterprise AI
and the shared `agent_hub/common/clients.py` example.

Object Storage bucket creation and lookup must use `oci.object_storage`
clients. The backend must resolve the Object Storage namespace before bucket
lookup or creation.
After creating an Object Storage bucket, the backend must poll the bucket with
`get_bucket` until it is readable and no longer reports a transitional
lifecycle state before starting dependent resources.

Live resource provisioning must resolve a submitted compartment name to an OCID
with the OCI Identity API before creating or reusing Object Storage buckets,
Vector Stores, or Data Sync Connectors. If multiple visible compartments share
the submitted name, the backend must fail with an actionable error and ask for a
compartment OCID.

Data Sync Connector creation must use the OCI Generative AI Python SDK control
plane client. The backend must construct `CreateVectorStoreConnectorDetails`
with the resolved compartment OCID, Vector Store OCID, connector display name,
and an `OciObjectStorageConfiguration` containing the resolved Object Storage
namespace and bucket name. The first implementation must create an hourly
enabled interval schedule and start it shortly after connector creation. This
matches the shared `agent_hub/connectors/create_connector.py` example.
The Data Sync Connector creation step must not start until both the Object
Storage bucket and the Vector Store have been created or resolved and, for new
resources, have been confirmed readable and outside known transitional states.
After calling `create_vector_store_connector`, the backend must verify the
connector exists through `get_vector_store_connector` when an OCID is returned,
or by listing connectors by display name. The connector step must not be marked
succeeded until that verification succeeds.

## UI Responsibilities

The Agent Factory UI must be implemented as a Next.js application.

The UI must provide a guided form and progress view for the deployment workflow.

The first implementation must prioritize an operational console layout rather
than a marketing page. The initial screen must be the deployment workflow itself.

The UI must allow users to:

- Enter deployment inputs.
- Choose whether to create or reuse optional resources.
- Review the planned actions before starting the deployment.
- Start the deployment run.
- Watch step-by-step progress.
- Receive live step updates while a non-dry-run deployment is still running,
  without waiting for the full workflow to finish.
- See created or reused resource identifiers.
- See the final Hosted Application deployment endpoint.
- See actionable error messages when a step fails.

The UI must disable workflow submission while required inputs are invalid.

The UI must display secret fields as password inputs and must not reveal secrets
after submission.

Dry-run results must perform all safe read-only checks available before returning
the generated command plan and Hosted Application JSON artifacts. At minimum,
dry-run must resolve compartment names, resolve GenAI project names inside the
resolved compartment through the OCI SDK `list_generative_ai_projects` API,
resolve the Object Storage namespace, validate reused resources, and check for
existing resources when create mode can reuse or would conflict. Dry-run must
also validate the submitted OCIR username and password by attempting Docker login
against the target OCIR registry using temporary Docker configuration. Dry-run
must not create, update, push, or delete OCI resources.

When the user supplies a name for a resource that is later required as an OCID,
the backend must include an explicit resolution step and all downstream commands
and generated JSON artifacts must use the resolved OCID. Dry-run output may use a
clear placeholder such as `<resolved-compartment-ocid>`,
`<resolved-genai-project-ocid>`, or
`<resolved-namespace>`, or `<created-or-resolved-vector-store-ocid>` for values
that cannot be known until live OCI creation.

## Deployment Inputs

Agent Factory must collect the following inputs.

| Field | Required | Behavior |
| --- | --- | --- |
| Compartment name or OCID | Yes | Identifies the compartment where resources are created or looked up. If a name is provided, the backend must resolve it to an OCID before running deployment actions. |
| Region | Yes | OCI region where all resources are created or reused. Must be selected from the supported region list. |
| Object Storage bucket mode | Yes | Either `create` or `reuse`. |
| Object Storage bucket name | Yes | Bucket to create or reuse for source documents. |
| Vector Store mode | Yes | Either `create` or `reuse`. |
| Vector Store name or OCID | Yes | Vector Store to create or reuse. If a name is provided for reuse, the backend must resolve it to an OCI Vector Store identifier before deploying the agent. |
| Data Sync Connector mode | Yes | Either `create`, `reuse`, or `skip`. |
| Data Sync Connector name or identifier | Conditional | Required when connector mode is `create` or `reuse`. |
| Hosted Application name | Yes | Name for the OCI Enterprise AI Hosted Application. |
| Hosted Application deployment name | Yes | Name for the deployment created inside the Hosted Application. |
| JWT protection enabled | Yes | Must be fixed to `false` in the first implementation. |
| Confidential application | No | Reserved for future JWT support. Must be disabled in the first implementation. |
| Endpoint visibility | Yes | Must be `public` in the first implementation. |
| Network mode | Yes | Must be `oracle_managed` in the first implementation. |
| Custom network | No | Reserved for future private/custom networking support. |
| GenAI project name or OCID | Yes | OCI Enterprise AI project used by the deployed RAG agent. If a name is provided, the backend must resolve it inside the resolved compartment before setting `OCI_PROJECT_ID`. |
| Model ID | Yes | Model identifier used by the deployed RAG agent. Must be selected from the supported model list. |
| OpenAI-compatible API key | Yes | API key used by the deployed RAG agent to call OCI Enterprise AI. |
| File search max results | No | Optional runtime tuning value for `FILE_SEARCH_MAX_NUM_RESULTS`. |
| Responses timeout seconds | No | Optional runtime tuning value for `RESPONSES_TIMEOUT_SECONDS`. |
| Stream finalization mode | No | Optional runtime tuning value for `STREAM_FINALIZATION_MODE`; default is `never`. |
| Container repository name | Yes | OCI Container Registry repository where the agent backend image is pushed. |
| Container image tag | Yes | Non-floating image tag used for the deployment. |
| OCIR username | Yes | Username used by Docker login before pushing the agent backend image. |
| OCIR password | Yes | Password or auth token used by Docker login before pushing the agent backend image. Must be treated as a secret. |

The first implementation must not allow users to select:

- `JWT protection enabled=true`.
- `Endpoint visibility=private`.
- `Network mode=custom`.

These controls may be visible as disabled fields if the UI clearly marks them as
not available in the first implementation.

## Resource Modes

For resources that support creation or reuse, the UI and backend must handle
both paths explicitly.

When the mode is `create`, the backend must:

- Validate that the requested name is syntactically valid.
- Check whether a conflicting resource already exists when OCI APIs allow that
  check.
- Create the resource when no blocking conflict exists.
- Store the created resource identifier in the deployment run state.

When the mode is `reuse`, the backend must:

- Resolve the provided name or OCID.
- Validate that the resource exists.
- Validate that the resource is in the requested region and compartment when
  OCI APIs expose that information.
- Store the resolved resource identifier in the deployment run state.

When Data Sync Connector mode is `skip`, the backend must not create or resolve
a connector. The final RAG agent deployment must still be allowed when an
existing Vector Store is supplied.

## Workflow Sequence

Agent Factory must run the deployment workflow in the following order.

1. Validate all submitted inputs.
2. Resolve the target compartment.
3. Validate region and resolve the GenAI project input.
4. Create or reuse the Object Storage bucket.
5. Wait for the Object Storage bucket to be readable and non-transitional when
   it was created by this run.
6. Create or reuse the Vector Store.
7. Wait for the Vector Store to be readable and non-transitional when it was
   created by this run.
8. Create, reuse, or skip the Data Sync Connector.
9. Build the RAG agent backend container image with Docker CLI.
10. Create or reuse the OCI Container Registry repository.
11. Authenticate Docker to OCI Container Registry using the submitted OCIR
    username and password. Dry-run must validate these credentials without
    writing to the user's default Docker configuration.
12. Push the RAG agent backend image to OCI Container Registry with Docker CLI.
13. Create the OCI Enterprise AI Hosted Application with OCI CLI.
14. Create the deployment inside the Hosted Application with OCI CLI.
15. Configure deployment runtime environment variables.
16. Wait for deployment activation or readiness with OCI CLI.
17. Validate the deployed `GET /health` endpoint when reachable.
18. Return final deployment outputs.

The backend must stop the sequence on the first unrecoverable failure.
Non-dry-run deployments must not mark planned Docker, OCIR, or Hosted
Application commands as succeeded unless those commands were actually executed
successfully.

The backend must persist or retain enough run state to show which steps
completed before a failure.
For non-dry-run deployments, the backend must return an initial running
deployment run promptly, continue provisioning work after the response, and
update the stored run state as each step transitions to running, succeeded,
failed, or skipped. The UI must poll the deployment status endpoint while the run
is active and render step updates progressively.

## RAG Agent Image

Agent Factory must deploy only the RAG agent backend image.

The Next.js reference chatbot UI must not be included in the Hosted Application
deployment created by Agent Factory.

The backend image must be built from the repository root `Dockerfile` by the
Docker CLI.

The first implementation must create the image during the Agent Factory workflow.
Using a prebuilt image is out of scope for the first implementation unless a
later specification revision adds that option.

The image intended for OCI Enterprise AI Hosted Application deployment must use
the `linux/amd64` platform.

The image tag must be non-floating. Values such as `latest` must be rejected or
require an explicit override in a later implementation.

The Docker build command must tag the image with the final OCI Container
Registry image reference before push.

The Docker push command must push the final OCI Container Registry image
reference.

The pushed image reference must be stored in the deployment run outputs.

## Deployed Agent Runtime Environment

The Hosted Application deployment must configure the RAG agent backend with the
runtime environment variables required by the agent.

At minimum, Agent Factory must set:

| Variable | Source |
| --- | --- |
| `OCI_REGION` | Submitted region. |
| `OCI_COMPARTMENT_ID` | Resolved compartment OCID. |
| `OCI_PROJECT_ID` | Resolved GenAI project OCID. |
| `OCI_MODEL_ID` | Submitted model ID. |
| `OCI_VECTOR_STORE_ID` | Created or resolved Vector Store identifier. |
| `OPENAI_API_KEY` | Submitted API key. |
| `FILE_SEARCH_MAX_NUM_RESULTS` | Submitted optional tuning value or agent default. |
| `RESPONSES_TIMEOUT_SECONDS` | Submitted optional tuning value or agent default. |
| `STREAM_FINALIZATION_MODE` | Submitted optional tuning value or `never`. |

Secrets must be configured using the most protected mechanism available for the
target Hosted Application runtime. If the first implementation can only set
plain runtime variables, the UI and documentation must clearly identify that
limitation.

## Hosted Application Requirements

Agent Factory must create an OCI Enterprise AI Hosted Application using the
selected region, compartment, and Hosted Application name.

Hosted Application creation must be performed through OCI CLI commands.

Hosted Application deployment creation and status polling must be performed
through OCI CLI commands.

The first implementation must create only public endpoint deployments.

The first implementation must use Oracle-managed networking.

The first implementation must not enable JWT protection.

The first implementation must not configure a confidential application.

The first implementation must not configure private endpoint networking or
custom VCN/subnet resources.

## Deployment Run State

The backend must model a deployment run as an ordered set of steps.

Each step must expose:

- Step identifier.
- Display name.
- Status.
- Start time when available.
- End time when available.
- Resource identifiers produced by the step when available.
- Sanitized error message when the step fails.

Supported statuses must include:

- `pending`
- `running`
- `succeeded`
- `failed`
- `skipped`

The UI must render the run status from backend state rather than inventing
client-side status.

## API Contract

The Agent Factory backend must expose at least:

```http
POST /factory/deployments
```

Starts a new deployment run.

```http
GET /factory/deployments/{deployment_run_id}
```

Returns the current state of a deployment run.

```http
GET /factory/health
```

Returns backend health.

The first implementation may run the workflow synchronously if deployment times
are acceptable for local validation, but the API contract must be compatible with
asynchronous execution. The `POST /factory/deployments` response must return a
deployment run identifier.

## Validation Requirements

The backend must validate:

- Required fields.
- Region format.
- OCID format for fields that require OCIDs.
- Resource names.
- Mutually exclusive create/reuse options.
- Disabled first-version options, including JWT, private endpoint, and custom
  networking.
- Runtime tuning values.
- Non-floating container image tag.

Validation failures must occur before OCI resources are created.

Validation errors must be returned as structured responses that the UI can map
to form fields or global workflow errors.

## Error Handling

The backend must make errors predictable and actionable.

When a step fails, the backend must:

- Mark the current step as `failed`.
- Preserve previously completed step outputs.
- Stop later steps.
- Return a sanitized error message.
- Avoid logging secrets.

The UI must show:

- The failed step.
- The sanitized error message.
- Which previous steps succeeded.

The first implementation does not need automatic rollback. If rollback is not
implemented, the UI must clearly show which resources may have been created
before failure.

## Idempotency And Re-Runs

The first implementation should avoid accidental duplicate resources.

For create-mode resources, the backend should check for existing resources with
the requested name before creation when OCI APIs support the lookup.

If a duplicate resource exists, the backend should fail with a clear message or
allow the user to switch that resource to reuse mode.

Deployment runs must have unique identifiers.

The same input submitted twice may create duplicate Hosted Applications or
deployments unless the backend detects conflicts. This limitation must be
documented if not fully prevented in the first implementation.

## Security Requirements

Agent Factory handles control plane operations and secrets.

The backend must be the only component allowed to use OCI credentials.

The UI must never receive OCI signing credentials.

For local Docker Compose runs, the Agent Factory API container must receive the
OCI SDK configuration through a read-only mount of the user's `.oci` directory.
The container must support `OCI_CONFIG_FILE`, `OCI_PROFILE`, and `OCI_AUTH_MODE`
so local tests can select the intended OCI profile and authentication mode.
The Agent Factory API container must also have Docker CLI, OCI CLI, and access
to the host Docker daemon through `/var/run/docker.sock` for local dry-run OCIR
credential validation, live image build/push operations, and live Hosted
Application operations.

The API key field must be treated as a secret.

Secrets must not be written to ordinary logs.

Secrets must not be returned from status APIs.

JWT protection for the deployed Hosted Application is out of scope for the first
implementation and must be fixed to disabled.

Private networking is out of scope for the first implementation and must be
fixed to public endpoint plus Oracle-managed networking.

## Test Strategy

Unit tests must cover:

- Request validation for required fields.
- Rejection of unsupported first-version options.
- Create/reuse/skip resource mode validation.
- Selection of the required implementation mechanism for each workflow step.
- Docker CLI command argument construction for build and push.
- OCI CLI command argument construction for Hosted Application and deployment
  operations.
- Runtime environment variable construction for the deployed agent.
- Workflow step ordering.
- Stop-on-failure behavior.
- Secret redaction in returned status payloads.
- Successful run state transitions with mocked OCI operations.
- Failed run state transitions with mocked OCI operation failures.
- UI form validation for required and disabled fields.

Integration tests may use mocked OCI clients in the first implementation.

Live OCI integration tests must not be required for the default test suite.

## Acceptance Criteria

- Agent Factory has a backend service with deployment-run APIs.
- Agent Factory has a Next.js UI for guided deployment.
- The UI collects all required first-version inputs.
- Region and model are selected through guided controls, and the backend rejects
  unsupported values.
- Dry-run responses include the generated OCI CLI command plan and Hosted
  Application JSON artifacts for auth, networking, environment variables, and
  active Docker artifact configuration.
- JWT protection is fixed to disabled in the first implementation.
- Endpoint visibility is fixed to public in the first implementation.
- Network mode is fixed to Oracle-managed in the first implementation.
- The backend validates deployment inputs before creating OCI resources.
- The backend resolves compartment and Vector Store names before passing those
  values to downstream commands or Hosted Application environment variables that
  require OCIDs.
- The backend can create or reuse an Object Storage bucket.
- The backend uses the OCI Python SDK for Object Storage bucket operations.
- The backend can create or reuse a Vector Store through the Vector Store
  control plane API.
- The backend can create, reuse, or skip a Data Sync Connector through the
  Vector Store control plane API.
- The backend builds the RAG agent backend image with Docker CLI.
- The backend publishes the RAG agent backend image to OCI Container Registry
  with Docker CLI.
- OCI Container Registry commands and image references use the selected region's
  OCIR region key rather than the full region identifier.
- The backend creates an OCI Enterprise AI Hosted Application with OCI CLI.
- The backend creates a deployment inside the Hosted Application with OCI CLI.
- The deployed agent receives the selected Vector Store identifier through
  `OCI_VECTOR_STORE_ID`.
- The deployed agent receives the resolved GenAI project OCID and submitted API
  key.
- The UI displays step-by-step progress and final outputs.
- The backend does not return secrets in deployment status responses.
- Unit tests cover validation, workflow ordering, status transitions, and
  runtime environment construction.

## Open Topics

- Exact OCI SDK resource models for Vector Store and Data Sync Connector
  creation.
- Exact Vector Store control plane API endpoints and payloads.
- Exact OCI CLI commands and payload files for Hosted Application and deployment
  creation.
- OCI Container Registry repository management command details.
- Best protected secret storage mechanism for Hosted Application runtime
  environment variables.
- Rollback or cleanup behavior after partial failures.
- JWT confidential application support.
- Private endpoint and custom networking support.
