# Specifications

This directory contains the project specifications for the OCI RAG Agent Blueprint.

Specifications are the source of truth for the implementation. New features must be specified here before code is generated or changed.

| Spec | Description |
| --- | --- |
| [0001 - Architecture Guidelines](0001-architecture-guidelines.md) | High-level architecture, project scope, deployment direction, configuration principles, and reference UI role. |
| [0002 - Short-Term Memory](0002-short-term-memory.md) | Platform-managed conversation memory, conversation creation, and attachment to existing conversations. |
| [0003 - Agent Implementation](0003-agent-implementation.md) | FastAPI agent contract, JSON validation, Responses API usage, file search, streaming, logging, and environment variables. |
| [0004 - Deployment](0004-deployment.md) | Local Docker Compose deployment and hosted deployment requirements for OCI Enterprise AI. |
| [0005 - CLI Test Client](0005-cli-test-client.md) | Python command-line client for testing the agent locally, including streaming support. |
| [0006 - Reference UI](0006-reference-ui.md) | Next.js reference UI behavior, chat experience, backend URL configuration, themes, and streaming support. |
| [0007 - Security](0007-security.md) | Initial OpenAI-compatible API key security model and future OCI Resource Principal direction. |
| [0008 - Document Loading](0008-document-loading.md) | Object Storage bucket and Vector Store Data Sync Connector approach for loading and updating knowledge base documents. |
| [0009 - Agent Runtime Tuning](0009-agent-runtime-tuning.md) | Runtime tuning parameters for file search result count and Responses API timeout. |
