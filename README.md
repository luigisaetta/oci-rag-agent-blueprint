# OCI RAG Agent Blueprint

![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)
![black](https://img.shields.io/badge/code%20style-black-000000)
![pylint](https://img.shields.io/badge/lint-pylint-yellowgreen)
![pytest](https://img.shields.io/badge/tests-pytest-blueviolet)
![spec-driven](https://img.shields.io/badge/development-spec--driven-orange)

Retrieval-Augmented Generation becomes truly useful when it is treated as an engineered system, not as a demo stitched together around a prompt. This repository is a **blueprint** for building that system on **OCI Enterprise AI**: grounded retrieval, clear deployment guidance, and agent behavior specified before code is written.

The goal is to provide a practical foundation for creating and deploying a RAG solution in OCI Enterprise AI, using OCI Enterprise AI **Vector Store** as the retrieval layer and the **Responses API** as the interaction layer.

## What This Project Is

This project contains a blueprint and a set of guidelines for creating and deploying a RAG solution in OCI Enterprise AI. It is intended to help teams move from an idea to a repeatable implementation by combining:

- A spec-driven development workflow.
- OCI-based vector storage and retrieval.
- Response generation through the Responses API.
- Python implementation patterns with automated quality checks.
- A Next.js reference UI for local chatbot testing.
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
├── agent/
├── clients/
├── docker-compose.yml
├── LICENSE
├── README.md
├── schemas/
├── specs/
├── tests/
└── ui/
```

## Local UI

The local Docker Compose deployment includes:

- `rag-agent`, the FastAPI backend exposed on `http://localhost:8080`.
- `rag-ui`, the Next.js reference UI exposed on `http://localhost:3000`.

Start both services with:

```bash
docker-compose up -d
```

Then open:

```text
http://localhost:3000
```

## Current Status

The project now includes the first backend agent implementation, Docker Compose local deployment, a CLI test client, and a reference Next.js UI.
