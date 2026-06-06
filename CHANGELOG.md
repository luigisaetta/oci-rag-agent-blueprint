# Changelog

All notable project changes must be recorded in this file.

Entries are grouped by date. New entries should be added under the current date
whenever significant features, fixes, refactorings, specifications, deployment
changes, or documentation updates are introduced.

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
