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
| [0007 - Security](0007-security.md) | OpenAI-compatible API key security model, OCI Resource Principal runtime mode, secret handling, and hosted authentication direction. |
| [0008 - Document Loading](0008-document-loading.md) | Object Storage bucket and Vector Store Data Sync Connector approach for loading and updating knowledge base documents. |
| [0009 - Agent Runtime Tuning](0009-agent-runtime-tuning.md) | Runtime tuning parameters for file search result count, Responses API timeout, and streaming finalization. |
| [0010 - Agent Factory](0010-agent-factory.md) | Guided backend and Next.js UI application for deploying the RAG agent backend into OCI Enterprise AI Hosted Applications. |
| [0011 - Agent Factory Ready-To-Run Deployment Script](0011-agent-factory-ready-script.md) | Exportable Linux-first deployment script that reuses Agent Factory live execution logic without changing dry-run behavior. |
| [0012 - Langfuse Observability](0012-langfuse-observability.md) | Optional Langfuse observability for Responses API calls, including runtime configuration, client selection, spans, sessions, deployment behavior, and tests. |
| [0013 - Agent-Managed Connector Ingestion](0013-agent-managed-connector-ingestion.md) | Server-side agent endpoints for uploading documents to Object Storage, triggering asynchronous Vector Store Data Sync Connector jobs, and reading job status. |
| [0014 - Voice Agent Requests](0014-voice-agent-requests.md) | Server-side speech-to-text request handling with OCI Speech, transcript-first streaming, and reference UI microphone input. |
| [0015 - Evaluation Golden Dataset](0015-evaluation-golden-dataset.md) | Offline golden dataset generation and incremental JSONL maintenance for future end-to-end RAG evaluations. |
