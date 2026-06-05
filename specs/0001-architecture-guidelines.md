# Architecture Guidelines

## Purpose

This specification defines the initial architectural guidelines for the OCI RAG Agent Blueprint project.

The purpose of the project is to provide a blueprint, a working reference implementation, documentation, and build and deployment scripts for a Retrieval-Augmented Generation solution designed to run and be deployed in OCI Enterprise AI.

## Scope

This document describes the high-level architecture and deployment principles that future specifications and implementation work must follow. It does not define the complete security model, detailed API contracts, ingestion pipeline implementation, or UI behavior. Those details will be covered by dedicated specifications.

## Architectural Overview

The solution is composed of the following main areas:

- A RAG agent implemented in Python.
- One or more OCI Vector Store instances used as the knowledge base.
- OCI Object Storage buckets used as document staging locations.
- OCI sync connectors used to synchronize Object Storage content with Vector Store instances.
- An HTTPS endpoint exposing the RAG agent.
- JSON-based request and response payloads for agent input and output.
- A Docker-based packaging model.
- Deployment support for both local testing and hosted deployment in OCI Enterprise AI.
- A reference UI implemented with Next.js.

## Knowledge Base

Documents used by the knowledge base must be stored in one or more vector stores.

Document loading must use OCI-native services:

- Source documents are uploaded to an OCI Object Storage bucket.
- An OCI sync connector synchronizes the Object Storage bucket with the target vector store.
- The RAG agent queries the vector store as its retrieval layer.

The architecture must support multiple vector stores when required by the use case.

## RAG Agent Implementation

The RAG agent implementation must be entirely based on the Responses API.

OCI Enterprise AI provides an implementation of the Responses API that is fully compatible with the OpenAI Responses API. The agent code must rely on that compatibility and avoid provider-specific behavior unless it is explicitly documented in a specification.

The large language model used by the agent must be configurable. Configuration must allow selecting a model from a supported model catalog, including OpenAI models and non-OpenAI models such as Google Gemini when available through OCI Enterprise AI.

The agent must receive input and return output through structured JSON payloads. The complete request and response schema will be defined in a dedicated agent API specification.

## Agent Exposure

The RAG agent must be exposed through a protected HTTPS endpoint.

Security details will be defined in later specifications, but the architecture must support authentication and authorization based on OCI IAM.

The agent may be protected by using:

- An OCI IAM confidential application.
- JWT tokens.
- Authorization checks applied before protected agent operations are executed.

## Agent-To-Resource Security

The first implementation must authenticate the agent to OCI Enterprise AI resources by using the OpenAI-compatible API key model defined in the dedicated security specification.

The API key is created inside the OCI Enterprise AI project and is passed to the agent through runtime environment variables.

A future release should add support for OCI-native security based on OCI Resource Principal, so the hosted workload can access OCI resources through its runtime identity instead of a long-lived API key value.

## Packaging

The RAG agent must be packaged as a Docker container.

The container image must include the runtime dependencies required to execute the agent and must be suitable for both local testing and hosted deployment.

## Deployment Modes

The project must support two deployment modes:

1. Local deployment for testing, based on Docker Compose.
2. Hosted deployment in OCI Enterprise AI, supported by documentation and deployment scripts.

Local deployment must be useful for development, validation, and integration testing before moving to OCI Enterprise AI hosted deployment.

## Configuration

All runtime configuration must be provided to the agent through environment variables.

Configuration must include, at minimum, the values required to select the model, connect to the OCI Enterprise AI Responses API implementation, locate retrieval resources, configure security behavior, and expose the agent endpoint.

Configuration values must not be hardcoded in the application code.

## Reference UI

The project must include a reference UI implemented with Next.js.

The UI is intended for testing and demonstration of the RAG agent. It must help validate the end-to-end behavior of the deployed solution without becoming the primary focus of the blueprint.

## Guiding Principles

- Specifications must be written before implementation.
- Implementation must conform to the relevant specification.
- OCI-native services should be used for storage, synchronization, deployment, and security whenever they fit the target architecture.
- The Responses API compatibility layer must be treated as the primary agent interface.
- Runtime behavior must be configurable through environment variables.
- Local testing and hosted deployment must remain aligned.
- Security must be designed as part of the architecture, not added as an afterthought.

## Open Topics

The following topics require dedicated specifications:

- End-user security model and JWT validation.
- Agent API contract.
- JSON request and response schema.
- Vector store retrieval strategy.
- Short-term memory and conversation management.
- Object Storage to Vector Store synchronization setup.
- Docker image structure.
- Docker Compose local deployment.
- Hosted deployment in OCI Enterprise AI.
- Environment variable reference.
- Next.js reference UI behavior.
- Testing strategy and coverage expectations.
