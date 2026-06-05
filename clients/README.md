# CLI Test Client

This folder contains a small Python command-line client for manually testing the local RAG agent endpoint.

The client sends a streaming request to the agent and prints the response as Server-Sent Events are received.

## Prerequisites

Start the local Docker Compose deployment before running the client:

```bash
docker-compose up -d
```

The agent must be reachable at:

```text
http://localhost:8080/responses
```

## Run From The Repository Root

Create a new conversation:

```bash
python -m clients.agent_cli \
  --create-conversation true \
  "Explain how the local deployment works."
```

Continue an existing conversation:

```bash
python -m clients.agent_cli \
  --create-conversation false \
  --conversation-id conv_123 \
  "Continue from the previous answer."
```

Override the endpoint:

```bash
python -m clients.agent_cli \
  --endpoint http://localhost:8080/responses \
  --create-conversation true \
  "What is the configured vector store?"
```

## Output

The client prints:

- Target endpoint.
- Whether a new conversation is being created.
- The active conversation identifier when returned by the stream.
- Response tokens as they arrive.
- Stream errors, when returned by the agent.

With placeholder credentials, the agent may return an authentication error. That still confirms that the client can reach the local endpoint and consume the streaming response.
