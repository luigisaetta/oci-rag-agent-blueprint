# CLI Test Client

## Purpose

This specification defines a simple Python command-line client used to test the local Docker Compose deployment of the RAG agent.

The client is intended for development and manual validation. It is not the reference UI and must remain small, readable, and easy to run.

## Scope

This document covers:

- Command-line arguments.
- Request payload construction.
- Streaming response handling.
- Non-streaming JSON response handling.
- Console output behavior.

This document does not define the Next.js reference UI or production client behavior.

## Related Specifications

- [Agent Implementation](0003-agent-implementation.md)
- [Deployment](0004-deployment.md)

## Command-Line Interface

The client must accept the user request from the command line.

The client must accept a `--create-conversation` argument with explicit `true` or `false` values.

The client must accept a `--stream` argument with explicit `true` or `false`
values. The default value must be `true`.

When `--create-conversation false` is used, the client must require `--conversation-id`.

The client must accept the user request as a positional argument.

The client must be runnable from the repository root with:

```bash
python -m clients.agent_cli
```

The client must allow overriding the agent endpoint URL. The default endpoint must be:

```text
http://localhost:8080/responses
```

## Request Payload

The client must map the command-line `--create-conversation` value to the agent request payload field `new_conversation`.

The client must map the command-line `--stream` value to the agent request
payload field `stream`.

When streaming is requested, the client must set:

```json
{
  "stream": true
}
```

When creating a new conversation, the client must send:

```json
{
  "new_conversation": true,
  "user_request": "User request text",
  "stream": true
}
```

When attaching to an existing conversation, the client must send:

```json
{
  "new_conversation": false,
  "conversation_id": "existing-conversation-id",
  "user_request": "User request text",
  "stream": true
}
```

When non-streaming is requested, the client must send the same payload shape with
`stream=false`.

## Response Handling

The client must call the agent endpoint with `POST /responses`.

When `--stream true` is used, the client must consume the `text/event-stream`
response returned by the agent.

The client must stop reading the HTTP response as soon as it receives either a
`done` event or an `error` event. This keeps hosted endpoints that leave the
underlying connection open from making the CLI appear stuck after the agent has
already completed.

The client must handle the following Server-Sent Events:

- `metadata`, used to display the active conversation identifier.
- `token`, used to print response text incrementally.
- `references`, used to collect and display source references returned by the agent.
- `done`, used to close the response output cleanly.
- `error`, used to display a readable error message.

When `--stream false` is used, the client must consume the JSON response returned
by the agent and print the active conversation identifier, agent response text,
references, and error message when present.

## Console Output

The client must print a compact, readable console output suitable for manual testing.

The output must show:

- Target endpoint.
- Whether a new conversation is being created.
- Existing conversation identifier, when provided.
- Whether streaming is enabled.
- Active conversation identifier returned by the stream metadata.
- Response text, either streamed token by token or printed from the JSON response.
- References returned by the agent, including file name and page when available.
- Errors, when returned by the agent.

## Acceptance Criteria

- The client can create a streaming request for a new conversation.
- The client can create a streaming request for an existing conversation.
- The client can create a non-streaming request for a new conversation.
- The client can create a non-streaming request for an existing conversation.
- The client can be launched from the repository root with `python -m clients.agent_cli`.
- The client rejects `--create-conversation false` when `--conversation-id` is missing.
- The client maps `--create-conversation` to `new_conversation`.
- The client maps `--stream` to `stream`.
- The client consumes Server-Sent Events from the agent endpoint.
- The client exits streaming mode when the agent emits `done` or `error`.
- The client consumes JSON responses from the agent endpoint.
- The client displays references for both streaming and non-streaming responses.
- Unit tests cover payload construction, argument validation, SSE parsing, and
  JSON response handling.
