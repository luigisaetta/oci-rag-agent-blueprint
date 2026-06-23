# Langfuse Observability

## Purpose

This specification defines optional Langfuse observability for the RAG agent
runtime.

The goal is to improve tracing and operational visibility for Responses API
calls while keeping the default local and hosted deployment behavior unchanged.
Langfuse must be disabled unless explicitly enabled through runtime
configuration.

## Scope

This specification covers:

- Optional Langfuse runtime configuration.
- Langfuse dependency requirements.
- Responses API client selection when observability is enabled.
- Span creation for Responses API calls.
- Langfuse session grouping for conversation-based requests.
- Logging, error handling, and secret handling expectations.
- Deployment and Agent Factory configuration requirements.
- Unit test expectations.

This specification does not cover:

- A Langfuse server deployment.
- Langfuse project provisioning.
- Langfuse dashboard design.
- Client-side UI tracing.
- Tracing for OCI Vector Store control plane operations.
- Tracing for Agent Factory deployment orchestration.

## Related Specifications

- [Architecture Guidelines](0001-architecture-guidelines.md)
- [Short-Term Memory](0002-short-term-memory.md)
- [Agent Implementation](0003-agent-implementation.md)
- [Deployment](0004-deployment.md)
- [Security](0007-security.md)
- [Agent Runtime Tuning](0009-agent-runtime-tuning.md)
- [Agent Factory](0010-agent-factory.md)

## Configuration Model

Langfuse observability must be controlled only by agent runtime environment
variables.

The feature must be disabled by default. Omitting every Langfuse environment
variable must preserve the current standard OpenAI-compatible Responses API
client behavior.

The agent request payload must not accept Langfuse credentials, Langfuse URLs,
or per-request flags that enable or disable tracing.

## Environment Variables

| Variable | Required | Default | Validation | Description |
| --- | --- | --- | --- | --- |
| `LANGFUSE_ENABLED` | No | `false` | Boolean value | Enables Langfuse observability when true. |
| `LANGFUSE_BASE_URL` | Only when `LANGFUSE_ENABLED=true` | None | Non-empty URL string | Base URL of the Langfuse instance. |
| `LANGFUSE_PUBLIC_KEY` | Only when `LANGFUSE_ENABLED=true` | None | Non-empty string | Langfuse public key. |
| `LANGFUSE_SECRET_KEY` | Only when `LANGFUSE_ENABLED=true` | None | Non-empty string | Langfuse secret key. |

Accepted true values for `LANGFUSE_ENABLED` must include `true`, `1`, `yes`,
and `on`, case-insensitively.

Accepted false values for `LANGFUSE_ENABLED` must include `false`, `0`, `no`,
and `off`, case-insensitively.

Invalid boolean values must fail configuration loading before any Responses API
call is made.

When `LANGFUSE_ENABLED` is omitted, empty, or false, the remaining Langfuse
variables must be optional and ignored by the runtime.

When `LANGFUSE_ENABLED=true`, `LANGFUSE_BASE_URL`, `LANGFUSE_PUBLIC_KEY`, and
`LANGFUSE_SECRET_KEY` must all be present. Missing or empty required Langfuse
values must fail configuration loading before any Responses API call is made.

## Dependency Requirements

The Python runtime dependencies must include the Langfuse Python package:

```text
langfuse>=3,<4
```

The dependency must be added to the project dependency files used by local
development, tests, Docker builds, and Hosted Application container builds.

## Client Selection

When Langfuse is disabled, the agent must continue to create the standard
OpenAI-compatible client from the `openai` package:

```python
from openai import OpenAI
```

When Langfuse is enabled, the agent must create the Langfuse-instrumented
OpenAI-compatible client provided by Langfuse:

```python
from langfuse.openai import OpenAI as LangfuseOpenAI
```

Both client paths must use the same OCI Enterprise AI Responses API base URL,
API key, project value, OCI compartment header, model, timeout, and file search
configuration defined by the existing agent specifications.

The Langfuse integration must not change the public `/responses` API contract,
the request schema, the response schema, streaming behavior, reference
extraction, or token usage extraction.

## Trace And Span Behavior

Each Responses API call made by the agent must be observable as a Langfuse span
when Langfuse is enabled.

This includes:

- Non-streaming `client.responses.create` calls.
- Streaming `client.responses.create` calls.
- Streaming finalization `client.responses.retrieve` calls when
  `STREAM_FINALIZATION_MODE` permits a retrieve call.

The implementation must use Langfuse's native OpenAI integration for Responses
API instrumentation. If an explicit parent observation is needed to group or
name the operation predictably, the parent observation must be a span and the
native Responses API generation must be created under that span.

Recommended observation names are:

- `oci-rag-agent-response` for a parent span around a create call.
- `oci-rag-agent-response-finalization` for a parent span around a retrieve
  call.

Span metadata should include safe operational values when available:

- `conversation_id`.
- `response_id`.
- `stream`.
- `model`.
- `file_search_max_num_results`.
- `stream_finalization_mode`.

Span metadata must not include:

- Full user prompts.
- Full model responses.
- API keys.
- Langfuse secret keys.
- Complete environment dumps.
- Authorization headers.

If input or output capture is enabled through Langfuse's native integration,
the implementation must rely on Langfuse configuration for that capture and must
not add a separate project-specific copy of full request or response content to
logs or metadata.

## Conversation Sessions

When a request uses conversation memory, Langfuse observations for that
conversation must be grouped under one Langfuse session.

For `new_conversation=true`, the agent must create the Responses API
conversation first, then use the returned `conversation_id` as the Langfuse
`session_id` for the response creation span.

For `new_conversation=false`, the agent must use the provided `conversation_id`
as the Langfuse `session_id`.

All Langfuse spans generated for the same conversation must use the same
`session_id`.

If the agent ever supports a request mode without conversation memory, the
implementation may omit `session_id` for that request or use a request-scoped
identifier. The current agent behavior is conversation-oriented, so the expected
MVP behavior is to use `conversation_id` as the Langfuse session identifier.

## Error Handling

Langfuse configuration errors must be reported as agent configuration errors
before any Responses API call is made.

Responses API failures must preserve the existing error behavior defined in
[Agent Implementation](0003-agent-implementation.md). Enabling Langfuse must not
replace agent-visible Responses API errors with Langfuse-specific errors.

If Langfuse instrumentation fails after the agent has selected the Langfuse
client, the request should fail with a clear upstream or observability error
only when the Responses API call cannot be completed. The error response must
not expose Langfuse secret values.

When Langfuse is disabled, no Langfuse client import, initialization, network
call, or flush operation should be required for a successful agent request.

## Logging And Secret Handling

Startup logs may record whether Langfuse observability is enabled.

Logs may include:

- `LANGFUSE_ENABLED` effective state.
- Langfuse base URL host or sanitized base URL.
- Conversation identifiers.
- Response identifiers.
- Observability setup failures without secret values.

Logs must not include:

- `LANGFUSE_PUBLIC_KEY`.
- `LANGFUSE_SECRET_KEY`.
- OpenAI-compatible API keys.
- Full Langfuse request headers.
- Full user prompts or full model responses.

## Deployment Requirements

The tracked sample environment documentation must include the Langfuse variables
with safe placeholder values and must show the feature disabled by default.

Local Docker Compose deployment must pass Langfuse environment variables into
the agent container only as optional runtime configuration.

OCI Enterprise AI Hosted Application deployment documentation must describe how
to add the optional Langfuse variables to the hosted deployment runtime
environment.

Agent Factory must support passing the optional Langfuse runtime variables to
generated Hosted Application deployments. The first implementation may expose
these values as optional advanced settings, provided that:

- Langfuse remains disabled unless the user explicitly enables it.
- The public key and secret key are treated as secrets.
- The secret key is redacted from logs, command previews, deployment status
  payloads, and UI summaries.
- Live deployment validation fails before deployment when Langfuse is enabled
  and any required Langfuse value is missing.

## Test Strategy

Unit tests must mock both the standard OpenAI client and the Langfuse OpenAI
client. Tests must not call Langfuse, OCI Enterprise AI, or any external
service.

Tests must cover:

- Langfuse disabled by default.
- Standard OpenAI client selection when Langfuse is disabled.
- Langfuse client selection when `LANGFUSE_ENABLED=true` and all required
  Langfuse values are present.
- Rejection of invalid `LANGFUSE_ENABLED` values.
- Rejection of missing `LANGFUSE_BASE_URL` when Langfuse is enabled.
- Rejection of missing `LANGFUSE_PUBLIC_KEY` when Langfuse is enabled.
- Rejection of missing `LANGFUSE_SECRET_KEY` when Langfuse is enabled.
- Preservation of existing Responses API create call shape when Langfuse is
  enabled.
- Use of the active `conversation_id` as the Langfuse session identifier for
  new conversations.
- Use of the provided `conversation_id` as the Langfuse session identifier for
  existing conversations.
- Streaming create calls are traced when Langfuse is enabled.
- Streaming finalization retrieve calls are traced when a retrieve call is made.
- Langfuse secrets are not present in logs or error responses.
- Agent Factory validation and redaction behavior for optional Langfuse
  deployment inputs.

## Acceptance Criteria

- Langfuse observability is disabled by default.
- Omitting Langfuse environment variables preserves existing agent behavior.
- `LANGFUSE_ENABLED=true` requires `LANGFUSE_BASE_URL`,
  `LANGFUSE_PUBLIC_KEY`, and `LANGFUSE_SECRET_KEY`.
- The runtime dependency set includes `langfuse>=3,<4`.
- The agent uses the standard OpenAI client when Langfuse is disabled.
- The agent uses the Langfuse OpenAI client when Langfuse is enabled.
- Every Responses API create call produces Langfuse instrumentation when
  Langfuse is enabled.
- Every Responses API retrieve call made for streaming finalization produces
  Langfuse instrumentation when Langfuse is enabled.
- Conversation-based requests use `conversation_id` as the Langfuse
  `session_id`.
- All spans for the same conversation are grouped under the same Langfuse
  session.
- Langfuse integration does not change the public `/responses` request or
  response contract.
- Langfuse keys and other secrets are redacted from logs, errors, command
  previews, and API responses.
- Unit tests cover configuration, client selection, session propagation,
  streaming behavior, and secret redaction.
