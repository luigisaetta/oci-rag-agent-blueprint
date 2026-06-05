# Short-Term Memory

## Purpose

This specification defines how the RAG agent manages short-term memory inside a conversation.

Short-term memory must be managed platform-side by OCI Enterprise AI. The agent is responsible for selecting whether a request starts a new conversation or attaches to an existing conversation, while the platform manages the conversation state and memory lifecycle.

## Scope

This document covers:

- Short-term memory enablement in OCI Enterprise AI.
- Conversation creation and conversation attachment behavior.
- The client JSON request fields required to control conversation handling.
- The agent behavior required to connect Responses API calls to the correct conversation.

This document does not define the complete agent API payload, the complete response schema, authentication and authorization behavior, or the memory compaction prompt. Those topics will be defined in dedicated specifications.

## OCI Enterprise AI Setup

The OCI Enterprise AI project setup must enable short-term memory management.

The setup must also configure the LLM used for memory compaction. The compaction model must be selected from the model catalog supported by OCI Enterprise AI.

The selected compaction model must be documented as part of the deployment configuration.

## Client Request Contract

The client controls conversation handling through explicit JSON request fields.

When the client wants to start a new conversation, it must send:

```json
{
  "new_conversation": true
}
```

When the client wants to attach the request to an existing conversation, it must send:

```json
{
  "new_conversation": false,
  "conversation_id": "existing-conversation-id"
}
```

The `new_conversation` field must always be explicit.

The `conversation_id` field is required when `new_conversation` is `false`.

The `conversation_id` field must be ignored when `new_conversation` is `true`.

## Agent Behavior

The agent must inspect the JSON request payload before calling the Responses API.

If `new_conversation` is `true`, the agent must create or request a new platform-managed conversation through the OpenAI-compatible API exposed by OCI Enterprise AI.

If `new_conversation` is `false`, the agent must attach the request to the specified existing conversation by using the provided `conversation_id`.

The agent must connect each generated response to the correct conversation context by using the OpenAI-compatible conversation support exposed by the Responses API.

The agent must return the active conversation identifier in its JSON response payload so that clients can continue the same conversation in later requests.

## Validation Rules

The agent must reject requests that do not contain an explicit `new_conversation` field.

The agent must reject requests where `new_conversation` is `false` and `conversation_id` is missing or empty.

The agent must reject requests where `new_conversation` is not a boolean value.

Validation errors must be returned as structured JSON responses.

## Configuration

The agent runtime configuration must include the values required to use platform-managed short-term memory through OCI Enterprise AI.

The project deployment configuration must include the selected memory compaction model.

Configuration must be provided through environment variables or OCI Enterprise AI deployment configuration. Configuration values must not be hardcoded in the application code.

## Acceptance Criteria

- Short-term memory is enabled in the OCI Enterprise AI project setup.
- A memory compaction model is configured in OCI Enterprise AI.
- The agent accepts a JSON request with `new_conversation=true` and starts a new conversation.
- The agent accepts a JSON request with `new_conversation=false` and a valid `conversation_id`, then attaches the request to that existing conversation.
- The agent returns the active `conversation_id` in the JSON response payload.
- Invalid conversation control payloads are rejected with structured JSON validation errors.
- Conversation handling is implemented through the OpenAI-compatible Responses API exposed by OCI Enterprise AI.

## Open Topics

- Complete agent request and response schema.
- Error response format.
- Security requirements for accessing an existing conversation.
- Memory compaction model selection criteria.
- Observability and audit events for conversation lifecycle operations.
