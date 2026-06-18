# Quickstart

This guide takes you from an empty OCI setup to a first working RAG demo with the OCI RAG Agent Blueprint.

The quickstart is intentionally compact. Use it as the main path, then follow the linked documents when you need policy details, environment variable details, or hosted deployment specifics.

## Goal

At the end of this guide you will have:

- An OCI Enterprise AI project.
- An OpenAI-compatible API key.
- An OCI Vector Store connected to an Object Storage bucket.
- A synchronized knowledge base.
- A local Docker Compose demo with the RAG agent and reference UI.
- A container image ready to be pushed to OCI Container Registry.
- The information needed to create a Hosted Application and Hosted Deployment in OCI Enterprise AI.

## 1. Check Prerequisites

You need:

- Access to an OCI tenancy with OCI Enterprise AI / OCI Generative AI enabled.
- A target OCI compartment.
- A selected OCI region.
- Permissions to manage OCI Generative AI resources.
- Permissions to create and manage the Object Storage bucket used for document uploads.
- Permissions to push images to OCI Container Registry.
- Docker installed locally.
- OCI CLI configured for the target tenancy and region.

For IAM policy examples, see [OCI Enterprise AI Deployment Guide](docs/oci-enterprise-ai-deployment.md).

## 2. Create OCI Enterprise AI Resources

Create all resources in the same OCI region.

Create an OCI Enterprise AI / OCI Generative AI project.

Record the project identifier. It will be used as:

```text
OCI_PROJECT_ID
```

Create an OpenAI-compatible API key inside the project.

Store the generated key secret securely. It will be used as:

```text
OPENAI_API_KEY
```

Create a Vector Store.

Record the vector store identifier. It will be used as:

```text
OCI_VECTOR_STORE_ID
```

For a practical introduction, see [First Steps with Vector Stores](https://luigi-saetta.medium.com/oci-enterprise-ai-first-steps-with-vector-stores-df074cb398cb).

## 3. Prepare The Knowledge Base

Create an Object Storage bucket in the same region and compartment.

Upload the documents that should become part of the knowledge base.

The supported formats for this first version are:

- PDF files (`.pdf`)
- Plain text files (`.txt`)
- Markdown files (`.md`)

Create a Data Sync Connector in the Vector Store and link it to the Object Storage bucket.

After uploading one or more files, start a synchronization job from the OCI Cloud Console or through an automation script.

Wait for the synchronization job to complete before testing retrieval.

## 4. Configure Runtime Variables

For local validation and Docker Compose deployment, create a `.env` file in the repository root:

```bash
cp .env.sample .env
```

Edit `.env` and set all required values.

By default, streaming uses `STREAM_FINALIZATION_MODE=never`. This avoids a
post-stream retrieve call for lower end-of-stream latency. Streaming references
and token usage are therefore emitted only when OCI Enterprise AI includes them
in the stream events. Set `STREAM_FINALIZATION_MODE=auto` or `always` when the
deployment should trade additional latency for more complete final metadata.

For Hosted Application deployment in OCI Enterprise AI, the `.env` file is not used by the runtime. The same variables and their real values must be configured in the Hosted Application runtime configuration.

See [Environment Variables](docs/environment-variables.md) for the complete reference.

## 5. Run The Local Demo

Build and start the local Docker Compose demo:

```bash
./start_demo.sh --build
```

The local deployment starts:

- `rag-agent` on `http://localhost:8080`
- `rag-ui` on `http://localhost:3000`

Open the reference UI:

```text
http://localhost:3000
```

Ask a question that can be answered from the synchronized knowledge base.

Stop the demo when finished:

```bash
./stop_demo.sh
```

## 6. Validate The Agent

Check the health endpoint:

```bash
curl http://localhost:8080/health
```

Expected response:

```json
{
  "status": "ok"
}
```

Use the reference UI or the Python CLI test client to send a request to the agent.

The agent should:

- Create or attach to a conversation.
- Query the configured Vector Store through Responses API file search.
- Return an answer.
- Stream final-answer tokens when streaming is enabled.

For CLI usage, see [CLI Test Client](clients/README.md).

## 7. Validate IDCS Token Acquisition

For Hosted Applications protected with `IDCS_AUTH_CONFIG`, validate that the
confidential application settings can issue a JWT access token before testing
the protected endpoint.

Make sure `.env` contains:

```text
IDENTITY_DOMAIN_URL
CONFIDENTIAL_APPLICATION_ID
CONFIDENTIAL_APPLICATION_SECRET
IDCS_SCOPE
```

Then run:

```bash
python -m clients.idcs_token_client
```

The standalone client contacts OCI IAM Identity Domains, prints the raw access
token, and decodes the JWT header and payload for inspection. It does not call
the RAG agent endpoint.

To call a protected Hosted Application with the full Python CLI client, use the
Hosted Application invoke URL and enable IDCS auth:

```bash
python -m clients.agent_cli \
  --endpoint https://<hosted-application-url>/actions/invoke/api/responses \
  --auth idcs \
  --create-conversation true \
  "Explain the documents in the vector store."
```

The client requests the IDCS access token, prints it for inspection, and sends it
to the Hosted Application as an `Authorization: Bearer <token>` header.

## 8. Build The Container Image

For local development on Apple Silicon or other ARM-based machines, `./start_demo.sh --build` can build and run native ARM images. This is valid for local testing only.

For OCI Enterprise AI Hosted Deployment, the image must be built for `linux/amd64`. The recommended approach is to build the hosted deployment image on a Linux AMD64 build machine.

Build the backend image for hosted deployment from the repository root on the AMD64 build machine:

```bash
docker build -t oci-rag-agent-blueprint-agent:latest .
```

The resulting container exposes HTTP on port `8080` and expects all runtime configuration through environment variables.

## 9. Push The Image To OCI Container Registry

Tag the image for OCI Container Registry:

```bash
docker tag oci-rag-agent-blueprint-agent:latest <region-key>.ocir.io/<tenancy-namespace>/<repo-name>:<tag>
```

Log in and push:

```bash
docker login <region-key>.ocir.io
docker push <region-key>.ocir.io/<tenancy-namespace>/<repo-name>:<tag>
```

Use a non-floating tag for customer deployments, for example:

```text
0.1.0
```

## 10. Deploy In OCI Enterprise AI

Create a Hosted Application in OCI Enterprise AI / OCI Generative AI.

Configure:

- Name and compartment.
- Scaling settings.
- Network access mode.
- Endpoint access mode.
- Authentication settings.
- Runtime environment variables.

Create a Hosted Deployment inside the Hosted Application and link it to the OCIR image.

Activate the deployment.

For the detailed hosted deployment procedure, see [OCI Enterprise AI Deployment Guide](docs/oci-enterprise-ai-deployment.md).

## 11. Final Validation

Validate the hosted deployment:

- The deployment reaches an active or running state.
- The application endpoint is available over HTTPS.
- `GET /health` returns success.
- `POST /responses` returns a JSON response.
- `POST /responses` with `stream=true` streams events.
- A knowledge-base question returns an answer grounded in synchronized documents.

## Next Documents

- [OCI Enterprise AI Deployment Guide](docs/oci-enterprise-ai-deployment.md)
- [Environment Variables](docs/environment-variables.md)
- [Specifications Index](specs/README.md)
- [Security Specification](specs/0007-security.md)
