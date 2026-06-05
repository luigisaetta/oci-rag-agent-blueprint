# Security

## Purpose

This specification defines the initial security model for the OCI RAG Agent Blueprint.

The first version focuses on how the agent authenticates to OCI Enterprise AI resources, including the selected LLM and the configured vector store. End-user authentication and authorization are intentionally left for later specifications.

## Scope

This document covers:

- Agent access to OCI Enterprise AI resources.
- OpenAI-compatible API key authentication.
- Required security-related environment variables.
- Advantages and disadvantages of the MVP approach.
- Future support for OCI-native Resource Principal authentication.

This document does not yet define:

- End-user authentication to the agent HTTPS endpoint.
- JWT validation.
- User role authorization.
- Network security.
- Secret rotation.
- OCI Vault integration.

## Related Specifications

- [Architecture Guidelines](0001-architecture-guidelines.md)
- [Agent Implementation](0003-agent-implementation.md)
- [Deployment](0004-deployment.md)
- [OCI Enterprise AI Deployment Guide](../docs/oci-enterprise-ai-deployment.md)

## Current Security Model

The MVP implementation uses the OpenAI-compatible security model exposed by OCI Enterprise AI.

The agent must authenticate to OCI Enterprise AI through an API key created inside the OCI Enterprise AI project.

The API key must be passed to the agent through the `OPENAI_API_KEY` environment variable.

The agent must use the `openai` Python library and create an OpenAI-compatible client with:

```python
OpenAI(
    api_key=OPENAI_API_KEY,
    base_url=BASE_URL,
    project=OCI_PROJECT_ID,
)
```

The same client is used to access:

- The configured LLM.
- The configured OCI Vector Store through the Responses API `file_search` tool.
- Platform-managed conversations.

## Required Environment Variables

The following environment variables are relevant to the current security model:

| Variable | Description |
| --- | --- |
| `OPENAI_API_KEY` | OpenAI-compatible API key created inside the OCI Enterprise AI project. |
| `OCI_PROJECT_ID` | OCI Enterprise AI project identifier associated with the API key and runtime resources. |
| `OCI_REGION` | OCI region used to build the OpenAI-compatible endpoint. |
| `OCI_MODEL_ID` | Model identifier selected from the supported model catalog. |
| `OCI_VECTOR_STORE_ID` | Vector store identifier used by the file search tool. |

The project, API key, model, and vector store must belong to the same OCI region.

## Advantages

The OpenAI-compatible API key approach has the following advantages:

- It follows the same programming model used by OpenAI clients.
- It is simple to configure and understand.
- It works directly with the standard `openai` Python library.
- It is convenient for Docker Compose and local integration testing.
- It avoids adding OCI SDK authentication complexity to the MVP.
- It preserves the project goal of using the Responses API compatibility layer as the primary agent interface.

## Disadvantages

The OpenAI-compatible API key approach has the following disadvantages:

- The API key value is passed to the container through environment variables.
- The API key is present in the runtime environment of the container.
- Operators must ensure that environment variables are not logged or exposed.
- API key rotation is not automated in the MVP.
- Access is tied to the API key permissions instead of a runtime workload identity.

## Handling Rules

The implementation and deployment must follow these rules:

- `OPENAI_API_KEY` must never be committed to version control.
- Local Docker Compose deployment must read `OPENAI_API_KEY` from the root `.env` file.
- The root `.env` file must remain ignored by Git.
- Hosted deployment must inject `OPENAI_API_KEY` through managed runtime configuration.
- The agent must never log the API key.
- Error responses must not include secrets, full environment dumps, or complete runtime configuration.
- Documentation must refer to the variable name and must not include real API key values.

## Future OCI-Native Security Model

A future release will add support for OCI-native security.

With that approach, the agent should authenticate to OCI resources by using OCI Resource Principal instead of passing an API key value through environment variables.

The future Resource Principal model should:

- Use the runtime identity of the hosted application or deployment.
- Avoid passing a long-lived API key to the container.
- Use OCI IAM policies and dynamic groups.
- Support least-privilege access to OCI Enterprise AI resources.
- Preserve compatibility with the OpenAI-based implementation where possible.

## Open Topics

The following topics require later specifications or revisions:

- Exact Resource Principal integration pattern for the OpenAI-compatible client.
- Whether OCI Enterprise AI exposes first-class Resource Principal authentication for the OpenAI-compatible API surface.
- OCI Vault secret management.
- API key rotation.
- End-user authentication and authorization.
- Hosted application authentication through OCI IAM identity domains.
