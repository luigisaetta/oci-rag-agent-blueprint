# Agent Factory

Agent Factory is the guided deployment application for the OCI RAG Agent
Blueprint.

It contains:

- `api`: FastAPI backend skeleton for validation, run tracking, and command
  planning.
- `ui`: Next.js UI for collecting deployment inputs, running dry checks, and
  showing deployment progress.

## Local Development

Start the API:

```bash
PYTHONPATH=agent-factory/api uvicorn agent_factory_api.app:app --host 0.0.0.0 --port 8081
```

Start the UI:

```bash
cd agent-factory/ui
npm run dev
```

Then open:

```text
http://localhost:3100
```

## Docker Compose

Start the Agent Factory deployment from the repository root:

```bash
./start_factory.sh --build
```

Stop only the Agent Factory services:

```bash
./stop_factory.sh
```

The Compose deployment is separate from the RAG agent demo deployment and uses
the `agent-factory` project name.

The local endpoints are:

```text
Agent Factory API: http://localhost:8081/factory/health
Agent Factory UI:  http://localhost:3100
```

The first implementation is a skeleton. It validates input, generates dry-run
commands, tracks step status, and returns command scripts without creating OCI
resources.
