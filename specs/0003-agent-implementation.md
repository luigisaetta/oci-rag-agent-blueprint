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
- [Security](0007-security.md)

## Runtime Model

The agent must be packaged as a FastAPI API.

The default HTTP port must be `8080`.

The agent must be started with `uvicorn`.

The default local start command should be:

```bash
uvicorn agent.main:app --host 0.0.0.0 --port 8080
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

Outgoing non-streaming response payloads must be validated against a JSON Schema provided by the project before they are returned to the client.

The implementation must use the `jsonschema` Python package for request and response JSON Schema validation instead of hand-rolled schema parsing logic.

The request schema is defined in [Agent Request Schema](../schemas/agent-request.schema.json).

The response schema is defined in [Agent Response Schema](../schemas/agent-response.schema.json).

The initial request payload must include:

- The user input message.
- Conversation control fields.
- Optional `user_id` and `user_role` fields reserved for future authentication, authorization, auditing, and personalization use cases.
- Optional `stream` field. When omitted or `false`, the agent returns a standard JSON response. When `true`, the agent streams response tokens.

The conversation control fields must follow the [Short-Term Memory](0002-short-term-memory.md) specification:

- `new_conversation=true` starts a new conversation.
- `new_conversation=false` attaches the request to an existing conversation.
- `conversation_id` is required when `new_conversation=false`.

The response payload must include:

- The generated answer.
- The active `conversation_id`.
- The response identifier returned by the Responses API, when available.
- A list of references containing source file name, page, and metadata.
- Token usage reported by the Responses API, when available.
- Structured error information when the request fails.

The JSON request and response schemas must be treated as implementation contracts.

## Streaming Output

The agent must support token streaming for the response.

Streaming is controlled by the optional `stream` field in [Agent Request Schema](../schemas/agent-request.schema.json).

When `stream` is omitted or `false`, `POST /responses` must return the standard JSON response defined by [Agent Response Schema](../schemas/agent-response.schema.json).

When `stream=true`, `POST /responses` must return a `text/event-stream` response using Server-Sent Events.

The streaming MVP must emit:

- A `metadata` event containing the active `conversation_id`.
- One or more `token` events containing generated final-answer text deltas.
- A `references` event containing normalized file search references, when available.
- A `usage` event containing token usage, when available.
- A final `done` event when streaming completes.
- An `error` event when the Responses API fails during streaming.

The agent must forward only Responses API stream events with type
`response.output_text.delta` as client-visible `token` events.

The agent must ignore stream deltas that are not final answer text, including
reasoning, reasoning summaries, tool-call arguments, file-search status, and
other operational events.

Streaming errors must not include secrets or complete request payloads.

If the OpenAI SDK stream parser fails after one or more token events have already
been emitted, the agent should log the parser failure and close the client stream
with a `done` event instead of appending a user-visible parser error to a partially
delivered answer. Parser failures that happen before any token is emitted must
still be returned as `error` events.

Streaming mode must still validate the JSON request payload and required environment variables before creating the stream.

When references are available, the `references` event must be emitted after token
events and before the final `done` event.

When token usage is available, the `usage` event must be emitted after token
events and before the final `done` event. The `usage` event may be emitted before
or after the `references` event.

## Request Handling Flow

For each `POST /responses` request, the agent must:

1. Parse the incoming JSON payload.
2. Validate the payload against the configured JSON Schema.
3. Determine whether the request starts a new conversation or attaches to an existing one.
4. Create an OpenAI-compatible client for the OCI Enterprise AI Responses API.
5. Create a new conversation with `client.conversations.create` when `new_conversation=true`.
6. Attach the Responses API request to the provided conversation when `new_conversation=false`.
7. Create a response by using the configured model.
8. Configure file search as a Responses API tool.
9. Scope file search to the configured OCI Vector Store.
10. Extract normalized references from Responses API file search results when available.
11. Extract token usage from the Responses API response when available.
12. Return a structured JSON response to the client.

Validation failures must stop the flow before any Responses API call is made.

## OpenAI Library Usage

The agent must use the `openai` Python library to call the OCI Enterprise AI OpenAI-compatible Responses API.

The agent must create a client configured for the OCI Enterprise AI endpoint derived from runtime configuration.

The base URL for the OpenAI-compatible client must be built from `OCI_REGION` using this rule:

```python
BASE_URL = (
    f"https://inference.generativeai.{REGION}.oci.oraclecloud.com/openai/v1"
)
```

The `openai` client must authenticate with an OpenAI-compatible API key provided through an environment variable.

The `openai` client must also pass the configured compartment identifier through
the OCI Enterprise AI OpenAI-compatible extension:

```python
client = OpenAI(
    api_key=OPENAI_API_KEY,
    base_url=BASE_URL,
    project=OCI_PROJECT_ID,
    default_headers={
        "extra_body": json.dumps({"compartmentId": OCI_COMPARTMENT_ID})
    },
)
```

The agent must use the Responses API to:

- Create a conversation with `client.conversations.create` when the request starts a new conversation.
- Attach to an existing conversation by passing the conversation identifier to `client.responses.create` through the `conversation` parameter.
- Create the model response.
- Pass agent instructions that require direct final answers and forbid exposing
  internal reasoning or tool-selection narration.
- Configure `file_search` as a tool.
- Pass the configured vector store identifier to the file search tool.

Provider-specific extensions must be isolated and documented if they become necessary.

The MVP implementation must use the following Responses API call shape:

```python
response = client.responses.create(
    model=OCI_MODEL_ID,
    instructions=AGENT_INSTRUCTIONS,
    input=user_request,
    conversation=conversation_id,
    tools=[
        {
            "type": "file_search",
            "vector_store_ids": [OCI_VECTOR_STORE_ID],
        }
    ],
    timeout=60,
)
```

When streaming is requested, the MVP implementation must use the same call shape with `stream=True`:

```python
stream = client.responses.create(
    model=OCI_MODEL_ID,
    instructions=AGENT_INSTRUCTIONS,
    input=user_request,
    conversation=conversation_id,
    tools=[
        {
            "type": "file_search",
            "vector_store_ids": [OCI_VECTOR_STORE_ID],
        }
    ],
    timeout=60,
    stream=True,
)
```

The agent must use only the Responses API surface exposed by the `openai` Python
library. The implementation must not bypass the SDK with a custom raw HTTP client
for Responses API calls.

When `new_conversation=true`, the agent must first create a conversation:

```python
conversation = client.conversations.create()
conversation_id = conversation.id
```

When `new_conversation=false`, the agent must use the `conversation_id` provided by the validated request payload.

The implementation must extract references from Responses API output text
annotations when file citation annotations are available. When annotations are
not available, it must fall back to file search results included through
`include=["file_search_call.results"]`.

For streaming responses, the implementation must capture the `response_id` from
the `response.created` stream event. Because OCI Enterprise AI may not include
complete file search results in streaming events, the agent must retrieve the
completed response with `client.responses.retrieve(response_id,
include=["file_search_call.results"])` before emitting the final `references`
event.

Each reference must follow the response schema:

- `file_name`: Source file name returned by file search.
- `page`: Page number when available, otherwise `null`. When the page is not
  available in file attributes, the implementation may derive it from retrieved
  text patterns such as `Page 44 of 56`.
- `metadata`: Additional retrieval metadata, including available file id, score,
  text excerpt, file attributes, and page number lists when available.

Reference extraction must be defensive. Missing or partially populated file search
results must not fail the whole response.

The implementation must extract token usage from the Responses API `usage`
object when available.

Usage must follow the response schema:

- `input_tokens`: Input tokens consumed by the request, when available.
- `output_tokens`: Output tokens generated by the response, when available.
- `total_tokens`: Total tokens reported by the Responses API, when available.
- `reasoning_tokens`: Reasoning tokens reported by the model/provider, when available.

When token usage is not available, non-streaming responses may return `usage=null`.
For streaming responses, the agent should retrieve the completed response by
`response_id` and emit usage when the retrieved response contains usage data.

## Environment Variables

The agent must receive runtime configuration through environment variables.

The initial required variables are:

| Variable | Description |
| --- | --- |
| `OCI_REGION` | OCI region used to build the OCI Enterprise AI endpoint. |
| `OCI_COMPARTMENT_ID` | OCI compartment identifier used by the deployment and API calls. |
| `OCI_PROJECT_ID` | OCI Enterprise AI project identifier passed to the OpenAI-compatible client. |
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

Error responses must use the `error` field already defined in [Agent Response Schema](../schemas/agent-response.schema.json). For the first implementation, the `error` field is a simple human-readable error message.

Error messages must be deterministic enough to support unit tests.

## Logging

The agent must implement minimal structured logging.

The first implementation must log:

- Agent startup.
- Request validation errors.
- Active `conversation_id` values.
- Responses API `response_id` values, when available.
- Responses API failures.

The health endpoint may log debug-level entries, but it must not create noisy logs during normal operation.

Logs must never include `OPENAI_API_KEY` or other secrets.

Logs must avoid recording complete user requests or full model responses because they may contain sensitive information.

## Timeout And Retry

The MVP implementation must use a default Responses API timeout of `60` seconds.

The MVP implementation must not implement custom application-level retry logic.

If the `openai` client applies default retry behavior, the agent may rely on that behavior without adding another retry layer.

Timeouts and Responses API failures must be returned through the `error` field in the JSON response payload.

## Test Strategy

The MVP implementation must include unit tests with `pytest`.

FastAPI endpoints must be tested with FastAPI `TestClient`.

Tests that exercise Responses API behavior must mock the `openai` client. Unit tests must not call OCI Enterprise AI or any external service.

The MVP test suite must cover:

- `GET /health`.
- JSON Schema validation for valid and invalid requests.
- Missing required environment variables.
- New conversation creation with `client.conversations.create`.
- Existing conversation attachment using `conversation_id`.
- Responses API response creation.
- Streaming Responses API creation.
- Agent instructions passed to Responses API calls.
- Filtering of streaming events so that only final output text is shown to the
  client.
- SDK stream parser failures after partial token delivery.
- Responses API failures.
- Structured JSON error responses.

Test coverage must follow the project rule defined in [AGENTS.md](../AGENTS.md), with a target above 80%.

## Acceptance Criteria

- The agent is implemented as a FastAPI application.
- The default runtime port is `8080`.
- The agent can be started with `uvicorn`.
- `GET /health` returns a JSON health response.
- `POST /responses` accepts JSON input and returns JSON output.
- `POST /responses` supports `stream=true` and returns `text/event-stream`.
- The request payload is validated against [Agent Request Schema](../schemas/agent-request.schema.json) before processing.
- Successful responses conform to [Agent Response Schema](../schemas/agent-response.schema.json).
- Invalid payloads are rejected before any Responses API call.
- The request can start a new conversation.
- The request can attach to an existing conversation by `conversation_id`.
- The agent uses the `openai` Python library.
- The agent creates a Responses API client configured for OCI Enterprise AI.
- The agent creates Responses API responses using `file_search`.
- The agent creates streaming Responses API responses with `stream=True` when requested.
- The agent passes behavior instructions to Responses API calls.
- The agent forwards only `response.output_text.delta` stream events to clients
  as response tokens.
- The agent emits a `usage` stream event when token usage is available.
- The agent passes `OCI_VECTOR_STORE_ID` to the file search configuration.
- The agent passes `OCI_PROJECT_ID` to the OpenAI-compatible client as the project identifier.
- The agent authenticates the `openai` client with `OPENAI_API_KEY`.
- Required runtime configuration is read from environment variables.
- Docker Compose local deployment reads configuration from a root `.env` file.
- A tracked `.env.sample` file documents the required environment variables.
- The agent logs startup, validation errors, conversation identifiers, response identifiers, and Responses API failures.
- The agent never logs secrets or complete user/model payloads.
- Responses API calls use a default timeout of `60` seconds.
- The MVP implementation does not add custom application-level retries.
- Unit tests use `pytest`, FastAPI `TestClient`, and a mocked `openai` client.
- Unit tests cover health checks, schema validation, environment validation, conversation handling, Responses API calls, and error handling.
