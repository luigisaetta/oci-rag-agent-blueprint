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

## IDCS Token Check

For Hosted Applications protected by `IDCS_AUTH_CONFIG`, the client can request
an OAuth access token from OCI IAM Identity Domains.

Set these values in `.env` or in the process environment:

```text
IDENTITY_DOMAIN_URL=https://idcs-example.identity.oraclecloud.com
CONFIDENTIAL_APPLICATION_ID=replace-with-confidential-application-id
CONFIDENTIAL_APPLICATION_SECRET=replace-with-confidential-application-secret
IDCS_SCOPE=replace-with-oauth-scope
```

Print only the token:

```bash
python -m clients.agent_cli \
  --auth idcs \
  --print-token-only
```

Or use the standalone token client:

```bash
python -m clients.idcs_token_client
```

The standalone client prints the raw access token and decodes the JWT header and
payload for inspection. It does not verify, decode, or render the signature as a
separate section.

When `--auth auto` is used, the client requests and prints a token only when all
IDCS variables are present. In this increment, the token is printed for
validation; sending it as a `Bearer` header to the agent endpoint will be added
later.

## Output

The client prints:

- Target endpoint.
- Whether a new conversation is being created.
- Whether streaming is enabled.
- IDCS access token when IDCS token acquisition is enabled and succeeds.
- The active conversation identifier when returned by the stream.
- Response text, either token by token or from the JSON response.
- Stream errors, when returned by the agent.

With placeholder credentials, the agent may return an authentication error. That still confirms that the client can reach the local endpoint and consume the streaming response.
