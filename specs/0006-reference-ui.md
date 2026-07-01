# Reference UI

## Purpose

This specification defines the first reference user interface for the OCI RAG Agent Blueprint.

The UI must provide a pleasant, practical chatbot experience for local testing of the RAG agent backend and for demonstrating the project workflow.

## Scope

This document covers:

- Next.js application structure.
- Chat interaction model.
- Backend URL configuration.
- Optional JWT Bearer authentication for OCI Enterprise AI Hosted Application
  endpoints.
- Agent runtime summary display from the backend diagnostic endpoint.
- Conversation reset behavior.
- Streaming response rendering.
- Streaming reference collection and rendering.
- Waiting indicator while the assistant response has not produced tokens yet.
- Markdown rendering for assistant responses.
- Light and dark visual themes.
- Local Docker Compose deployment.

This document does not define production reference UI hosting in OCI Enterprise
AI or advanced inline citation rendering.

## Related Specifications

- [Architecture Guidelines](0001-architecture-guidelines.md)
- [Agent Implementation](0003-agent-implementation.md)
- [Deployment](0004-deployment.md)

## Application Runtime

The reference UI must be implemented as a Next.js application located under the `ui` folder.

The UI must be runnable locally with:

```bash
npm run dev
```

The UI must be packaged in a Docker image for local Docker Compose deployment.

The Docker Compose service name must be `rag-ui`.

The UI must listen on port `3000`.

## Layout

The UI must use a two-column application layout:

- A left sidebar for controls.
- A main chat area for the conversation.

The sidebar must include:

- A button that clears the visible chat and starts a new conversation on the next user request.
- An editable text field for the backend URL.
- A compact agent runtime summary loaded from the backend diagnostic endpoint.
- A compact response references panel for the latest completed assistant response.
- A light/dark theme control.

The backend URL field must default to the local Docker Compose backend endpoint:

```text
http://localhost:8080/responses
```

JWT authentication must be disabled by default so the local Docker Compose demo
continues to work without OCI IAM Identity Domain settings.

When JWT authentication is enabled, the sidebar must collect:

- Identity Domain URL.
- Confidential application client ID.
- Confidential application secret.
- IDCS token request scope.

The UI must keep confidential application values and acquired access tokens in
browser memory only. It must not persist them to local storage.

The UI must expose a `Test health` action that calls the backend `/health`
endpoint derived from the configured `/responses` URL. When JWT authentication
is enabled, this health check must acquire an IDCS access token and send it as:

```text
Authorization: Bearer <access-token>
```

When JWT authentication is disabled, the health check must call `/health`
without an authorization header.

The UI must load a compact agent runtime summary from the backend
`/config/environment` endpoint derived from the configured `/responses` URL.
When JWT authentication is enabled, the UI must acquire an IDCS access token and
send it as a Bearer authorization header for this request. When JWT
authentication is disabled, no authorization header must be sent.

The sidebar runtime summary must display:

- `OCI_MODEL_ID`, labeled as the agent model.
- `FILE_SEARCH_MAX_NUM_RESULTS`, labeled as the document search result limit.
- `OCI_REGION`, when available.
- `STREAM_FINALIZATION_MODE`, when available.

If `FILE_SEARCH_MAX_NUM_RESULTS` is omitted by the backend environment response,
the UI may display the documented agent default value `10`.

The runtime summary must not display secret values, raw redacted values, or full
environment dumps. It must ignore the backend `redacted` list except for knowing
that redaction occurred.

The runtime summary must be refreshed when the backend URL changes, when JWT
authentication settings change, after a successful health check, and through a
manual refresh action in the sidebar. Failure to load runtime metadata must show
a compact unavailable status without blocking chat requests.

The main area must display user and agent messages in a familiar chatbot style.

The main area must include a message composer that allows users to submit questions.

## Markdown Rendering

Assistant responses must be rendered as Markdown because model output commonly
contains Markdown formatting.

The UI must support at least:

- Paragraphs.
- Headings.
- Ordered and unordered lists.
- Inline code and fenced code blocks.
- Links.
- Tables.

User messages may be rendered as plain text.

Markdown content must remain visually contained inside the message bubble and
must not break the chat layout on narrow screens.

## Conversation Behavior

The UI must keep the active `conversation_id` returned by the backend.

When there is no active `conversation_id`, the UI must send:

```json
{
  "new_conversation": true
}
```

When there is an active `conversation_id`, the UI must send:

```json
{
  "new_conversation": false,
  "conversation_id": "active-conversation-id"
}
```

When the user clicks the new conversation button, the UI must:

- Clear visible messages.
- Clear the active `conversation_id`.
- Mark the next request as a new conversation.

## Streaming Behavior

The UI must send requests with:

```json
{
  "stream": true
}
```

The UI must consume Server-Sent Events returned by the backend.

When JWT authentication is enabled, the UI must acquire an IDCS access token
before sending the streaming request and include it as a Bearer authorization
header. When JWT authentication is disabled, no authorization header must be
sent. This preserves the unauthenticated local Docker Compose workflow.

Token acquisition must be performed by a server-side Next.js route so the
browser does not call OCI IAM directly. The route must:

- Accept Identity Domain URL, confidential application client ID, confidential
  application secret, and IDCS token request scope.
- Call `<identity-domain-url>/oauth2/v1/token` with the OAuth client
  credentials grant.
- Return the access token and expiry metadata needed by the UI.
- Return readable errors when configuration is missing, OCI IAM rejects the
  request, or the token response is malformed.

The UI may reuse an acquired token while it is still valid, but it must request a
new token before using an expired or nearly expired token.

Some hosted gateways may preserve SSE `data:` frames while stripping explicit
`event:` lines. In that case, the UI must infer agent event names from the known
payload shape:

- `conversation_id` before metadata has been shown: `metadata`.
- `text`: `token`.
- `references`: `references`.
- `usage`: `usage`.
- `error`: `error`.
- `conversation_id` after metadata has been shown: `done`.

The UI must handle:

- `metadata`, used to store the active `conversation_id`.
- `token`, used to append response text as it arrives.
- `references`, reserved for source reference rendering.
- `usage`, used to update token totals.
- `done`, used to mark the assistant response as complete.
- `error`, used to display a readable error message.

When `done` or `error` is received, the UI must stop reading the stream so
hosted gateways that keep connections open do not leave the interface in a
permanent streaming state.

The UI must not show backend protocol details to users.

While a request is in flight and the assistant message has not received any
streamed text yet, the UI must show a compact loading spinner inside the
assistant message bubble.

The spinner must be accessible through a text label for screen readers and must
not resize or shift the surrounding chat layout when tokens start arriving.

## Reference Rendering

When the UI receives a streaming `references` event, it must store the
normalized references on the assistant message currently being streamed.

The UI must preserve references until the conversation is reset.

After the assistant stream completes, the sidebar must show a compact list of
references for the latest completed assistant response. Each reference item must
show:

- Source file name.
- Page number, when available.
- A compact metadata summary when useful non-secret metadata is available.

The references panel must remain readable when no references are returned by the
backend. An empty reference list must not be treated as a stream error.

Reference rendering must support the same streaming behavior as text questions
and transcribed audio questions.

## Theme Behavior

The UI must support both light and dark themes.

Theme switching must be available from the sidebar.

The selected theme should persist in browser local storage when possible.

## Local Backend CORS

The agent backend must allow browser requests from the local reference UI during Docker Compose based development.

For the MVP, local CORS handling may allow all origins.

Production CORS and security restrictions will be defined in a later security specification.

## Docker Compose Deployment

Docker Compose must include both:

- `rag-agent`, the FastAPI backend.
- `rag-ui`, the Next.js reference UI.

The `rag-ui` service must:

- Build from the `ui` folder.
- Expose port `3000`.
- Depend on the `rag-agent` service.

## Acceptance Criteria

- The UI is implemented as a Next.js app under `ui`.
- The UI has a left sidebar with a new conversation button.
- The UI has an editable backend URL field defaulting to `http://localhost:8080/responses`.
- JWT authentication is disabled by default.
- The UI can enable JWT authentication for OCI Enterprise AI Hosted Application
  endpoints without changing the local Docker Compose default.
- The UI can request an IDCS access token through a server-side Next.js route.
- The UI sends `Authorization: Bearer <access-token>` on `/responses` requests
  only when JWT authentication is enabled.
- The UI provides a `/health` test action and sends the Bearer token only when
  JWT authentication is enabled.
- The UI loads `/config/environment` from the configured backend and sends the
  Bearer token only when JWT authentication is enabled.
- The sidebar displays the agent model and document search result limit from
  backend runtime metadata.
- The sidebar may also display non-secret region and streaming finalization mode
  values when available.
- The UI does not display secret values, raw redacted values, or full
  environment dumps from runtime metadata.
- The UI supports light and dark themes.
- The UI displays user and assistant messages in chatbot style.
- The UI renders assistant Markdown responses correctly.
- The UI sends streaming requests to the backend.
- The UI shows a loading spinner while waiting for the first assistant token.
- The UI renders streamed assistant tokens as they arrive.
- The UI handles hosted gateway responses that strip SSE event names.
- The UI exits streaming mode when the backend emits `done` or `error`.
- The UI stores and reuses the active backend `conversation_id`.
- The UI can clear the current conversation and start a new one.
- Docker Compose can build and run the UI service.
- The backend supports local browser access from the UI.
