# Changelog

All notable project changes must be recorded in this file.

Entries are grouped by date. New entries should be added under the current date
whenever significant features, fixes, refactorings, specifications, deployment
changes, or documentation updates are introduced.

## 2026-06-25

- Added a document ingestion CLI for submitting remote agent-managed connector
  ingestion jobs, reading job status, optional polling, multipart uploads, IDCS
  token reuse, documentation, and unit tests.
- Replaced document-specific auth mode with the general `OCI_AUTH_MODE`
  setting, added Resource Principal and config-file authentication for Responses
  API clients through `oci-genai-auth`, and made `OPENAI_API_KEY` required only
  for `openai_api_key` mode.
- Updated environment variable documentation for `OCI_AUTH_MODE`, conditional
  `OPENAI_API_KEY` usage, config-file auth, and Resource Principal IAM
  expectations.
- Updated quickstart, deployment, security, implementation, and roadmap
  documentation to mark Resource Principal Responses API authentication as
  partially implemented at runtime while keeping IAM, Dynamic Group, Agent
  Factory, and hosted validation work explicit.
- Added explicit OCI authentication mode requirements for agent-managed
  connector ingestion, including Resource Principal support for hosted
  server-side Object Storage uploads and connector file sync operations.
- Implemented agent-managed connector ingestion endpoints for submitting
  document uploads through Object Storage and reading Vector Store Data Sync
  Connector job status, with shared ingestion helpers and mocked unit tests.
- Specified agent-managed connector ingestion endpoints for uploading documents
  to Object Storage, triggering asynchronous Vector Store Data Sync Connector
  jobs, and reading connector job status without duplicating ingestion logic in
  the agent.

## 2026-06-24

- Implemented a management document loader script with local file discovery,
  Object Storage uploads, Vector Store connector file sync triggering, dry-run
  support, overwrite handling, documentation, and unit tests.
- Specified a local document loader script that uploads PDF, text, and Markdown
  files to the configured Object Storage bucket and triggers a Vector Store Data
  Sync Connector file sync job.
- Added a numbered roadmap document with a first future improvement proposal for
  replacing OpenAI-compatible API key authentication with OCI Resource Principal
  and Dynamic Group based IAM authorization.
- Fixed the Agent Factory container UI default so remote browsers derive the
  Factory API endpoint from the current UI hostname instead of using
  `localhost`, while preserving explicit `NEXT_PUBLIC_FACTORY_API_URL`
  overrides.
- Specified a protected runtime environment diagnostic endpoint for the RAG
  agent, including non-secret environment reporting, secret-name redaction, JWT
  protection expectations, logging constraints, and unit test coverage.
- Implemented the RAG agent runtime environment diagnostic endpoint with
  reusable secret-name classification, deterministic non-secret reporting, and
  FastAPI unit tests.
- Updated the reference UI sidebar to load protected agent runtime metadata and
  show the active model, document search result limit, region, and streaming
  finalization mode without exposing secrets.
- Fixed Agent Factory live health validation for JWT-protected Hosted
  Applications by acquiring a temporary IDCS client-credentials token and
  sending it as a Bearer token on `/health`.
- Fixed Langfuse parent spans so Responses API traces include observation input
  and output for non-streaming, streaming, and stream-finalization calls.

## 2026-06-23

- Specified optional Langfuse observability for Responses API calls, including
  disabled-by-default runtime configuration, Langfuse client selection,
  conversation-based sessions, span behavior, secret redaction, deployment
  requirements, and unit test expectations.
- Clarified Agent Factory backend and UI requirements for optional Langfuse
  deployment settings, including validation, runtime environment mapping,
  ready-to-run script handling, and secret redaction.
- Implemented optional Langfuse observability for the RAG agent runtime,
  including configuration loading, Langfuse OpenAI client selection, Responses
  API observation spans, conversation-based sessions, dependency updates, and
  environment variable documentation.
- Added Agent Factory backend, ready-to-run script, and UI support for optional
  Langfuse deployment settings with validation and secret redaction.
- Added GPT-5.5 to the Agent Factory supported model list and UI selector.

## 2026-06-22

- Added an Agent Factory ready-to-run deployment script export, keeping dry-run
  behavior read-only while generating a separate Linux-first Bash wrapper that
  keeps Docker commands, OCI CLI commands, and OCI CLI JSON artifacts visible
  for administrator review.
- Added an exported deployment script runner that restores runtime secrets from
  environment variables or prompts and reuses existing foundation provisioning,
  OCI identifier extraction, endpoint derivation, and Hosted Application lookup
  logic.
- Added an Agent Factory UI action for downloading the ready-to-run deployment
  script after a successful dry run.
- Specified the ready-to-run deployment script workflow separately from Agent
  Factory dry-run behavior.

## 2026-06-19

- Added optional JWT authentication support to the reference Next.js UI,
  including server-side IDCS token acquisition, Bearer authorization headers for
  protected `/responses` calls, and a JWT-aware `/health` test action.
- Updated the reference UI specification to define JWT-disabled local defaults,
  IDCS token acquisition, protected Hosted Application request behavior, and
  health-check acceptance criteria.
- Clarified that protected Hosted Application testing requires a configured OCI
  IAM confidential application with Client ID, Client secret, and the OAuth
  client credentials grant, and linked to the official OCI setup documentation.

## 2026-06-18

- Expanded `test_hosted_application.sh` into a full Hosted Application self-test
  covering IDCS token acquisition, JWT diagnostics, `/health`, non-streaming
  `/responses`, and streaming `/responses`.
- Added an optional Hosted Application self-test switch for printing agent
  response text when manual answer inspection is needed.
- Added protected Hosted Application Python CLI examples with `--auth idcs` to
  the main README.
- Updated the main README current status to include IDCS-protected hosted
  applications, authenticated Python CLI requests, Agent Factory token
  validation, and Hosted Application self-tests.
- Added Agent Factory IDCS token validation from the UI, including client
  credentials token acquisition, JWT claim diagnostics, and separate audience
  and scope claim checks.
- Added a root `test_hosted_application.sh` helper script for manual validation
  of protected Hosted Application `/responses` endpoints.
- Added detailed documentation explaining the difference between separated
  Hosted Application IDCS `audience`/`scope` values and concatenated client
  token-request `IDCS_SCOPE` values.
- Fixed Agent Factory IDCS Hosted Application auth rendering so
  `idcsConfig.audience` and `idcsConfig.scope` remain separate JWT claim
  expectations.
- Updated the Python CLI client to send acquired IDCS access tokens as Bearer
  authorization headers when calling protected Hosted Application endpoints.
- Added Python CLI support for requesting and printing an IDCS access token from
  OCI IAM using confidential application credentials loaded from `.env` or the
  process environment.
- Added a standalone IDCS token test client that only contacts OCI IAM, prints
  the access token, and exits without requiring RAG agent request arguments.
- Added JWT header and payload decoding to the standalone IDCS token test client
  so issued token claims can be inspected without decoding the signature.
- Documented the CLI-only IDCS token environment variables in `.env.sample`,
  client documentation, and environment variable reference.
- Added the standalone IDCS token validation step to the quickstart.

## 2026-06-17

- Added a README section that explains practical use cases for the blueprint and
  clarifies what users can build with the project.
- Updated Agent Factory outputs to show the Hosted Application invoke base URL,
  health URL, and `/responses` URL after successful live deployments.
- Fixed Agent Factory connector provisioning so deleted connectors are not reused
  in create mode and are rejected clearly in reuse mode.
- Fixed Agent Factory Hosted Deployment readiness so deployments still in
  transitional states are polled instead of being marked successful immediately.
- Replaced the Agent Factory health validation command with a Python standard
  library check and preserved partial Hosted Application outputs when health
  validation fails.
- Fixed Agent Factory command placeholder replacement so embedded placeholders
  such as `<deployed-health-endpoint>/health` are resolved before execution.
- Added Agent Factory authentication UI controls for confidential application
  linkage.
- Changed Agent Factory bucket, Vector Store, and Data Sync Connector mode
  choices from dropdowns to compact segmented controls.
- Added Agent Factory backend validation and Hosted Application IDCS inbound auth
  artifact generation for authenticated deployments.
- Added Agent Factory UI troubleshooting hints when credential checks or
  deployment submissions fail while the backend endpoint still points to a local
  default URL.
- Added a troubleshooting FAQ entry for Hosted Application `/health` validation
  returning 404 after enabling IDCS authentication.
- Changed Agent Factory IDCS authentication to require the exact Identity Domain
  URL instead of deriving one from an Identity Domain display name.

## 2026-06-09

- Marked version 1.0 as ready after Hosted Deployment validation, with both
  non-streaming and streaming request modes tested successfully.
- Refreshed the main README for the version 1.0 state, highlighting Hosted
  Deployment validation, API usage, Agent Factory, local UI usage, and quality
  checks.
- Added a simple Agent API usage guide covering local and Hosted Application
  endpoints, non-streaming payloads, streaming payloads, and hosted SSE behavior.
- Made the Python CLI streaming parser tolerate hosted gateway responses that
  preserve SSE `data:` frames but strip explicit `event:` names.
- Verified and enabled streaming tests through OCI Hosted Deployments by
  handling the Hosted Application invoke gateway's stripped SSE event names.
- Ported Hosted Deployment streaming compatibility to the Next.js reference UI
  so it can consume gateway-stripped SSE event names and stop on final events.
- Fixed the Python CLI streaming client so it exits immediately after `done` or
  `error` events instead of waiting for hosted gateway connections to close, and
  added agent stream-open and stream-completion diagnostics.
- Added request-scoped diagnostic logging to the RAG agent backend so unhandled
  errors and Responses API failures include request identifiers and failing
  processing phases in server logs.
- Added a root troubleshooting FAQ and documented how to set the Agent Factory
  API URL when the UI is opened against a remote server.
- Aligned Agent Factory Hosted Application and Hosted Deployment OCI CLI actions
  with the working `oci-enterprise-ai-deployer` flow by reusing existing Hosted
  Applications by display name and using the single Docker artifact deployment
  command.
- Added browser-local OCIR credential save, load, and forget controls to the
  Agent Factory sidebar without persisting the selected OCI region.
- Restored OCI CLI wait behavior for Hosted Application and Hosted Deployment
  creation and wait for existing non-active Hosted Applications before creating
  dependent deployments.

## 2026-06-08

- Changed Agent Factory dry runs to perform read-only OCI preflight checks,
  resolving compartment names, GenAI project names, and Object Storage
  namespaces before generating command plans.
- Added explicit OCIR username and password inputs to Agent Factory and changed
  Docker login planning to use those credentials instead of assuming a prior
  local login.
- Added dry-run validation of OCIR Docker credentials using temporary Docker
  configuration so invalid registry credentials fail before deployment.
- Fixed GenAI project name resolution to call the OCI SDK
  `list_generative_ai_projects` method exposed by `GenerativeAiClient`.
- Added Docker CLI to the Agent Factory API container and mounted the host
  Docker socket in the local Compose deployment so dry-run OCIR validation and
  live image build/push operations can run inside the container.
- Installed the `docker-cli` package explicitly because recent Debian images no
  longer provide the `docker` client binary through `docker.io` alone.
- Changed `start_factory.sh --build` to rebuild the API image without cache and
  force-recreate services so runtime tool changes are picked up.
- Added the official OCI Generative AI Hosted Applications and Deployments
  documentation link to the Agent Factory specification.
- Made the Agent Factory Compose project name compatible with Docker Compose v1
  by moving it from the Compose file to the helper script `-p` option.
- Made the Agent Factory Compose scripts portable across Linux and macOS by
  declaring a Compose file version, avoiding default-value interpolation inside
  the Compose file, and supporting both `docker-compose` and `docker compose`.
- Changed the Agent Factory helper scripts to prefer Docker Compose v2
  (`docker compose`) over older `docker-compose` clients.
- Fixed live Agent Factory deployments so Docker, OCIR, and Hosted Application
  steps are executed and failures stop the run instead of marking planned
  commands as completed.
- Mounted the repository root into the Agent Factory API container so live Docker
  builds can use the root RAG agent backend `Dockerfile`.
- Added OCI CLI to the Agent Factory API dependencies so live Hosted Application
  and deployment steps can execute inside the container.
- Changed the Agent Factory UI default backend endpoint to use the browser host
  on port `8081` when the UI is opened from a non-localhost machine.
- Documented how to set the Agent Factory backend endpoint field when the UI is
  opened from a browser on a different machine.
- Added a live deployment guard that fails before Hosted Application creation if
  any required resource identifier still contains a planning placeholder.
- Fixed live Hosted Application and Hosted Deployment identifier extraction so
  OCI CLI work-request responses use the matching resource identifier instead of
  unrelated OCIDs from the same response.
- Treated OCI Vector Store service identifiers such as `vs_fra_...` as resolved
  runtime values so live deployments propagate the real Vector Store identifier
  instead of the planning placeholder.
- Updated Agent Factory to accept a GenAI project name or OCID, resolving names
  inside the selected compartment before setting the deployed agent
  `OCI_PROJECT_ID` runtime environment variable.
- Updated the Agent Factory UI and specification to describe GenAI project
  name-or-OCID input and show the resolved project identifier in run outputs.
- Fixed live Agent Factory registry handling so an existing OCIR repository is
  treated as successful reuse instead of leaving the deployment failed.
- Fixed live Agent Factory failure handling so failed runs cannot leave steps in
  `running` state and the UI always displays the run-level error message.
- Normalized pasted Agent Factory text inputs and disabled browser autofill for
  secret fields so OCIR auth tokens are not submitted with accidental whitespace
  or stale autofilled values.
- Added a direct Agent Factory OCIR credential check action in the sidebar,
  backed by a non-mutating Docker login validation endpoint.
- Removed the confusing `python3 -m json.tool` runtime-environment command from
  Agent Factory plans and made runtime environment generation a commandless
  logical step before Hosted Application creation.
- Removed OCI CLI wait flags from Hosted Application and Hosted Deployment
  create commands, keeping readiness in the dedicated deployment-readiness step
  and allowing the executor to parse OCI JSON output with informational
  prefixes.
- Fixed Hosted Application and Hosted Deployment ID extraction for direct OCI
  resource responses so compartment or parent application OCIDs are not passed
  to dependent deployment commands.

## 2026-06-07

- Added Agent Factory resource managers for creating or reusing Object Storage
  buckets through the OCI Python SDK and Vector Stores through the OCI
  OpenAI-compatible control plane client.
- Integrated bucket and Vector Store provisioning into non-dry-run Agent Factory
  deployment requests, using the resolved Vector Store OCID in the deployed
  agent runtime environment.
- Updated Agent Factory tests to cover mocked bucket creation, Vector Store
  creation, and non-dry-run resource provisioning outputs.
- Documented the concrete Vector Store control plane client and Object Storage
  SDK mechanisms in the Agent Factory specification.
- Aligned Agent Factory control plane client construction with the shared
  `agent_hub/common/clients.py` pattern using `openai.OpenAI`, `httpx`, and
  `oci_genai_auth` authentication helpers.
- Added Agent Factory Data Sync Connector provisioning through the OCI
  Generative AI Python SDK, linking the resolved Object Storage bucket to the
  resolved Vector Store with an hourly enabled sync schedule.
- Fixed live Agent Factory resource provisioning so compartment names are
  resolved through OCI Identity before bucket, Vector Store, and connector
  operations receive a compartment OCID.
- Mounted local OCI SDK configuration into the Agent Factory API container and
  converted missing OCI config/profile failures into managed provisioning errors
  instead of unhandled API exceptions.
- Fixed the Agent Factory control plane client endpoint to use the OCI
  OpenAI-compatible `/20231130/openai/v1` path from the local `agent_hub`
  examples, and kept Vector Store lookup failures visible before create/reuse.
- Added explicit readiness waits after Object Storage bucket and Vector Store
  creation so Data Sync Connector creation starts only after its dependencies
  are readable and outside known transitional states.
- Changed live Agent Factory deployments to return an initial running run,
  execute resource provisioning in the background, update step status as each
  resource phase completes, and poll those updates from the UI.
- Added post-create verification for Data Sync Connectors so the connector step
  is marked succeeded only after the connector can be retrieved or listed.

## 2026-06-06

- Updated the streaming finalization specification to make post-stream retrieve
  behavior configurable with `STREAM_FINALIZATION_MODE`.
- Documented `STREAM_FINALIZATION_MODE=never` as the default, with `auto` and
  `always` available for deployments that prefer more complete final streaming
  metadata over lower end-of-stream latency.
- Implemented `STREAM_FINALIZATION_MODE` in the agent runtime configuration and
  streaming response finalization path.
- Updated streaming tests to cover the default `never` behavior, conditional
  `auto` retrieval, and legacy-compatible `always` retrieval.
- Added the Agent Factory specification for a backend and Next.js UI that guide
  OCI Enterprise AI RAG agent deployment from resource setup through Hosted
  Application deployment.
- Updated the Agent Factory specification with required implementation
  mechanisms for OCI Python SDK, Vector Store control plane APIs, Docker CLI,
  and OCI CLI orchestration steps.
- Added the initial Agent Factory FastAPI backend skeleton, Next.js UI, dry-run
  command generation, command export, and backend validation tests.
- Added a separate Docker Compose deployment for Agent Factory, including API
  and UI container builds plus root-level start and stop scripts.
- Added Agent Factory runtime environment planning for Hosted Application
  deployment creation, covering all environment variables required by the RAG
  agent and redacting secrets in API responses.
- Updated Agent Factory dry-run planning to emit deployer-compatible OCI CLI
  commands and Hosted Application JSON artifacts for auth, networking,
  environment variables, and Docker artifact configuration.
- Fixed Agent Factory command planning so compartment and Vector Store names are
  represented as resolved OCID values before they are passed to downstream OCI
  commands, JSON artifacts, or agent runtime environment variables.
- Changed Agent Factory region and model inputs to guided selections, added
  backend validation for supported choices, and mapped OCI regions to OCIR
  registry keys for Docker image references.

## 2026-06-05

- Created the initial spec-driven project structure and repository guidelines.
- Added architecture, agent implementation, short-term memory, deployment,
  security, UI, and document loading specifications.
- Implemented the FastAPI RAG agent using the OpenAI-compatible Responses API.
- Added Docker Compose based local deployment with backend and Next.js UI.
- Added the Python CLI test client with streaming support.
- Added JSON Schema validation for agent request and response payloads.
- Added reference extraction for Responses API file search results and citation
  annotations.
- Added streaming reference recovery by retrieving the completed Responses API
  response after token streaming.
- Added page number extraction from retrieved result text when OCI does not
  populate page metadata attributes.
- Refactored reference and citation handling into `agent/references.py`.
- Updated the response contract to include token usage information.
- Implemented token usage extraction for non-streaming and streaming agent
  responses.
- Updated the Python CLI test client to display token usage.
- Updated the Next.js UI sidebar to show cumulative input and output token usage
  for the active conversation.
- Added an agent runtime tuning specification for file search result count and
  Responses API timeout configuration.
- Implemented runtime tuning for file search result count and Responses API
  timeout through environment variables.
