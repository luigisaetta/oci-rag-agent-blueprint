# Reference UI

## Purpose

This specification defines the first reference user interface for the OCI RAG Agent Blueprint.

The UI must provide a pleasant, practical chatbot experience for local testing of the RAG agent backend and for demonstrating the project workflow.

## Scope

This document covers:

- Next.js application structure.
- Chat interaction model.
- Backend URL configuration.
- Conversation reset behavior.
- Streaming response rendering.
- Light and dark visual themes.
- Local Docker Compose deployment.

This document does not define production authentication, authorization, reference UI hosting in OCI Enterprise AI, or advanced citation rendering.

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
- A light/dark theme control.

The backend URL field must default to the local Docker Compose backend endpoint:

```text
http://localhost:8080/responses
```

The main area must display user and agent messages in a familiar chatbot style.

The main area must include a message composer that allows users to submit questions.

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

The UI must handle:

- `metadata`, used to store the active `conversation_id`.
- `token`, used to append response text as it arrives.
- `done`, used to mark the assistant response as complete.
- `error`, used to display a readable error message.

The UI must not show backend protocol details to users.

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
- The UI supports light and dark themes.
- The UI displays user and assistant messages in chatbot style.
- The UI sends streaming requests to the backend.
- The UI renders streamed assistant tokens as they arrive.
- The UI stores and reuses the active backend `conversation_id`.
- The UI can clear the current conversation and start a new one.
- Docker Compose can build and run the UI service.
- The backend supports local browser access from the UI.
