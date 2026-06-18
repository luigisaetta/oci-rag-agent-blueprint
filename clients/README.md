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
IDCS_SCOPE=replace-with-primary-audience-plus-scope
```

For OCI IAM IDCS Hosted Application auth, keep `audience` and `scope` separate
in the Hosted Application configuration, but use the concatenated value in
`IDCS_SCOPE`. For example, Hosted Application `audience=hello_world` and
`scope=invoke` means client `IDCS_SCOPE=hello_worldinvoke`. See
[OCI IAM IDCS Audience And Scope](../docs/idcs-audience-and-scope.md).

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
IDCS variables are present. When token acquisition succeeds, the full CLI client
also sends the token to the agent endpoint as:

```text
Authorization: Bearer <access-token>
```

This lets the same client call Hosted Application endpoints protected with
`IDCS_AUTH_CONFIG`.

Example against a protected Hosted Application:

```bash
python -m clients.agent_cli \
  --endpoint https://<hosted-application-url>/actions/invoke/responses \
  --auth idcs \
  --create-conversation true \
  "Explain the documents in the vector store."
```

The repository root also includes `test_hosted_application.sh`, a diagnostic
wrapper for Hosted Application validation. Edit the variables at the top of that
script and run:

```bash
./test_hosted_application.sh
```

The script validates IDCS token acquisition, JWT claim decoding, `/health`,
non-streaming `/responses`, and streaming `/responses`. It prints pass/fail
status for each step without printing the raw access token or confidential
application secret.

By default the diagnostic output only shows response sizes and reference counts.
Set `SHOW_AGENT_OUTPUT=true` near the top of `test_hosted_application.sh` when
you also want to print the actual answer returned by the agent.

## Output

The client prints:

- Target endpoint.
- Whether a new conversation is being created.
- Whether streaming is enabled.
- IDCS access token when IDCS token acquisition is enabled and succeeds.
- Bearer authentication on the agent request when an IDCS access token is
  available.
- The active conversation identifier when returned by the stream.
- Response text, either token by token or from the JSON response.
- Stream errors, when returned by the agent.

With placeholder credentials, the agent may return an authentication error. That still confirms that the client can reach the local endpoint and consume the streaming response.
