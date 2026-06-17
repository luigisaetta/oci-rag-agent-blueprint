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

The Agent Factory API container uses the host Docker daemon to validate OCIR
credentials, build the RAG agent backend image, and push it to OCIR. Make sure
Docker is running on the host before starting Agent Factory.
After pulling changes to the Agent Factory API image, restart with
`./start_factory.sh --build` so the API container is rebuilt and recreated.

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

When the UI is opened from a browser on a different machine, the Factory API
endpoint field must use the hostname or IP address of the machine that runs the
Agent Factory API backend. For example, when the backend runs on a host named
`proxima`, set the field to:

```text
http://proxima:8081/factory/deployments
```

Dry runs validate inputs and generate command plans without creating OCI
resources. Non-dry-run deployments create or reuse the configured OCI resources,
build and push the RAG agent backend image, and create the Hosted Application
deployment.

After a successful live deployment, the UI outputs include the Hosted
Application invoke base URL plus ready-to-use health and `/responses` URLs. Use
the `/responses` URL with the reference UI or Python CLI client when validating
the hosted RAG agent.
