# Agent API Usage

This guide shows which endpoint to call and which payload to send when invoking
the RAG agent directly.

The same `/responses` API supports both non-streaming and streaming requests.

Agent-managed document ingestion also exposes `/documents/ingestions` endpoints
when `DOCUMENT_INGESTION_ENABLED=true`.

Voice request intake also exposes `/responses/audio` when
`SPEECH_TO_TEXT_ENABLED=true`. The implementation accepts and validates audio
uploads, transcribes them with OCI Speech, emits the transcript event, and
streams a fixed fake answer. The next implementation step will connect the
transcript to the real RAG agent response path.

## Endpoints

For a local backend, use:

```text
http://localhost:8080/responses
```

For an OCI Hosted Application deployment, use:

```text
https://inference.generativeai.<region>.oci.oraclecloud.com/20251112/hostedApplications/<hosted-application-ocid>/actions/invoke/responses
```

Replace:

- `<region>` with the OCI region, for example `eu-frankfurt-1`.
- `<hosted-application-ocid>` with the Hosted Application OCID.

The health endpoint uses the same base path with `health` instead of
`responses`:

```text
http://localhost:8080/health
```

```text
https://inference.generativeai.<region>.oci.oraclecloud.com/20251112/hostedApplications/<hosted-application-ocid>/actions/invoke/health
```

The document ingestion endpoints use the same base path:

```text
http://localhost:8080/documents/ingestions
http://localhost:8080/documents/ingestions/<job-id>
```

```text
https://inference.generativeai.<region>.oci.oraclecloud.com/20251112/hostedApplications/<hosted-application-ocid>/actions/invoke/documents/ingestions
https://inference.generativeai.<region>.oci.oraclecloud.com/20251112/hostedApplications/<hosted-application-ocid>/actions/invoke/documents/ingestions/<job-id>
```

The voice request endpoint uses the same base path:

```text
http://localhost:8080/responses/audio
```

```text
https://inference.generativeai.<region>.oci.oraclecloud.com/20251112/hostedApplications/<hosted-application-ocid>/actions/invoke/responses/audio
```

## New Conversation

Set `new_conversation` to `true` when starting a new conversation.

```json
{
  "new_conversation": true,
  "user_request": "Answer with only: ok",
  "stream": false
}
```

The response includes the new `conversation_id`. Store it if you want to
continue the same conversation later.

## Existing Conversation

Set `new_conversation` to `false` and pass the existing `conversation_id`.

```json
{
  "new_conversation": false,
  "conversation_id": "conv_fra_example",
  "user_request": "Continue from the previous answer.",
  "stream": false
}
```

## Non-Streaming Request

Use `stream: false` to receive one JSON response.

```bash
curl -s \
  -H "Content-Type: application/json" \
  -H "Accept: application/json" \
  -d '{"new_conversation":true,"user_request":"Answer with only: ok","stream":false}' \
  "http://localhost:8080/responses"
```

The response shape is:

```json
{
  "conversation_id": "conv_fra_example",
  "response_id": "resp_fra_example",
  "agent_response": "ok",
  "references": [],
  "usage": {
    "input_tokens": 100,
    "output_tokens": 10,
    "total_tokens": 110,
    "reasoning_tokens": 0
  },
  "error": null
}
```

## Streaming Request

Use `stream: true` and request `text/event-stream`.

```bash
curl -N \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -d '{"new_conversation":true,"user_request":"Answer with only: ok","stream":true}' \
  "http://localhost:8080/responses"
```

When the client connects directly to the FastAPI backend, the server emits named
SSE events:

```text
event: metadata
data: {"conversation_id": "conv_fra_example"}

event: token
data: {"text": "ok"}

event: references
data: {"references": []}

event: usage
data: {"usage": {"input_tokens": 100, "output_tokens": 10, "total_tokens": 110, "reasoning_tokens": 0}}

event: done
data: {"conversation_id": "conv_fra_example"}
```

When the same endpoint is invoked through OCI Hosted Application invoke, the
gateway may preserve the `data:` frames but strip the explicit `event:` lines.
Clients should therefore also support this equivalent shape:

```text
data: {"conversation_id": "conv_fra_example"}

data: {"text": "ok"}

data: {"references": []}

data: {"usage": {"input_tokens": 100, "output_tokens": 10, "total_tokens": 110, "reasoning_tokens": 0}}

data: {"conversation_id": "conv_fra_example"}
```

In that hosted shape, infer the event type from the JSON payload:

- `conversation_id` before metadata has been shown: `metadata`.
- `transcript`: `transcript`.
- `text`: `token`.
- `references`: `references`.
- `usage`: `usage`.
- `error`: `error`.
- `conversation_id` after metadata has been shown: `done`.

Clients should stop reading the stream after `done` or `error`, because hosted
gateways may keep the HTTP connection open after the useful response frames have
already been delivered.

## Audio Request

Use `POST /responses/audio` to submit a recorded voice question. The endpoint
currently transcribes multipart audio input with OCI Speech and returns a fake
assistant response.

```bash
curl -N \
  -H "Accept: text/event-stream" \
  -F "new_conversation=true" \
  -F "stream=true" \
  -F "file=@./question.webm;type=audio/webm" \
  "http://localhost:8080/responses/audio"
```

The stream starts with a real transcript event and then follows the normal
streaming response event sequence:

```text
event: transcript
data: {"text": "<transcribed user request>", "transcript": "<transcribed user request>"}

event: metadata
data: {"conversation_id": "conv-audio-new"}

event: token
data: {"text": "Audio input was received successfully. Server-side transcription will be connected in the next implementation step."}
```

Supported upload extensions are aligned with OCI Speech supported formats:
`.aac`, `.ac3`, `.amr`, `.au`, `.flac`, `.m4a`, `.mkv`, `.mp3`, `.mp4`, `.oga`,
`.ogg`, `.opus`, `.wav`, and `.webm`.

Local Docker Compose testing requires `OCI_AUTH_MODE=config_file`, a mounted OCI
config directory, and `OCI_SPEECH_STAGING_NAMESPACE` /
`OCI_SPEECH_STAGING_BUCKET` values pointing to an Object Storage bucket that the
configured OCI profile can use. Hosted deployments should use
`OCI_AUTH_MODE=resource_principal` with policies for Object Storage and OCI
Speech.

## Python CLI

The repository includes a Python test client that already handles both local and
hosted streaming shapes.

Non-streaming:

```bash
python -m clients.agent_cli \
  --endpoint "http://localhost:8080/responses" \
  --create-conversation true \
  --stream false \
  "Answer with only: ok"
```

Streaming:

```bash
python -m clients.agent_cli \
  --endpoint "http://localhost:8080/responses" \
  --create-conversation true \
  --stream true \
  "Answer with only: ok"
```

## Document Ingestion CLI

The repository also includes a client for the agent-managed connector ingestion
endpoints. It uploads one or more local files to the agent, starts one connector
file sync job, and can poll the job status.

Submit three files to a local agent:

```bash
python -m clients.document_ingestion_cli \
  --base-url "http://localhost:8080" \
  submit \
  --file ./docs/guide.pdf \
  --file ./docs/faq.md \
  --file ./docs/notes.txt \
  --prefix product-docs \
  --sync-display-name "manual-doc-ingestion" \
  --wait
```

Read job status:

```bash
python -m clients.document_ingestion_cli \
  --base-url "http://localhost:8080" \
  status "ocid1.generativeaivectorconnectorfilesync.oc1..example"
```

For Hosted Applications, pass the invoke base URL up to `actions/invoke`:

```bash
python -m clients.document_ingestion_cli \
  --base-url "https://inference.generativeai.<region>.oci.oraclecloud.com/20251112/hostedApplications/<hosted-application-ocid>/actions/invoke" \
  submit \
  --file ./docs/guide.pdf \
  --wait
```

When the Hosted Application is protected by IDCS authentication, the CLI reuses
the same `--auth`, `--env-file`, and IDCS environment variables as
`clients.agent_cli`.
