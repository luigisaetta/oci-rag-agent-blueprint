# CLI Test Client

## Purpose

This specification defines a simple Python command-line client used to test the local Docker Compose deployment of the RAG agent.

The client is intended for development and manual validation. It is not the reference UI and must remain small, readable, and easy to run.

## Scope

This document covers:

- Command-line arguments.
- Optional IDCS token acquisition for authenticated Hosted Applications.
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

The client must accept a `--create-conversation` argument with explicit `true`
or `false` values. This argument is required when the client calls the agent
endpoint and optional when `--print-token-only` is used.

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

The client must accept an `--auth` argument with values `auto`, `none`, and
`idcs`. The default value must be `auto`.

The client must accept an `--env-file` argument that points to the `.env` file
used for optional client-side authentication settings. The default must be
`.env`.

The client must accept `--print-token-only`. When this flag is used with IDCS
authentication, the client must request a token, print it, and exit without
calling the agent endpoint.

The repository must also provide a standalone IDCS token test client runnable
from the repository root with:

```bash
python -m clients.idcs_token_client
```

This standalone client must only contact OCI IAM Identity Domains, request an
OAuth access token, print the token, and exit. It must not require agent endpoint
arguments, conversation arguments, or a RAG user request.

Because the IDCS access token is expected to be a JWT, the standalone client
must decode the JWT header and payload without verifying the signature and print
both sections as formatted JSON. The client must not decode, verify, or print
the signature as a separate section. The raw token remains visible in full so it
can be copied for manual testing. If the access token is not a three-part JWT,
the client must keep printing the raw token and add a readable warning that JWT
details could not be decoded.

## IDCS Token Acquisition

The client must support obtaining an OAuth access token from OCI IAM Identity
Domains for Hosted Applications protected by `IDCS_AUTH_CONFIG`.

The client must read the following variables from the process environment or the
configured `.env` file:

| Variable | Required For IDCS Auth | Purpose |
| --- | --- | --- |
| `IDENTITY_DOMAIN_URL` | Yes | Exact Identity Domain URL from OCI Console. |
| `CONFIDENTIAL_APPLICATION_ID` | Yes | Confidential application client identifier. |
| `CONFIDENTIAL_APPLICATION_SECRET` | Yes | Confidential application client secret. |
| `IDCS_SCOPE` | Yes | OAuth scope requested for the Hosted Application. |

Process environment values must override values loaded from `.env`.

When `--auth auto` is used, the client must request an IDCS token only when all
required IDCS variables are present. When they are not present, the client must
continue without token acquisition.

When `--auth idcs` is used, the client must require all IDCS variables and fail
with a clear error if any are missing.

The token request must use the OAuth client credentials flow:

```text
POST <IDENTITY_DOMAIN_URL>/oauth2/v1/token
Authorization: Basic base64(CONFIDENTIAL_APPLICATION_ID:CONFIDENTIAL_APPLICATION_SECRET)
Content-Type: application/x-www-form-urlencoded

grant_type=client_credentials&scope=<IDCS_SCOPE>
```

When token acquisition succeeds and the client calls the agent endpoint, the
client must include the token as an HTTP `Authorization: Bearer <token>` header
on both streaming and non-streaming requests. The client must continue to print
the acquired access token so the user can validate the IDCS configuration.

The standalone token client must use the same `.env` loading, required variable
validation, token endpoint construction, and token request implementation as the
full CLI test client.

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

Some hosted gateways may preserve SSE `data:` frames while stripping explicit
`event:` lines. In that case, the client must infer agent event names from the
known payload shape:

- `conversation_id` before metadata has been shown: `metadata`.
- `text`: `token`.
- `references`: `references`.
- `usage`: `usage`.
- `error`: `error`.
- `conversation_id` after metadata has been shown: `done`.

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
- The acquired IDCS access token when token acquisition is enabled and succeeds.
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
- The client handles hosted gateway responses that strip SSE event names.
- The client exits streaming mode when the agent emits `done` or `error`.
- The client consumes JSON responses from the agent endpoint.
- The client displays references for both streaming and non-streaming responses.
- The client can request and print an IDCS token using confidential application
  credentials.
- The client sends the acquired IDCS token as a `Bearer` authorization header
  when calling the agent endpoint.
- The client does not request an IDCS token in `auto` mode when the required
  variables are absent.
- The client fails clearly in `idcs` mode when required IDCS variables are
  missing.
- The standalone IDCS token client can request and print a token without any
  RAG agent request arguments.
- The standalone IDCS token client decodes and prints JWT header and payload
  details without printing or interpreting the signature.
- Unit tests cover payload construction, argument validation, SSE parsing, and
  JSON response handling.
