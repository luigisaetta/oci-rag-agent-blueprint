# Changelog

All notable project changes must be recorded in this file.

Entries are grouped by date. New entries should be added under the current date
whenever significant features, fixes, refactorings, specifications, deployment
changes, or documentation updates are introduced.

## 2026-06-05

- Created the initial spec-driven project structure and repository guidelines.
- Added architecture, agent implementation, short-term memory, deployment,
  security, UI, and document loading specifications.
- Implemented the FastAPI RAG agent using the OpenAI-compatible Responses API.
- Added Docker Compose based local deployment with backend and Next.js UI.
- Added the Python CLI test client with streaming support.
- Added JSON Schema validation for agent request and response payloads.
- Added reference extraction for Responses API file search results and citation
  annotations.
- Added streaming reference recovery by retrieving the completed Responses API
  response after token streaming.
- Added page number extraction from retrieved result text when OCI does not
  populate page metadata attributes.
- Refactored reference and citation handling into `agent/references.py`.
- Updated the response contract to include token usage information.
- Implemented token usage extraction for non-streaming and streaming agent
  responses.
- Updated the Python CLI test client to display token usage.
