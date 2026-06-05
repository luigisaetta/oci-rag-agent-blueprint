# Deployment

## Purpose

This specification defines the initial deployment requirements for the OCI RAG Agent Blueprint.

The project must support two deployment modes:

1. Local deployment for development and testing, based on Docker Compose.
2. Hosted deployment in OCI Enterprise AI.

## Scope

This document covers the deployment structure and minimum requirements for packaging, configuration, startup, and health validation.

This document does not define the complete security model, OCI IAM application setup, OCI networking, or hosted deployment automation details. Those topics will be covered by dedicated specifications or later revisions.

## Related Specifications

- [Architecture Guidelines](0001-architecture-guidelines.md)
- [Agent Implementation](0003-agent-implementation.md)
- [Reference UI](0006-reference-ui.md)

## Local Deployment With Docker Compose

Local deployment must be based on Docker Compose and must support development and local testing of the RAG agent.

The local deployment must run the agent backend as a containerized FastAPI service.

The local deployment must also run the reference UI as a containerized Next.js service.

The Docker image must be built from `Dockerfile` in the repository root.

The image must use a Python 3.11 runtime base image.

Runtime Python dependencies must be installed from `requirements.txt`.

The container must start the agent with `uvicorn` using the package path defined in the agent implementation specification:

```bash
uvicorn agent.main:app --host 0.0.0.0 --port 8080
```

The agent container must expose the agent on port `8080`.

The reference UI container must expose the UI on port `3000`.

The Docker Compose service name must be `rag-agent`.

The Docker Compose service name for the reference UI must be `rag-ui`.

The local image name must be `oci-rag-agent-blueprint-agent`.

The Docker Compose configuration must load runtime configuration from a `.env` file located in the repository root.

The `.env` file must not be committed to version control. The repository must provide a tracked `.env.sample` file documenting the required variables.

The local deployment must pass at least the following environment variables to the agent container:

| Variable | Description |
| --- | --- |
| `OCI_REGION` | OCI region used to build the OCI Enterprise AI endpoint. |
| `OCI_COMPARTMENT_ID` | OCI compartment identifier used by the deployment and API calls. |
| `OCI_PROJECT_ID` | OCI Enterprise AI project identifier passed to the OpenAI-compatible client. |
| `OCI_MODEL_ID` | Model identifier selected from the supported OCI Enterprise AI model catalog. |
| `OCI_VECTOR_STORE_ID` | Vector store identifier used by the Responses API file search tool. |
| `OPENAI_API_KEY` | OpenAI-compatible API key used by the `openai` client to authenticate to OCI Enterprise AI. |

The local deployment must expose the health endpoint:

```http
GET /health
```

The health endpoint must be usable to verify that the agent container is alive and ready to serve requests.

Docker Compose must define a health check for the `rag-agent` service using `GET /health`.

The local deployment must support both non-streaming and streaming requests to:

```http
POST /responses
```

Streaming requests must use the `stream=true` request field defined in the agent request schema.

The local deployment must expose the reference UI at:

```http
GET http://localhost:3000
```

The reference UI must be able to call the local backend at:

```text
http://localhost:8080/responses
```

### Local Deployment Acceptance Criteria

- A Docker image can be built for the agent backend.
- Docker Compose can start the agent service locally.
- Docker Compose reads configuration from the root `.env` file.
- Docker Compose defines the `rag-agent` service.
- Docker Compose defines the `rag-ui` service.
- Docker Compose builds the `oci-rag-agent-blueprint-agent` image.
- Docker Compose builds the `oci-rag-agent-blueprint-ui` image.
- The agent service listens on port `8080`.
- The UI service listens on port `3000`.
- `GET /health` returns a successful JSON response.
- `POST /responses` can be sent to the local service.
- `POST /responses` supports streaming when `stream=true`.
- The UI can send streaming requests to the local backend from a browser.
- Secrets are read from environment variables and are not hardcoded in Docker files or source code.

## Hosted Deployment In OCI Enterprise AI

Hosted deployment must deploy the RAG agent as a containerized application in OCI Enterprise AI.

The hosted deployment must use the same agent container image and runtime contract used by local deployment whenever possible.

Hosted deployment configuration must provide the required environment variables through OCI Enterprise AI deployment configuration or an equivalent managed configuration mechanism.

The hosted deployment must expose the agent through a protected HTTPS endpoint.

The hosted deployment must support:

- The health endpoint.
- The JSON request and response contract.
- Token streaming for `stream=true` requests.
- Access to the configured OCI Vector Store through Responses API file search.
- OpenAI-compatible API key authentication for OCI Enterprise AI Responses API calls.

Security details, including OCI IAM confidential application setup, JWT validation, and authorization behavior, will be defined in a dedicated security specification.

### Hosted Deployment Acceptance Criteria

- The agent can be deployed as a container in OCI Enterprise AI.
- Required runtime configuration is supplied through managed deployment configuration.
- The hosted endpoint is exposed over HTTPS.
- The hosted endpoint can serve `GET /health`.
- The hosted endpoint can serve `POST /responses`.
- The hosted endpoint supports streaming when `stream=true`.
- The deployment does not hardcode secrets.

## Open Topics

The following topics require dedicated specifications or later revisions:

- Local deployment scripts.
- Hosted deployment scripts.
- OCI Enterprise AI hosted deployment procedure.
- Security and JWT validation.
- Hosted deployment of the reference UI.
