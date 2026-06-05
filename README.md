# OCI RAG Agent Blueprint

Retrieval-Augmented Generation becomes truly useful when it is treated as an engineered system, not as a demo stitched together around a prompt. This repository is a blueprint for building that system on OCI Enterprise AI: grounded retrieval, clear deployment guidance, and agent behavior specified before code is written.

The goal is to provide a practical foundation for creating and deploying a RAG solution in Oracle Cloud Infrastructure, using OCI Vector Store as the retrieval layer and the Responses API as the interaction layer.

## What This Project Is

This project contains a blueprint and a set of guidelines for creating and deploying a RAG solution in OCI Enterprise AI. It is intended to help teams move from an idea to a repeatable implementation by combining:

- A spec-driven development workflow.
- OCI-based vector storage and retrieval.
- Response generation through the Responses API.
- Python implementation patterns with automated quality checks.
- Unit tests and coverage expectations for every new feature.

## Development Approach

This repository follows spec-driven development.

Every new capability must start with a specification under the `specs/` directory. Code is written only after the expected behavior, acceptance criteria, and test expectations are documented.

This keeps the project aligned around a simple rule: the implementation must conform to the specification, not the other way around.

## Quality Standards

Python code in this repository must follow these standards:

- Source files include the required project header.
- Code is formatted with `black`.
- Code is checked with `pylint`.
- Unit tests are written with `pytest`.
- New functionality targets more than 80% test coverage.
- Work is considered done only when formatting, linting, tests, and related fixes are complete.

See [AGENTS.md](AGENTS.md) for the full working guidelines.

## Repository Structure

```text
.
├── AGENTS.md
├── LICENSE
├── README.md
└── specs/
```

## Current Status

The project is in its foundation phase. The first priority is to define the specifications that will drive the blueprint, implementation structure, deployment guidance, and test strategy.
