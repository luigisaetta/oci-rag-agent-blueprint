# 0014 - Voice Agent Requests

## Status

Proposed.

## Purpose

Add a voice input path to the RAG agent so users can ask questions by speaking
in the reference UI. Speech-to-text is a server-side agent responsibility. The
browser records audio and uploads it to the agent; the agent transcribes the
audio with OCI Speech and then reuses the existing streaming Responses API
agent flow.

The feature must preserve the existing text request path. The UI chooses between
the existing text endpoint and the new audio endpoint depending on whether the
user sends typed text or recorded audio.

## External Service Basis

OCI Speech supports transcription jobs for media files stored in Object Storage.
The feature must therefore use an asynchronous OCI Speech transcription job
behind the agent endpoint, not a browser-side transcription path.

According to the OCI Speech documentation, supported media formats include:

- `AAC`
- `AC3`
- `AMR`
- `AU`
- `FLAC`
- `M4A`
- `MKV`
- `MP3`
- `MP4`
- `OGA`
- `OGG`
- `OPUS`
- `WAV`
- `WEBM`

The implementation must not advertise or accept audio formats outside the
formats supported by OCI Speech unless it explicitly transcodes them into a
supported format before submission.

For browser recording, the preferred format is `WEBM` with Opus audio because
it is the most natural format produced by the browser `MediaRecorder` API on
modern Chromium-based browsers and is supported by OCI Speech. `WAV` remains a
supported upload format for manual clients and browsers that provide it.

## Goals

- Add a server-side audio request endpoint that accepts an uploaded audio file,
  transcribes it with OCI Speech, and streams the agent answer.
- Keep speech-to-text credentials, Object Storage staging, and OCI Speech job
  orchestration on the server side.
- Return the transcription to the client before answer tokens are streamed.
- Enable speech-to-text by default.
- Add a microphone workflow to the Next.js reference UI.
- Reuse the current conversation behavior, streaming SSE format, schema
  validation, references, and token usage events wherever possible.
- Keep the feature testable with mocked OCI Speech and Object Storage clients.

## Non-Goals

- Browser-side speech recognition.
- Real-time partial transcription while the user is still speaking.
- Voice output or text-to-speech responses.
- Audio diarization in the first implementation.
- Long-form audio processing beyond short user questions.
- A separate conversation model for voice requests.

## Endpoint Contract

The agent must expose:

```text
POST /responses/audio
```

The endpoint accepts `multipart/form-data`.

Required form fields:

| Field | Type | Description |
| --- | --- | --- |
| `file` | file | Audio file to transcribe. |
| `new_conversation` | boolean | Same meaning as `/responses`. |

Optional form fields:

| Field | Type | Description |
| --- | --- | --- |
| `conversation_id` | string | Required when `new_conversation=false`. |
| `user_id` | string | Passed through to the agent request payload. |
| `user_role` | string | Passed through to the agent request payload. |
| `stream` | boolean | Defaults to `true`. Initial implementation should support only streaming responses and reject `stream=false` unless non-streaming audio behavior is explicitly implemented. |
| `language_code` | string | Optional per-request override for OCI Speech language code. |

The endpoint must validate the form payload before uploading audio or starting
an OCI Speech job.

## Streaming Response Contract

The successful response must use `text/event-stream`.

The first successful semantic event must be:

```text
event: transcript
data: {"text": "<transcribed user request>"}
```

After the `transcript` event, the endpoint must stream the same event sequence
used by `/responses`:

- `metadata`
- `token`
- `references`
- `usage`
- `done`
- `error`

The hosted gateway compatibility rule still applies: clients must tolerate
SSE streams where explicit `event:` names are stripped and infer the event type
from JSON keys. For the stripped hosted shape, a payload containing only
`transcript` must be interpreted as the transcript event:

```text
data: {"transcript": "<transcribed user request>"}
```

To support both direct and hosted shapes, the named event payload may include
both keys:

```json
{
  "text": "What documents mention retention?",
  "transcript": "What documents mention retention?"
}
```

The UI must display the transcript as the user's message before or while the
assistant response streams.

## Audio Validation

Accepted extensions and media types must be limited to OCI Speech supported
formats. The first implementation should explicitly accept:

| Extension | Expected media types |
| --- | --- |
| `.webm` | `audio/webm`, `video/webm` |
| `.opus` | `audio/opus`, `audio/ogg` |
| `.wav` | `audio/wav`, `audio/x-wav`, `audio/wave` |
| `.mp3` | `audio/mpeg`, `audio/mp3` |
| `.m4a` | `audio/mp4`, `audio/x-m4a` |
| `.mp4` | `audio/mp4`, `video/mp4` |
| `.ogg` | `audio/ogg`, `application/ogg` |
| `.oga` | `audio/ogg` |
| `.flac` | `audio/flac`, `audio/x-flac` |
| `.aac` | `audio/aac`, `audio/x-aac` |
| `.amr` | `audio/amr` |
| `.au` | `audio/basic` |
| `.ac3` | `audio/ac3`, `audio/vnd.dolby.dd-raw` |
| `.mkv` | `video/x-matroska` |

Validation must reject:

- Missing file.
- Empty file.
- Unsupported extension.
- Unsupported media type when a media type is provided.
- Files larger than the configured maximum.
- `new_conversation=false` without `conversation_id`.
- Empty transcription results.

The default upload size limit is intentionally smaller than OCI Speech service
limits because this feature is for spoken questions, not batch transcription.

## Server-Side Flow

For each valid audio request, the backend must:

1. Load and validate speech-to-text settings.
2. Read the uploaded audio file and enforce size and format limits.
3. Upload the audio to the configured Object Storage staging bucket.
4. Create an OCI Speech transcription job using the configured Whisper model.
5. Poll the transcription job until it reaches a terminal state or the
   configured timeout expires.
6. Read the generated transcript from Object Storage.
7. Emit the transcript SSE event.
8. Build the same validated request payload used by `/responses`, replacing
   `user_request` with the transcript.
9. Call the existing agent streaming implementation directly, not through an
   internal HTTP request.
10. Stream the resulting agent events to the client.

Temporary Object Storage objects should use collision-resistant names and a
configurable prefix. The implementation may leave staged audio and transcript
objects in Object Storage for auditability in the first version, but retention
behavior must be documented.

## OCI Authentication

The feature must use the existing `OCI_AUTH_MODE` setting:

- `resource_principal`: intended for OCI Hosted Application deployments.
- `config_file`: intended for local Docker Compose testing.

`openai_api_key` cannot authenticate Object Storage and OCI Speech operations.
If speech-to-text is enabled and the selected operation requires OCI SDK
clients, requests must fail fast with a clear configuration error when
`OCI_AUTH_MODE=openai_api_key`.

Local Docker Compose testing requires mounting the local OCI config directory
into the backend container and setting `OCI_CONFIG_FILE` and `OCI_PROFILE`.

## Object Storage And IAM Requirements

The speech-to-text feature requires a dedicated Object Storage staging location.
Deployers must provide both:

- The Object Storage namespace.
- The Object Storage bucket name.

These values are configured through `OCI_SPEECH_STAGING_NAMESPACE` and
`OCI_SPEECH_STAGING_BUCKET`. The bucket must exist before audio requests are
sent. It must be in a region supported by OCI Speech and should be in the same
region as the agent runtime and Speech job configuration to avoid cross-region
operational surprises.

The configured principal must have policies that allow both Object Storage and
OCI Speech operations.

For local Docker Compose testing with `OCI_AUTH_MODE=config_file`, the OCI user
or group associated with the selected `OCI_PROFILE` must be allowed to:

- Upload staged audio objects to the configured bucket.
- Read transcript result objects from the configured bucket.
- Optionally delete staged input and output objects if cleanup is implemented.
- Create, inspect, and manage OCI Speech transcription jobs in the configured
  compartment.

For hosted deployments with `OCI_AUTH_MODE=resource_principal`, the Hosted
Application resource principal must be matched by an OCI Dynamic Group, and
that Dynamic Group must be granted equivalent Object Storage and Speech
permissions.

Policy wording is tenancy-specific, but the required capability shape is:

```text
Allow group <local-user-group> to manage objects in compartment <compartment>
  where target.bucket.name = '<speech-staging-bucket>'

Allow group <local-user-group> to manage ai-service-speech-family in compartment <compartment>

Allow dynamic-group <hosted-application-dynamic-group> to manage objects in compartment <compartment>
  where target.bucket.name = '<speech-staging-bucket>'

Allow dynamic-group <hosted-application-dynamic-group> to manage ai-service-speech-family in compartment <compartment>
```

The final implementation documentation must verify the exact OCI IAM resource
type names for Speech policies and use the narrowest resource types and verbs
that support creating transcription jobs, polling status, and reading results.

## Configuration

Speech-to-text is enabled by default.

| Variable | Default | Required | Description |
| --- | --- | --- | --- |
| `SPEECH_TO_TEXT_ENABLED` | `true` | No | Enables `POST /responses/audio`. |
| `OCI_SPEECH_MODEL` | `whisper-medium` | No | Whisper model selection. Accepted blueprint values are `whisper-medium` and `whisper-large-v3-turbo`. Implementation must map these values to the exact OCI SDK/API model identifiers. |
| `OCI_SPEECH_LANGUAGE_CODE` | `auto` | No | Default OCI Speech language code. Whisper supports language identification with `auto`. |
| `OCI_SPEECH_COMPARTMENT_ID` | `OCI_COMPARTMENT_ID` | No | Compartment used for Speech jobs when different from the agent compartment. |
| `OCI_SPEECH_STAGING_NAMESPACE` | none | Yes when audio endpoint is used | Object Storage namespace for staged audio and transcript results. |
| `OCI_SPEECH_STAGING_BUCKET` | none | Yes when audio endpoint is used | Object Storage bucket used for Speech input and output. |
| `OCI_SPEECH_INPUT_PREFIX` | `speech-input` | No | Prefix for uploaded audio objects. |
| `OCI_SPEECH_OUTPUT_PREFIX` | `speech-output` | No | Prefix for transcription output objects. |
| `AUDIO_UPLOAD_MAX_SIZE_MB` | `25` | No | Maximum accepted audio upload size for voice questions. |
| `AUDIO_TRANSCRIPTION_TIMEOUT_SECONDS` | `120` | No | Maximum time to wait for one transcription job. |
| `AUDIO_TRANSCRIPTION_POLL_INTERVAL_SECONDS` | `2` | No | Poll interval for transcription status. |
| `OCI_SPEECH_WHISPER_PROMPT` | empty | No | Optional Whisper prompt passed through OCI Speech additional settings when configured. |

`OCI_SPEECH_MODEL` defaults to `whisper-medium`. `whisper-large-v3-turbo` must be
supported as a configurable option. If OCI uses a different exact identifier for
Large V3 Turbo, the implementation must keep the public environment value stable
and perform the mapping internally.

## UI Requirements

The Next.js reference UI must:

- Keep typed text input and existing `/responses` behavior unchanged.
- Add a microphone control using the browser `MediaRecorder` API.
- Prefer `audio/webm;codecs=opus` when supported.
- Allow recording start, stop, cancel, and send.
- Show clear states for recording, transcribing, and streaming.
- Handle missing microphone permission and unavailable `MediaRecorder`.
- Send recorded audio to `/responses/audio` as multipart form data.
- Include the current conversation fields in the audio request.
- Include the same Bearer token behavior used for protected hosted text
  requests.
- Display the transcript as the user message as soon as the transcript SSE event
  arrives.
- Continue streaming assistant tokens into the assistant message exactly as the
  text request path does.

The UI must not expose OCI Speech credentials or Object Storage configuration.

## Diagnostics

The runtime environment diagnostic endpoint may expose non-secret speech
configuration values:

- `SPEECH_TO_TEXT_ENABLED`
- `OCI_SPEECH_MODEL`
- `OCI_SPEECH_LANGUAGE_CODE`
- `AUDIO_UPLOAD_MAX_SIZE_MB`
- `AUDIO_TRANSCRIPTION_TIMEOUT_SECONDS`

It must not expose bucket names, namespace values, object prefixes, or prompts
unless those values are explicitly classified as safe in a future specification.

## Error Handling

The audio endpoint must return structured errors.

Expected cases:

- `404` when `SPEECH_TO_TEXT_ENABLED=false`.
- `400` for invalid form fields, unsupported audio format, missing file, empty
  file, or missing conversation id.
- `413` for audio files larger than the configured limit.
- `500` for missing or invalid speech-to-text configuration.
- `502` for OCI Speech, Object Storage, or transcript retrieval failures.
- `504` when transcription does not complete before the configured timeout.

If transcription fails after the SSE response has started, the endpoint must
emit an `error` event and stop streaming.

## Security

- Audio files may contain sensitive user speech and must be treated as
  confidential input.
- Logs must not contain raw transcripts, raw audio bytes, Object Storage
  pre-authenticated URLs, or secret configuration values.
- Logs may include request ids, object names, job ids, lifecycle states, file
  sizes, and sanitized error summaries.
- The backend must use server-side OCI authentication only.
- The UI must not call OCI Speech directly.

## Documentation

Documentation updates must cover:

- `/responses/audio` endpoint usage.
- Supported audio formats.
- Local Docker Compose config-file authentication requirements.
- Required Object Storage staging namespace and bucket name.
- Required Object Storage and OCI Speech IAM policies for both local
  config-file authentication and hosted Resource Principal authentication.
- Speech-to-text environment variables.
- UI microphone workflow.
- Hosted Application Resource Principal requirements.

## Test Expectations

Backend tests must cover:

- Speech settings defaults and validation.
- Accepted and rejected audio formats.
- Missing, empty, and oversized audio uploads.
- Disabled endpoint behavior.
- `config_file` and `resource_principal` client construction using mocked OCI
  modules.
- Successful transcription followed by transcript-first SSE streaming.
- Empty transcription rejection.
- Transcription timeout.
- OCI Speech and Object Storage failure mapping.
- Conversation validation for audio requests.

UI tests must cover:

- Audio endpoint URL derivation from the configured backend `/responses` URL.
- Transcript SSE event parsing, including hosted gateway stripped-event shape.
- Microphone unavailable or permission-denied state.
- Multipart request construction with conversation and auth fields.
- Text sending remaining unchanged.

## Acceptance Criteria

- A user can record a voice question in the reference UI and receive a streaming
  RAG answer.
- The UI displays the transcribed question before answer tokens stream.
- The text endpoint and typed-input UI behavior remain backward compatible.
- The backend transcribes audio through OCI Speech using a configurable Whisper
  model, defaulting to `whisper-medium`.
- `whisper-large-v3-turbo` can be selected by environment variable.
- Local Docker Compose testing works with `OCI_AUTH_MODE=config_file`.
- Hosted deployment works with `OCI_AUTH_MODE=resource_principal`, assuming IAM
  policies allow Object Storage and Speech operations.
- The deployment documentation names the required Object Storage namespace,
  bucket, and IAM policy requirements before users attempt voice requests.
- Unit tests pass with coverage above the repository threshold.
- Documentation and changelog entries are updated.
