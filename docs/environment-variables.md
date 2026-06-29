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

Note: the Agent Factory local Docker Compose stack also reads an `OCI_AUTH_MODE`
environment variable for its own control-plane authentication and currently
uses values such as `user_principal` and `session`. That setting belongs to the
Factory process. The agent runtime setting documented below uses
`openai_api_key`, `resource_principal`, and `config_file`.

## Variable Reference

| Variable | Required | Example | Local Configuration | Hosted Application Configuration | Notes |
| --- | --- | --- | --- | --- | --- |
| `OCI_REGION` | Yes | `eu-frankfurt-1` | Set in root `.env`. | Set as a runtime environment variable. | Used to build the OpenAI-compatible OCI Enterprise AI endpoint. |
| `OCI_COMPARTMENT_ID` | Yes | `ocid1.compartment.oc1..example` | Set in root `.env`. | Set as a runtime environment variable. | Target compartment OCID for project resources and deployment context. |
| `OCI_PROJECT_ID` | Yes | `ocid1.generativeaiproject.oc1..example` | Set in root `.env`. | Set as a runtime environment variable. | OCI Enterprise AI project identifier passed to the OpenAI-compatible client. |
| `OCI_MODEL_ID` | Yes | `openai.gpt-5.4` | Set in root `.env`. | Set as a runtime environment variable. | Model identifier selected from the supported OCI Enterprise AI model catalog. |
| `OCI_VECTOR_STORE_ID` | Yes | `vs_...` | Set in root `.env`. | Set as a runtime environment variable. | Vector store identifier used by the Responses API `file_search` tool. |
| `OCI_AUTH_MODE` | No | `openai_api_key` | Usually omitted for local API-key testing. Set only when testing OCI IAM auth. | Set to `resource_principal` for OCI-native Hosted Application deployments that should avoid OpenAI-compatible API keys. | Accepted agent runtime values: `openai_api_key`, `resource_principal`, `config_file`. Default: `openai_api_key`. |
| `OPENAI_API_KEY` | Only when `OCI_AUTH_MODE=openai_api_key` | `sk-...` | Set in root `.env` for API-key mode. | Set only when using API-key mode, preferably through the most protected configuration mechanism available. | OpenAI-compatible API key created inside the OCI Enterprise AI project. Never log or commit this value. |
| `OCI_CONFIG_FILE` | Only when `OCI_AUTH_MODE=config_file` | `~/.oci/config` | Set when local config-file auth should use a non-default OCI config path. | Usually not used for Hosted Applications. | Used by OCI IAM config-file auth for Responses API and document ingestion. |
| `OCI_PROFILE` | Only when `OCI_AUTH_MODE=config_file` | `DEFAULT` | Set when local config-file auth should use a non-default profile. | Usually not used for Hosted Applications. | Used by OCI IAM config-file auth for Responses API and document ingestion. |
| `FILE_SEARCH_MAX_NUM_RESULTS` | No | `10` | Set in root `.env` when a non-default value is needed. | Set as a runtime environment variable when a non-default value is needed. | Maximum number of Vector Store file search results requested by the Responses API `file_search` tool. Accepted range: `1` to `50`. |
| `RESPONSES_TIMEOUT_SECONDS` | No | `60` | Set in root `.env` when a non-default value is needed. | Set as a runtime environment variable when a non-default value is needed. | Timeout in seconds for Responses API create and retrieve calls. Accepted range: `1` to `300`. |
| `STREAM_FINALIZATION_MODE` | No | `never` | Set in root `.env` when a non-default value is needed. | Set as a runtime environment variable when a non-default value is needed. | Controls whether streaming responses perform a post-stream retrieve call to complete references and token usage. Accepted values: `never`, `auto`, `always`. |
| `SPEECH_TO_TEXT_ENABLED` | No | `true` | Set in root `.env` only when voice request intake should be disabled. | Set as a runtime environment variable only when voice request intake should be disabled. | Enables `POST /responses/audio`. |
| `AUDIO_UPLOAD_MAX_SIZE_MB` | No | `25` | Set in root `.env` when a non-default local audio upload limit is needed. | Set as a runtime environment variable when a non-default hosted audio upload limit is needed. | Maximum accepted upload size for `POST /responses/audio`. Accepted range: `1` to `100`. |
| `OCI_SPEECH_MODEL` | No | `whisper-medium` | Set in root `.env` when selecting a non-default speech model. | Set as a runtime environment variable when selecting a non-default speech model. | Accepted values: `whisper-medium`, `whisper-large-v3-turbo`. The latter maps internally to OCI Speech model type `WHISPER_LARGE_V3T`. |
| `OCI_SPEECH_LANGUAGE_CODE` | No | `auto` | Set in root `.env` when a fixed transcription language is needed. | Set as a runtime environment variable when a fixed transcription language is needed. | Default `auto` lets Whisper identify the language. |
| `OCI_SPEECH_STAGING_NAMESPACE` | Yes when using `/responses/audio` | `mytenancynamespace` | Set in root `.env`. | Set as a runtime environment variable. | Object Storage namespace for staged audio and transcript output. |
| `OCI_SPEECH_STAGING_BUCKET` | Yes when using `/responses/audio` | `rag-agent-speech-staging` | Set in root `.env`. | Set as a runtime environment variable. | Object Storage bucket for staged audio and transcript output. |
| `OCI_SPEECH_INPUT_PREFIX` | No | `speech-input` | Set in root `.env` when a non-default prefix is needed. | Set as a runtime environment variable when a non-default prefix is needed. | Object Storage prefix for uploaded audio. |
| `OCI_SPEECH_OUTPUT_PREFIX` | No | `speech-output` | Set in root `.env` when a non-default prefix is needed. | Set as a runtime environment variable when a non-default prefix is needed. | Object Storage prefix for OCI Speech transcript output. |
| `AUDIO_TRANSCRIPTION_TIMEOUT_SECONDS` | No | `120` | Set in root `.env` when a non-default timeout is needed. | Set as a runtime environment variable when a non-default timeout is needed. | Maximum time to wait for one OCI Speech transcription task. |
| `AUDIO_TRANSCRIPTION_POLL_INTERVAL_SECONDS` | No | `2` | Set in root `.env` when a non-default polling interval is needed. | Set as a runtime environment variable when a non-default polling interval is needed. | Poll interval for OCI Speech transcription task status. |
| `OCI_SPEECH_WHISPER_PROMPT` | No | empty | Set in root `.env` only when a Whisper prompt is needed. | Set as a runtime environment variable only when a Whisper prompt is needed. | Optional Whisper transcription prompt. Do not put secrets here. |
| `EVAL_SOURCE_NAMESPACE` | Yes for golden dataset generation | `mytenancynamespace` | Set in root `.env` before running `python -m management.evals.generate_golden_dataset`. | Usually not used by the agent runtime. | Object Storage namespace containing source PDFs for evaluation dataset generation. |
| `EVAL_SOURCE_BUCKET` | Yes for golden dataset generation | `rag-documents` | Set in root `.env` before running the golden dataset generator. | Usually not used by the agent runtime. | Object Storage bucket containing source PDFs for evaluation dataset generation. |
| `EVAL_SOURCE_PREFIX` | No | `product-docs/` | Set in root `.env` when only a subset of source PDFs should be scanned. | Usually not used by the agent runtime. | Optional Object Storage prefix for source PDF discovery. |
| `EVAL_GOLDEN_DATASET_PATH` | Yes for golden dataset generation | `evals/datasets/golden_dataset.jsonl` | Set in root `.env` before running the golden dataset generator. | Usually not used by the agent runtime. | Target JSONL output path. Real generated datasets under `evals/datasets/` are gitignored by default. |
| `EVAL_OCI_REGION` | Yes for golden dataset generation | `us-chicago-1` | Set in root `.env` before running the golden dataset generator. | Usually not used by the agent runtime. | Evaluation model region. This is intentionally separate from `OCI_REGION`. |
| `EVAL_OCI_COMPARTMENT_ID` | Yes for golden dataset generation | `ocid1.compartment.oc1..example` | Set in root `.env` before running the golden dataset generator. | Usually not used by the agent runtime. | Evaluation model compartment. This is intentionally separate from `OCI_COMPARTMENT_ID`. |
| `EVAL_OCI_PROJECT_ID` | Yes for golden dataset generation | `ocid1.generativeaiproject.oc1..example` | Set in root `.env` before running the golden dataset generator. | Usually not used by the agent runtime. | Evaluation model project. This is intentionally separate from `OCI_PROJECT_ID`. |
| `EVAL_OCI_MODEL_ID` | Yes for golden dataset generation | `openai.gpt-5.4` | Set in root `.env` before running the golden dataset generator. | Usually not used by the agent runtime. | Model used to generate golden questions and expected answers. The generator does not fall back to `OCI_MODEL_ID`. |
| `EVAL_MAX_PAGES_PER_PDF` | No | `10` | Set in root `.env` when a non-default page selection limit is needed. | Usually not used by the agent runtime. | Maximum significant pages selected per source PDF. |
| `EVAL_GENERATION_TEMPERATURE` | No | `0` | Set in root `.env` when a non-default generation temperature is needed. | Usually not used by the agent runtime. | Temperature for LLM-generated golden questions and expected answers. When set to `0`, the generator omits the Responses API `temperature` parameter for model compatibility. |
| `LANGFUSE_ENABLED` | No | `false` | Set in root `.env` only when Langfuse observability is needed. | Set as a runtime environment variable only when Langfuse observability is needed. | Enables optional Langfuse tracing for Responses API calls. Accepted true values: `true`, `1`, `yes`, `on`. Accepted false values: `false`, `0`, `no`, `off`. |
| `LANGFUSE_BASE_URL` | Only when `LANGFUSE_ENABLED=true` | `https://cloud.langfuse.com` | Set in root `.env` when Langfuse is enabled. | Set as a runtime environment variable when Langfuse is enabled. | Base URL of the Langfuse instance. |
| `LANGFUSE_PUBLIC_KEY` | Only when `LANGFUSE_ENABLED=true` | `pk-lf-...` | Set in root `.env` when Langfuse is enabled. | Set as a runtime environment variable when Langfuse is enabled. | Langfuse public key. Avoid logging full values. |
| `LANGFUSE_SECRET_KEY` | Only when `LANGFUSE_ENABLED=true` | `sk-lf-...` | Set in root `.env` when Langfuse is enabled. | Set as a runtime environment variable when Langfuse is enabled, preferably through the most protected configuration mechanism available. | Langfuse secret key. Never log or commit this value. |
| `IDENTITY_DOMAIN_URL` | Client only | `https://idcs-example.identity.oraclecloud.com` | Set in root `.env` when the Python CLI client must request an IDCS token. Enter manually in the reference UI when JWT authentication is enabled. | Not used by the agent runtime. | Exact Identity Domain URL from OCI Console for protected Hosted Application testing. |
| `CONFIDENTIAL_APPLICATION_ID` | Client only | `ocid-or-client-id` | Set in root `.env` when the Python CLI client must request an IDCS token. Enter manually in the reference UI when JWT authentication is enabled. | Not used by the agent runtime. | Confidential application client identifier. |
| `CONFIDENTIAL_APPLICATION_SECRET` | Client only | `secret` | Set in root `.env` when the Python CLI client must request an IDCS token. Enter manually in the reference UI when JWT authentication is enabled. | Not used by the agent runtime. | Confidential application client secret. Never log or commit this value. |
| `IDCS_SCOPE` | Client only | `hello_worldinvoke` | Set in root `.env` when the Python CLI client must request an IDCS token. Enter manually in the reference UI when JWT authentication is enabled. | Not used by the agent runtime. | OAuth scope requested by the client token request. For OCI IAM IDCS Hosted Application auth, this is usually the primary audience concatenated with the scope claim. |

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

## Langfuse Observability

Langfuse observability is disabled by default.

When `LANGFUSE_ENABLED=true`, the agent requires `LANGFUSE_BASE_URL`,
`LANGFUSE_PUBLIC_KEY`, and `LANGFUSE_SECRET_KEY`. The agent uses the
Langfuse-instrumented OpenAI-compatible client for Responses API calls and
groups observations by the active Responses API `conversation_id`.

When `LANGFUSE_ENABLED` is omitted or false, the agent uses the standard
OpenAI-compatible client and does not require Langfuse configuration.

## Region Consistency

The following values must refer to resources in the same OCI region:

- `OCI_REGION`
- `OCI_PROJECT_ID`
- `OCI_MODEL_ID`
- `OCI_VECTOR_STORE_ID`
- `OPENAI_API_KEY`, only when `OCI_AUTH_MODE=openai_api_key`

The Object Storage bucket used for knowledge base uploads and the Hosted Application deployment must also be created in the same region.

## Failure Impact

If one or more required variables are missing, the agent must fail request handling before calling the Responses API and return a structured error response.

If variables point to resources in different regions, the most common outcomes are authentication failures, project lookup failures, vector store lookup failures, or Responses API request errors.

If `OCI_AUTH_MODE=openai_api_key` and `OPENAI_API_KEY` is invalid or missing
required API key permissions, the agent cannot call OCI Enterprise AI.

If `OCI_AUTH_MODE=resource_principal`, the Hosted Application Resource Principal
must have IAM permissions for the configured OCI Enterprise AI project, model,
Vector Store, Object Storage bucket, and connector operations used by enabled
features.

If optional tuning variables are missing, the agent uses their defaults. If they
are present but invalid, the agent fails request handling before calling the
Responses API.

The IDCS client variables are used by client-side validation tools only. They do
not configure the local agent runtime. When all four variables are present and
the Python CLI runs with `--auth auto`, the CLI requests and prints an IDCS
access token before sending the test request. When a token is acquired, the CLI
sends it to the agent endpoint as an `Authorization: Bearer <token>` header.
The same client-side IDCS configuration is used by
`clients.document_ingestion_cli` for protected document ingestion endpoints.

The Next.js reference UI does not read these values from `.env`. For protected
Hosted Application testing, enter the same values in the UI after enabling
`JWT authentication`. The UI keeps the values and acquired access token in
browser memory and uses its server-side Next.js token route to call OCI IAM
Identity Domains.

Before using these values, create and activate a confidential application in OCI
IAM Identity Domains, enable the OAuth `Client credentials` grant, and record
the Client ID and Client secret. Oracle documents the setup in
[Adding a Confidential Application](https://docs.oracle.com/en-us/iaas/Content/Identity/applications/add-confidential-application.htm).

For the difference between Hosted Application `audience` and `scope` values and
the concatenated client-side `IDCS_SCOPE` value, see
[OCI IAM IDCS Audience And Scope](idcs-audience-and-scope.md).

## Security Rules

- Never commit `.env`.
- Never commit real API key values.
- Never commit real confidential application secrets.
- Never commit real Langfuse secret keys.
- Never print environment variables in logs.
- Never include full runtime configuration in error responses.
- Use `.env.sample` only for placeholder values.
- Rotate `OPENAI_API_KEY` and `LANGFUSE_SECRET_KEY` according to customer
  security requirements.
