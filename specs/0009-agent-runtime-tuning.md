# Agent Runtime Tuning

## Purpose

This specification defines the runtime tuning parameters that can be changed
without modifying the agent source code.

The goal is to keep operational parameters easy to configure for Docker Compose
and OCI Enterprise AI Hosted Deployment while preserving a predictable API
contract for clients.

## Scope

This specification covers:

- File search result count tuning.
- Responses API timeout tuning.
- Streaming finalization tuning.
- Environment variable names, defaults, validation, and usage.

This specification does not cover model selection, authentication, authorization,
deployment topology, or client-provided per-request tuning.

## Related Specifications

- [Architecture Guidelines](0001-architecture-guidelines.md)
- [Agent Implementation](0003-agent-implementation.md)
- [Deployment](0004-deployment.md)

## Configuration Model

Runtime tuning must be provided through environment variables.

These values are operational settings of the deployed agent and must not be
accepted directly from the client request payload in the MVP.

This keeps behavior predictable, limits accidental cost increases, and prevents a
client from arbitrarily changing retrieval or timeout behavior.

## Runtime Tuning Variables

| Variable | Required | Default | Validation | Description |
| --- | --- | --- | --- | --- |
| `FILE_SEARCH_MAX_NUM_RESULTS` | No | `10` | Integer from `1` to `50` | Maximum number of file search results requested from the configured Vector Store. |
| `RESPONSES_TIMEOUT_SECONDS` | No | `60` | Integer from `1` to `300` | Timeout in seconds for Responses API create and retrieve calls. |
| `STREAM_FINALIZATION_MODE` | No | `never` | One of `never`, `auto`, or `always` | Controls whether streaming responses perform a post-stream retrieve call to complete references and token usage. |

## File Search Result Count

`FILE_SEARCH_MAX_NUM_RESULTS` controls the `max_num_results` value passed to the
Responses API `file_search` tool.

The agent must use the configured value when building the file search tool:

```python
{
    "type": "file_search",
    "vector_store_ids": [OCI_VECTOR_STORE_ID],
    "max_num_results": FILE_SEARCH_MAX_NUM_RESULTS,
}
```

The default value must be `10`.

The accepted range must be `1` to `50`.

Values outside the accepted range must fail configuration loading before any
Responses API call is made.

## Streaming Finalization Mode

`STREAM_FINALIZATION_MODE` controls whether the agent performs a post-stream
`client.responses.retrieve` call after token streaming completes.

The default value must be `never`.

The accepted values must be:

- `never`: Do not perform a post-stream retrieve call. References and usage are
  emitted only when available in Responses API stream events. This mode provides
  the lowest end-of-stream latency and treats references and token usage as
  best-effort metadata.
- `auto`: Prefer stream-provided references and usage. Perform a post-stream
  retrieve call only when final references or usage are missing after the stream
  completes and a `response_id` is available.
- `always`: Always perform a post-stream retrieve call when a `response_id` is
  available. This preserves the legacy complete-finalization behavior at the
  cost of additional end-of-stream latency.

Values outside the accepted set must fail configuration loading before any
Responses API call is made.

## Responses API Timeout

`RESPONSES_TIMEOUT_SECONDS` controls the timeout used for Responses API calls.

The agent must use the configured timeout for:

- Non-streaming `client.responses.create`.
- Streaming `client.responses.create`.
- Streaming follow-up `client.responses.retrieve` when
  `STREAM_FINALIZATION_MODE` permits a final retrieve call.

The default value must be `60`.

The accepted range must be `1` to `300`.

Values outside the accepted range must fail configuration loading before any
Responses API call is made.

## Deployment Requirements

For local Docker Compose deployment, these variables may be set in the root
`.env` file.

For OCI Enterprise AI Hosted Deployment, these variables may be set in the
hosted application runtime environment configuration.

All runtime tuning variables are optional. If they are omitted, the agent must use the default
values defined in this specification.

The tracked `.env.sample` file must document these variables and their defaults.

## Error Handling

Invalid tuning values must be reported as configuration errors.

The error message should include:

- The environment variable name.
- The expected type or range.
- The invalid value when safe to report.

Invalid tuning values must not be silently ignored.

## Test Strategy

Unit tests must cover:

- Default values when all tuning variables are omitted.
- Valid custom values.
- Rejection of non-integer values.
- Rejection of values below the allowed minimum.
- Rejection of values above the allowed maximum.
- Rejection of unsupported `STREAM_FINALIZATION_MODE` values.
- Use of `FILE_SEARCH_MAX_NUM_RESULTS` in the file search tool configuration.
- Use of `RESPONSES_TIMEOUT_SECONDS` in Responses API create and retrieve calls.
- Streaming without a post-stream retrieve call by default.
- Conditional post-stream retrieve behavior for `auto`.
- Always-on post-stream retrieve behavior for `always`.

## Acceptance Criteria

- `FILE_SEARCH_MAX_NUM_RESULTS` is loaded from environment variables with default `10`.
- `RESPONSES_TIMEOUT_SECONDS` is loaded from environment variables with default `60`.
- `STREAM_FINALIZATION_MODE` is loaded from environment variables with default `never`.
- Invalid tuning values fail configuration loading before Responses API calls.
- File search uses the configured `max_num_results`.
- Responses API create and retrieve calls use the configured timeout when those
  calls are made.
- Streaming responses do not perform a post-stream retrieve call by default.
- `.env.sample` documents all tuning variables.
- Tests cover default, valid, invalid, and call-shape behavior.
