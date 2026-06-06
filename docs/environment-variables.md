# Environment Variables

## Purpose

This document is the runtime configuration reference for the OCI RAG Agent Blueprint.

The agent is configured entirely through environment variables. Values must not be hardcoded in source code, Docker files, or documentation examples.

## Local Configuration

For local validation and Docker Compose deployment, create a `.env` file in the repository root by copying the tracked sample:

```bash
cp .env.sample .env
```

Then edit `.env` and replace the sample values with real values for the target OCI environment.

The `.env` file must not be committed to source control.

## Hosted Application Configuration

For Hosted Application deployment in OCI Enterprise AI, the `.env` file is not used by the runtime.

All environment variables and their real values must be defined in the Hosted Application runtime configuration.

## Variable Reference

| Variable | Required | Example | Local Configuration | Hosted Application Configuration | Notes |
| --- | --- | --- | --- | --- | --- |
| `OCI_REGION` | Yes | `eu-frankfurt-1` | Set in root `.env`. | Set as a runtime environment variable. | Used to build the OpenAI-compatible OCI Enterprise AI endpoint. |
| `OCI_COMPARTMENT_ID` | Yes | `ocid1.compartment.oc1..example` | Set in root `.env`. | Set as a runtime environment variable. | Target compartment OCID for project resources and deployment context. |
| `OCI_PROJECT_ID` | Yes | `ocid1.generativeaiproject.oc1..example` | Set in root `.env`. | Set as a runtime environment variable. | OCI Enterprise AI project identifier passed to the OpenAI-compatible client. |
| `OCI_MODEL_ID` | Yes | `openai.gpt-5.4` | Set in root `.env`. | Set as a runtime environment variable. | Model identifier selected from the supported OCI Enterprise AI model catalog. |
| `OCI_VECTOR_STORE_ID` | Yes | `vs_...` | Set in root `.env`. | Set as a runtime environment variable. | Vector store identifier used by the Responses API `file_search` tool. |
| `OPENAI_API_KEY` | Yes | `sk-...` | Set in root `.env`. | Set as a runtime environment variable, preferably through the most protected configuration mechanism available. | OpenAI-compatible API key created inside the OCI Enterprise AI project. Never log or commit this value. |
| `FILE_SEARCH_MAX_NUM_RESULTS` | No | `10` | Set in root `.env` when a non-default value is needed. | Set as a runtime environment variable when a non-default value is needed. | Maximum number of Vector Store file search results requested by the Responses API `file_search` tool. Accepted range: `1` to `50`. |
| `RESPONSES_TIMEOUT_SECONDS` | No | `60` | Set in root `.env` when a non-default value is needed. | Set as a runtime environment variable when a non-default value is needed. | Timeout in seconds for Responses API create and retrieve calls. Accepted range: `1` to `300`. |
| `STREAM_FINALIZATION_MODE` | No | `never` | Set in root `.env` when a non-default value is needed. | Set as a runtime environment variable when a non-default value is needed. | Controls whether streaming responses perform a post-stream retrieve call to complete references and token usage. Accepted values: `never`, `auto`, `always`. |

## Streaming Finalization

`STREAM_FINALIZATION_MODE` controls the latency/completeness tradeoff for
streaming responses.

The default value is `never`. In this mode, the agent does not call
`responses.retrieve` after token streaming completes. References and token usage
are emitted only when OCI Enterprise AI includes them in the stream events.

Use `auto` when the deployment should prefer low latency but recover missing
references or token usage with a final retrieve call when needed.

Use `always` when the deployment should preserve complete finalization behavior
and always retrieve the completed response after streaming when a `response_id`
is available.

## Region Consistency

The following values must refer to resources in the same OCI region:

- `OCI_REGION`
- `OCI_PROJECT_ID`
- `OCI_MODEL_ID`
- `OCI_VECTOR_STORE_ID`
- `OPENAI_API_KEY`

The Object Storage bucket used for knowledge base uploads and the Hosted Application deployment must also be created in the same region.

## Failure Impact

If one or more required variables are missing, the agent must fail request handling before calling the Responses API and return a structured error response.

If variables point to resources in different regions, the most common outcomes are authentication failures, project lookup failures, vector store lookup failures, or Responses API request errors.

If `OPENAI_API_KEY` is invalid or missing required API key permissions, the agent cannot call OCI Enterprise AI.

If optional tuning variables are missing, the agent uses their defaults. If they
are present but invalid, the agent fails request handling before calling the
Responses API.

## Security Rules

- Never commit `.env`.
- Never commit real API key values.
- Never print environment variables in logs.
- Never include full runtime configuration in error responses.
- Use `.env.sample` only for placeholder values.
- Rotate `OPENAI_API_KEY` according to customer security requirements.
