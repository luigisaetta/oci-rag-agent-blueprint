# Agent Implementation

## Purpose

This specification defines the first implementation requirements for the RAG agent.

The agent must expose a JSON-based API, validate incoming requests, manage conversation creation or attachment, and call the OCI Enterprise AI OpenAI-compatible Responses API using the `openai` Python library.

## Scope

This document covers:

- FastAPI packaging.
- HTTP endpoints.
- JSON input and output behavior.
- Request validation through JSON Schema.
- Conversation handling integration.
- Responses API client creation.
- File search usage against the configured vector store.
- Required environment variables.

This document does not define the complete security model, deployment manifests, Dockerfile, Docker Compose file, or reference UI behavior. Those topics will be covered by dedicated specifications.

## Related Specifications

- [Architecture Guidelines](0001-architecture-guidelines.md)
- [Short-Term Memory](0002-short-term-memory.md)

## Runtime Model

The agent must be packaged as a FastAPI API.

The default HTTP port must be `8080`.

The agent must be started with `uvicorn`.

The default local start command should be:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8080
```

The exact Python package layout may be refined by implementation-specific specifications, but the application must expose a FastAPI `app` object for `uvicorn`.

## HTTP Endpoints

The agent must expose two endpoints.

### Health Endpoint

```http
GET /health
```

The health endpoint must verify that the agent process is alive and able to serve requests.

The endpoint must return a JSON response.

Example response:

```json
{
  "status": "ok"
}
```

### Agent Request Endpoint

```http
POST /responses
```

The request endpoint must accept a JSON payload, validate it, manage conversation state, call the Responses API, and return a JSON response.

The endpoint name may be revisited before implementation if a later API contract specification standardizes a different route.

## JSON Input And Output

The agent must receive input and return output using JSON payloads.

Incoming request payloads must be validated against a JSON Schema provided by the project.

The request schema is defined in [Agent Request Schema](../schemas/agent-request.schema.json).

The response schema is defined in [Agent Response Schema](../schemas/agent-response.schema.json).

The initial request payload must include:

- The user input message.
- Conversation control fields.
- Optional `user_id` and `user_role` fields reserved for future authentication, authorization, auditing, and personalization use cases.

The conversation control fields must follow the [Short-Term Memory](0002-short-term-memory.md) specification:

- `new_conversation=true` starts a new conversation.
- `new_conversation=false` attaches the request to an existing conversation.
- `conversation_id` is required when `new_conversation=false`.

The response payload must include:

- The generated answer.
- The active `conversation_id`.
- The response identifier returned by the Responses API, when available.
- A list of references containing source file name, page, and metadata.
- Structured error information when the request fails.

The JSON request and response schemas must be treated as implementation contracts.

## Request Handling Flow

For each `POST /responses` request, the agent must:

1. Parse the incoming JSON payload.
2. Validate the payload against the configured JSON Schema.
3. Determine whether the request starts a new conversation or attaches to an existing one.
4. Create an OpenAI-compatible client for the OCI Enterprise AI Responses API.
5. Create a new conversation when `new_conversation=true`.
6. Attach the Responses API request to the provided conversation when `new_conversation=false`.
7. Create a response by using the configured model.
8. Configure file search as a Responses API tool.
9. Scope file search to the configured OCI Vector Store.
10. Return a structured JSON response to the client.

Validation failures must stop the flow before any Responses API call is made.

## OpenAI Library Usage

The agent must use the `openai` Python library to call the OCI Enterprise AI OpenAI-compatible Responses API.

The agent must create a client configured for the OCI Enterprise AI endpoint derived from runtime configuration.

The `openai` client must authenticate with an OpenAI-compatible API key provided through an environment variable.

The agent must use the Responses API to:

- Create or attach to a conversation, according to the request.
- Create the model response.
- Configure `file_search` as a tool.
- Pass the configured vector store identifier to the file search tool.

Provider-specific extensions must be isolated and documented if they become necessary.

## Environment Variables

The agent must receive runtime configuration through environment variables.

The initial required variables are:

| Variable | Description |
| --- | --- |
| `OCI_REGION` | OCI region used to build the OCI Enterprise AI endpoint. |
| `OCI_COMPARTMENT_ID` | OCI compartment identifier used by the deployment and API calls. |
| `OCI_MODEL_ID` | Model identifier selected from the supported OCI Enterprise AI model catalog. |
| `OCI_VECTOR_STORE_ID` | Vector store identifier used by the Responses API file search tool. |
| `OPENAI_API_KEY` | OpenAI-compatible API key used by the `openai` client to authenticate to OCI Enterprise AI. |

Environment variable names must be treated as part of the public deployment contract.

Configuration values must not be hardcoded in the application code.

For Docker Compose based local deployment, environment variables must be loaded from a `.env` file located in the repository root.

The `.env` file must not be committed to version control. The repository must provide a tracked `.env.sample` file documenting the required variables.

## Error Handling

The agent must return structured JSON errors for:

- Invalid JSON payloads.
- JSON Schema validation failures.
- Missing or invalid conversation control fields.
- Missing required environment variables.
- Responses API failures.

Error responses must be deterministic enough to support unit tests.

The exact error schema will be defined before implementation.

## Acceptance Criteria

- The agent is implemented as a FastAPI application.
- The default runtime port is `8080`.
- The agent can be started with `uvicorn`.
- `GET /health` returns a JSON health response.
- `POST /responses` accepts JSON input and returns JSON output.
- The request payload is validated against [Agent Request Schema](../schemas/agent-request.schema.json) before processing.
- Successful responses conform to [Agent Response Schema](../schemas/agent-response.schema.json).
- Invalid payloads are rejected before any Responses API call.
- The request can start a new conversation.
- The request can attach to an existing conversation by `conversation_id`.
- The agent uses the `openai` Python library.
- The agent creates a Responses API client configured for OCI Enterprise AI.
- The agent creates Responses API responses using `file_search`.
- The agent passes `OCI_VECTOR_STORE_ID` to the file search configuration.
- The agent authenticates the `openai` client with `OPENAI_API_KEY`.
- Required runtime configuration is read from environment variables.
- Docker Compose local deployment reads configuration from a root `.env` file.
- A tracked `.env.sample` file documents the required environment variables.

## Missing Details To Specify

The following details must be specified before or during implementation:

- Exact JSON error schema.
- How the OCI Enterprise AI endpoint is built from `OCI_REGION`.
- Exact Responses API fields for conversation creation and attachment.
- Timeout, retry, and backoff behavior for Responses API calls.
- Logging and observability requirements.
- Unit test strategy and mocking approach for the `openai` client.
