# CLI Test Client

This folder contains a small Python command-line client for manually testing the local RAG agent endpoint.

The client can send either a streaming request or a non-streaming JSON request to the agent.

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

Send a non-streaming request and print the JSON response content:

```bash
python -m clients.agent_cli \
  --create-conversation true \
  --stream false \
  "What is Oracle Vector Store?"
```

Force streaming explicitly:

```bash
python -m clients.agent_cli \
  --create-conversation true \
  --stream true \
  "What is Oracle Vector Store?"
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
- Whether streaming is enabled.
- The active conversation identifier when returned by the stream.
- Response text, either token by token or from the JSON response.
- Stream errors, when returned by the agent.

With placeholder credentials, the agent may return an authentication error. That still confirms that the client can reach the local endpoint and consume the streaming response.
