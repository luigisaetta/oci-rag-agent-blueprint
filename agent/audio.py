"""
Author: L. Saetta
Date last modified: 2026-06-26
License: MIT
Description: Audio request validation, OCI Speech transcription, and voice response streaming.
"""

from __future__ import annotations

# pylint: disable=too-many-instance-attributes

import json
import time
from dataclasses import dataclass
from os import environ
from pathlib import Path
from typing import Any, AsyncIterator, BinaryIO
from uuid import uuid4

from agent.config import load_optional_choice_env

AUDIO_UPLOAD_MAX_SIZE_MB_DEFAULT = 25
AUDIO_UPLOAD_MAX_SIZE_MB_MIN = 1
AUDIO_UPLOAD_MAX_SIZE_MB_MAX = 100
AUDIO_TRANSCRIPTION_TIMEOUT_SECONDS_DEFAULT = 120
AUDIO_TRANSCRIPTION_TIMEOUT_SECONDS_MIN = 1
AUDIO_TRANSCRIPTION_TIMEOUT_SECONDS_MAX = 900
AUDIO_TRANSCRIPTION_POLL_INTERVAL_SECONDS_DEFAULT = 2
AUDIO_TRANSCRIPTION_POLL_INTERVAL_SECONDS_MIN = 1
AUDIO_TRANSCRIPTION_POLL_INTERVAL_SECONDS_MAX = 30
SPEECH_TO_TEXT_ENABLED_DEFAULT = True
BOOLEAN_TRUE_VALUES = frozenset({"true", "1", "yes", "on"})
BOOLEAN_FALSE_VALUES = frozenset({"false", "0", "no", "off"})
OCI_AUTH_MODE_DEFAULT = "openai_api_key"
OCI_AUTH_MODES = frozenset({"openai_api_key", "resource_principal", "config_file"})
OCI_SPEECH_MODEL_DEFAULT = "whisper-medium"
OCI_SPEECH_MODELS = frozenset({"whisper-medium", "whisper-large-v3-turbo"})
OCI_SPEECH_MODEL_TYPE_MAP = {
    "whisper-medium": "WHISPER_MEDIUM",
    "whisper-large-v3-turbo": "WHISPER_LARGE_V3_TURBO",
}
OCI_SPEECH_LANGUAGE_CODE_DEFAULT = "auto"
OCI_SPEECH_INPUT_PREFIX_DEFAULT = "speech-input"
OCI_SPEECH_OUTPUT_PREFIX_DEFAULT = "speech-output"
FAKE_AGENT_RESPONSE = (
    "Audio input was received successfully. Server-side transcription will be "
    "connected to the RAG agent in the next implementation step."
)

SUPPORTED_AUDIO_TYPES = {
    ".aac": frozenset({"audio/aac", "audio/x-aac"}),
    ".ac3": frozenset({"audio/ac3", "audio/vnd.dolby.dd-raw"}),
    ".amr": frozenset({"audio/amr"}),
    ".au": frozenset({"audio/basic"}),
    ".flac": frozenset({"audio/flac", "audio/x-flac"}),
    ".m4a": frozenset({"audio/mp4", "audio/x-m4a"}),
    ".mkv": frozenset({"video/x-matroska"}),
    ".mp3": frozenset({"audio/mpeg", "audio/mp3"}),
    ".mp4": frozenset({"audio/mp4", "video/mp4"}),
    ".oga": frozenset({"audio/ogg"}),
    ".ogg": frozenset({"audio/ogg", "application/ogg"}),
    ".opus": frozenset({"audio/opus", "audio/ogg"}),
    ".wav": frozenset({"audio/wav", "audio/x-wav", "audio/wave"}),
    ".webm": frozenset({"audio/webm", "video/webm"}),
}


class AudioRequestError(Exception):
    """Raised when an audio request is invalid or disabled."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        """Initialize an audio request error.

        Args:
            message: Error message safe to return to the client.
            status_code: HTTP status code for the error.
        """

        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class AudioRequestSettings:
    """Runtime settings for voice request intake.

    Attributes:
        enabled: Whether the audio request endpoint is enabled.
        max_upload_size_mb: Maximum accepted audio file size in MiB.
        namespace: Object Storage namespace for staged audio and transcript output.
        bucket: Object Storage bucket for staged audio and transcript output.
        compartment_id: OCI compartment used for Speech jobs.
        model: Blueprint speech model selector.
        language_code: OCI Speech language code.
        input_prefix: Object Storage prefix for uploaded audio.
        output_prefix: Object Storage prefix for transcription output.
        timeout_seconds: Maximum time to wait for transcription completion.
        poll_interval_seconds: Poll interval for transcription task status.
        whisper_prompt: Optional Whisper prompt passed to OCI Speech.
    """

    enabled: bool = SPEECH_TO_TEXT_ENABLED_DEFAULT
    max_upload_size_mb: int = AUDIO_UPLOAD_MAX_SIZE_MB_DEFAULT
    namespace: str = ""
    bucket: str = ""
    compartment_id: str = ""
    model: str = OCI_SPEECH_MODEL_DEFAULT
    language_code: str = OCI_SPEECH_LANGUAGE_CODE_DEFAULT
    input_prefix: str = OCI_SPEECH_INPUT_PREFIX_DEFAULT
    output_prefix: str = OCI_SPEECH_OUTPUT_PREFIX_DEFAULT
    timeout_seconds: int = AUDIO_TRANSCRIPTION_TIMEOUT_SECONDS_DEFAULT
    poll_interval_seconds: int = AUDIO_TRANSCRIPTION_POLL_INTERVAL_SECONDS_DEFAULT
    whisper_prompt: str = ""

    @property
    def max_upload_size_bytes(self) -> int:
        """Return the maximum accepted audio upload size in bytes.

        Returns:
            int: Maximum upload size in bytes.
        """

        return self.max_upload_size_mb * 1024 * 1024


@dataclass(frozen=True)
class RawAudioRequest:
    """Raw audio request form values and upload metadata before validation.

    Attributes:
        filename: Uploaded file name.
        content_type: Uploaded file media type.
        size_bytes: Uploaded file size.
        new_conversation: Raw form value for new conversation flag.
        conversation_id: Raw form value for conversation id.
        stream: Raw form value for stream flag.
    """

    filename: str
    content_type: str
    size_bytes: int
    new_conversation: str
    conversation_id: str
    stream: str


@dataclass(frozen=True)
class AudioRequest:
    """Validated audio request metadata.

    Attributes:
        filename: Uploaded file name.
        content_type: Uploaded file media type.
        size_bytes: Uploaded file size.
        new_conversation: Whether the request starts a new conversation.
        conversation_id: Optional existing conversation identifier.
    """

    filename: str
    content_type: str
    size_bytes: int
    new_conversation: bool
    conversation_id: str = ""


@dataclass(frozen=True)
class AudioTranscriptionClients:
    """OCI clients and model module used for audio transcription.

    Attributes:
        object_storage_client: OCI Object Storage client.
        speech_client: OCI AI Speech client.
        speech_models: OCI AI Speech models module.
    """

    object_storage_client: Any
    speech_client: Any
    speech_models: Any


def load_audio_request_settings() -> AudioRequestSettings:
    """Load audio request settings from environment variables.

    Returns:
        AudioRequestSettings: Validated audio request settings.

    Raises:
        ValueError: If configured values are invalid.
    """

    settings = AudioRequestSettings(
        enabled=_load_optional_bool(
            "SPEECH_TO_TEXT_ENABLED",
            SPEECH_TO_TEXT_ENABLED_DEFAULT,
        ),
        max_upload_size_mb=_load_optional_int(
            "AUDIO_UPLOAD_MAX_SIZE_MB",
            AUDIO_UPLOAD_MAX_SIZE_MB_DEFAULT,
            AUDIO_UPLOAD_MAX_SIZE_MB_MIN,
            AUDIO_UPLOAD_MAX_SIZE_MB_MAX,
        ),
        namespace=environ.get("OCI_SPEECH_STAGING_NAMESPACE", "").strip(),
        bucket=environ.get("OCI_SPEECH_STAGING_BUCKET", "").strip(),
        compartment_id=(
            environ.get("OCI_SPEECH_COMPARTMENT_ID")
            or environ.get("OCI_COMPARTMENT_ID", "")
        ).strip(),
        model=load_optional_choice_env(
            "OCI_SPEECH_MODEL",
            OCI_SPEECH_MODEL_DEFAULT,
            OCI_SPEECH_MODELS,
        ),
        language_code=environ.get(
            "OCI_SPEECH_LANGUAGE_CODE",
            OCI_SPEECH_LANGUAGE_CODE_DEFAULT,
        ).strip()
        or OCI_SPEECH_LANGUAGE_CODE_DEFAULT,
        input_prefix=environ.get(
            "OCI_SPEECH_INPUT_PREFIX",
            OCI_SPEECH_INPUT_PREFIX_DEFAULT,
        ).strip()
        or OCI_SPEECH_INPUT_PREFIX_DEFAULT,
        output_prefix=environ.get(
            "OCI_SPEECH_OUTPUT_PREFIX",
            OCI_SPEECH_OUTPUT_PREFIX_DEFAULT,
        ).strip()
        or OCI_SPEECH_OUTPUT_PREFIX_DEFAULT,
        timeout_seconds=_load_optional_int(
            "AUDIO_TRANSCRIPTION_TIMEOUT_SECONDS",
            AUDIO_TRANSCRIPTION_TIMEOUT_SECONDS_DEFAULT,
            AUDIO_TRANSCRIPTION_TIMEOUT_SECONDS_MIN,
            AUDIO_TRANSCRIPTION_TIMEOUT_SECONDS_MAX,
        ),
        poll_interval_seconds=_load_optional_int(
            "AUDIO_TRANSCRIPTION_POLL_INTERVAL_SECONDS",
            AUDIO_TRANSCRIPTION_POLL_INTERVAL_SECONDS_DEFAULT,
            AUDIO_TRANSCRIPTION_POLL_INTERVAL_SECONDS_MIN,
            AUDIO_TRANSCRIPTION_POLL_INTERVAL_SECONDS_MAX,
        ),
        whisper_prompt=environ.get("OCI_SPEECH_WHISPER_PROMPT", "").strip(),
    )

    if settings.enabled:
        missing_vars = [
            env_name
            for env_name, value in {
                "OCI_SPEECH_STAGING_NAMESPACE": settings.namespace,
                "OCI_SPEECH_STAGING_BUCKET": settings.bucket,
                "OCI_SPEECH_COMPARTMENT_ID or OCI_COMPARTMENT_ID": (
                    settings.compartment_id
                ),
            }.items()
            if not value
        ]
        if missing_vars:
            names = ", ".join(missing_vars)
            raise ValueError(
                "Missing required speech-to-text environment variables: " f"{names}"
            )

    return settings


def validate_audio_request(
    raw_request: RawAudioRequest,
    settings: AudioRequestSettings,
) -> AudioRequest:
    """Validate audio request form fields and upload metadata.

    Args:
        raw_request: Raw audio request form values and upload metadata.
        settings: Audio request settings.

    Returns:
        AudioRequest: Validated audio request metadata.

    Raises:
        AudioRequestError: If the endpoint is disabled or the request is invalid.
    """

    if not settings.enabled:
        raise AudioRequestError("Speech-to-text is not enabled.", status_code=404)
    if not raw_request.filename.strip():
        raise AudioRequestError("Audio file name is required.")
    if raw_request.size_bytes <= 0:
        raise AudioRequestError("Audio file is empty.")
    if raw_request.size_bytes > settings.max_upload_size_bytes:
        raise AudioRequestError("Audio file is larger than the configured limit.", 413)

    normalized_stream = _parse_bool(raw_request.stream, "stream")
    if not normalized_stream:
        raise AudioRequestError("Audio requests currently require stream=true.")

    normalized_new_conversation = _parse_bool(
        raw_request.new_conversation,
        "new_conversation",
    )
    clean_conversation_id = raw_request.conversation_id.strip()
    if not normalized_new_conversation and not clean_conversation_id:
        raise AudioRequestError(
            "conversation_id is required when new_conversation=false."
        )

    _validate_audio_type(raw_request.filename, raw_request.content_type)

    return AudioRequest(
        filename=raw_request.filename,
        content_type=raw_request.content_type,
        size_bytes=raw_request.size_bytes,
        new_conversation=normalized_new_conversation,
        conversation_id=clean_conversation_id,
    )


async def stream_fake_audio_response(
    audio_request: AudioRequest,
    transcript: str,
) -> AsyncIterator[str]:
    """Stream a transcript and fake assistant answer for audio intake.

    Args:
        audio_request: Validated audio request metadata.
        transcript: Transcribed user request.

    Yields:
        str: Server-Sent Events chunks.
    """

    conversation_id = (
        "conv-audio-new"
        if audio_request.new_conversation
        else audio_request.conversation_id
    )

    yield _format_sse(
        "transcript",
        {
            "text": transcript,
            "transcript": transcript,
        },
    )
    yield _format_sse("metadata", {"conversation_id": conversation_id})
    yield _format_sse("token", {"text": FAKE_AGENT_RESPONSE})
    yield _format_sse("references", {"references": []})
    yield _format_sse(
        "usage",
        {
            "usage": {
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "reasoning_tokens": 0,
            }
        },
    )
    yield _format_sse("done", {"conversation_id": conversation_id})


def build_oci_audio_transcription_clients() -> AudioTranscriptionClients:
    """Build OCI clients required for audio transcription.

    Returns:
        AudioTranscriptionClients: Object Storage and AI Speech clients.

    Raises:
        RuntimeError: If OCI SDK authentication cannot be initialized.
    """

    try:
        import oci  # pylint: disable=import-outside-toplevel
    except ImportError as exc:
        raise RuntimeError(
            "The oci package is required for audio transcription."
        ) from exc

    auth_mode = load_optional_choice_env(
        "OCI_AUTH_MODE",
        OCI_AUTH_MODE_DEFAULT,
        OCI_AUTH_MODES,
    )
    if auth_mode == "resource_principal":
        return _build_resource_principal_clients(oci)
    if auth_mode == "config_file":
        return _build_config_file_clients(oci)

    raise RuntimeError(
        "Speech-to-text requires OCI_AUTH_MODE to be resource_principal or "
        "config_file. openai_api_key cannot authenticate Object Storage or "
        "OCI Speech operations."
    )


def transcribe_audio(
    audio_request: AudioRequest,
    audio_body: BinaryIO,
    settings: AudioRequestSettings,
    clients: AudioTranscriptionClients,
) -> str:
    """Transcribe one uploaded audio file with OCI Speech.

    Args:
        audio_request: Validated audio request metadata.
        audio_body: File-like object containing uploaded audio.
        settings: Speech-to-text runtime settings.
        clients: OCI clients and model module.

    Returns:
        str: Transcribed text.

    Raises:
        RuntimeError: If upload, job creation, polling, or transcript parsing fails.
    """

    request_id = uuid4().hex
    audio_object_name = _build_object_name(
        settings.input_prefix,
        f"{request_id}{Path(audio_request.filename).suffix.lower()}",
    )
    output_prefix = _build_object_name(settings.output_prefix, request_id)

    clients.object_storage_client.put_object(
        namespace_name=settings.namespace,
        bucket_name=settings.bucket,
        object_name=audio_object_name,
        put_object_body=audio_body,
    )
    job = _create_transcription_job(
        audio_object_name,
        output_prefix,
        settings,
        clients.speech_client,
        clients.speech_models,
    )
    job_id = str(getattr(job, "id", ""))
    if not job_id:
        raise RuntimeError("OCI Speech did not return a transcription job id.")

    output_location = _wait_for_transcription_output(
        job_id,
        settings,
        clients.speech_client,
    )
    transcript_payload = _read_transcript_payload(
        output_location,
        settings,
        clients.object_storage_client,
    )
    transcript = _extract_transcript_text(transcript_payload).strip()
    if not transcript:
        raise RuntimeError("OCI Speech returned an empty transcript.")

    return transcript


def _build_resource_principal_clients(oci_module: Any) -> AudioTranscriptionClients:
    """Build OCI transcription clients with Resource Principal authentication."""

    try:
        signer = oci_module.auth.signers.get_resource_principals_signer()
    except Exception as exc:  # pylint: disable=broad-exception-caught
        raise RuntimeError(
            "Unable to initialize OCI Resource Principal authentication for "
            f"audio transcription: {exc}"
        ) from exc

    region = environ.get("OCI_REGION", "").strip()
    client_config = {"region": region} if region else {}
    return AudioTranscriptionClients(
        object_storage_client=oci_module.object_storage.ObjectStorageClient(
            client_config,
            signer=signer,
        ),
        speech_client=oci_module.ai_speech.AIServiceSpeechClient(
            client_config,
            signer=signer,
        ),
        speech_models=oci_module.ai_speech.models,
    )


def _build_config_file_clients(oci_module: Any) -> AudioTranscriptionClients:
    """Build OCI transcription clients from an OCI config file."""

    profile = environ.get("OCI_PROFILE", "DEFAULT")
    config_file = environ.get("OCI_CONFIG_FILE")
    try:
        if config_file:
            oci_config = oci_module.config.from_file(
                file_location=config_file,
                profile_name=profile,
            )
        else:
            oci_config = oci_module.config.from_file(profile_name=profile)
    except Exception as exc:  # pylint: disable=broad-exception-caught
        raise RuntimeError(f"Unable to load OCI SDK configuration: {exc}") from exc

    return AudioTranscriptionClients(
        object_storage_client=oci_module.object_storage.ObjectStorageClient(oci_config),
        speech_client=oci_module.ai_speech.AIServiceSpeechClient(oci_config),
        speech_models=oci_module.ai_speech.models,
    )


def _create_transcription_job(
    audio_object_name: str,
    output_prefix: str,
    settings: AudioRequestSettings,
    speech_client: Any,
    speech_models: Any,
) -> Any:
    """Create an OCI Speech transcription job for one staged audio object."""

    additional_settings = {}
    if settings.whisper_prompt:
        additional_settings["whisperPrompt"] = settings.whisper_prompt

    transcription_settings = None
    if additional_settings:
        transcription_settings = speech_models.TranscriptionSettings(
            additional_settings=additional_settings
        )

    model_details = speech_models.TranscriptionModelDetails(
        model_type=OCI_SPEECH_MODEL_TYPE_MAP[settings.model],
        domain="GENERIC",
        language_code=settings.language_code,
        transcription_settings=transcription_settings,
    )
    input_location = speech_models.ObjectListInlineInputLocation(
        location_type="OBJECT_LIST_INLINE_INPUT_LOCATION",
        object_locations=[
            speech_models.ObjectLocation(
                namespace_name=settings.namespace,
                bucket_name=settings.bucket,
                object_names=[audio_object_name],
            )
        ],
    )
    output_location = speech_models.OutputLocation(
        namespace_name=settings.namespace,
        bucket_name=settings.bucket,
        prefix=output_prefix,
    )
    details = speech_models.CreateTranscriptionJobDetails(
        display_name=f"rag-agent-audio-{uuid4().hex[:12]}",
        compartment_id=settings.compartment_id,
        model_details=model_details,
        input_location=input_location,
        output_location=output_location,
    )
    response = speech_client.create_transcription_job(details)
    return response.data


def _wait_for_transcription_output(
    job_id: str,
    settings: AudioRequestSettings,
    speech_client: Any,
) -> Any:
    """Poll OCI Speech until the first task reaches a terminal state."""

    deadline = time.monotonic() + settings.timeout_seconds
    last_state = ""
    while time.monotonic() < deadline:
        tasks_response = speech_client.list_transcription_tasks(job_id)
        tasks = list(getattr(tasks_response.data, "items", []) or [])
        if not tasks:
            time.sleep(settings.poll_interval_seconds)
            continue

        task = tasks[0]
        last_state = str(getattr(task, "lifecycle_state", "") or "")
        if last_state.upper() == "SUCCEEDED":
            task_id = str(getattr(task, "id", ""))
            if task_id:
                task_response = speech_client.get_transcription_task(task_id)
                full_task = task_response.data
            else:
                full_task = task
            output_location = getattr(full_task, "output_location", None)
            if output_location is None:
                raise RuntimeError("OCI Speech task did not include output location.")
            return output_location
        if last_state.upper() in {"FAILED", "CANCELED"}:
            details = getattr(task, "lifecycle_details", "") or "No details returned."
            raise RuntimeError(f"OCI Speech transcription failed: {details}")

        time.sleep(settings.poll_interval_seconds)

    raise TimeoutError(
        "OCI Speech transcription did not complete within "
        f"{settings.timeout_seconds} seconds. Last state: {last_state or 'unknown'}"
    )


def _read_transcript_payload(
    output_location: Any,
    settings: AudioRequestSettings,
    object_storage_client: Any,
) -> Any:
    """Read and parse the OCI Speech transcript JSON from Object Storage."""

    namespace = getattr(output_location, "namespace_name", "") or settings.namespace
    bucket = getattr(output_location, "bucket_name", "") or settings.bucket
    object_names = list(getattr(output_location, "object_names", []) or [])
    object_name = ""
    for candidate in object_names:
        if str(candidate).lower().endswith(".json"):
            object_name = str(candidate)
            break
    if not object_name and object_names:
        object_name = str(object_names[0])
    if not object_name:
        prefix = getattr(output_location, "prefix", "") or settings.output_prefix
        object_name = _find_first_json_object(
            namespace, bucket, prefix, object_storage_client
        )

    response = object_storage_client.get_object(
        namespace_name=namespace,
        bucket_name=bucket,
        object_name=object_name,
    )
    raw_body = response.data.content.decode("utf-8")
    return json.loads(raw_body)


def _find_first_json_object(
    namespace: str,
    bucket: str,
    prefix: str,
    object_storage_client: Any,
) -> str:
    """Find the first JSON object under a Speech output prefix."""

    response = object_storage_client.list_objects(
        namespace_name=namespace,
        bucket_name=bucket,
        prefix=prefix,
    )
    objects = getattr(response.data, "objects", []) or []
    for object_summary in objects:
        name = str(getattr(object_summary, "name", ""))
        if name.lower().endswith(".json"):
            return name
    raise RuntimeError(f"No OCI Speech transcript JSON object found under {prefix}.")


def _extract_transcript_text(payload: Any) -> str:
    """Extract transcript text from common OCI Speech JSON shapes."""

    transcript = ""
    if isinstance(payload, dict):
        for key in ("transcription", "transcript", "text", "displayText"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                transcript = value
                break
        if isinstance(payload.get("transcriptions"), list):
            transcript = _extract_transcript_from_items(payload["transcriptions"])
        elif isinstance(payload.get("results"), dict):
            transcript = _extract_transcript_text(payload["results"])
        elif isinstance(payload.get("results"), list):
            transcript = _extract_transcript_from_items(payload["results"])
        elif isinstance(payload.get("tokens"), list):
            token_text = [
                str(token.get("token") or token.get("text") or "").strip()
                for token in payload["tokens"]
                if isinstance(token, dict)
            ]
            transcript = " ".join(token for token in token_text if token)

    elif isinstance(payload, list):
        transcript = _extract_transcript_from_items(payload)

    return transcript


def _extract_transcript_from_items(items: list[Any]) -> str:
    """Extract transcript text from a list of nested transcript items."""

    parts = []
    for item in items:
        text = _extract_transcript_text(item)
        if text:
            parts.append(text)
    return " ".join(parts)


def _build_object_name(prefix: str, name: str) -> str:
    """Build an Object Storage object name from a prefix and leaf name."""

    clean_prefix = prefix.strip("/")
    if clean_prefix:
        return f"{clean_prefix}/{name}"
    return name


def _validate_audio_type(filename: str, content_type: str) -> None:
    """Validate file extension and content type against supported audio formats.

    Args:
        filename: Uploaded file name.
        content_type: Uploaded file media type.

    Raises:
        AudioRequestError: If the extension or content type is unsupported.
    """

    extension = Path(filename).suffix.lower()
    if extension not in SUPPORTED_AUDIO_TYPES:
        raise AudioRequestError(f"Unsupported audio extension: {extension or filename}")

    clean_content_type = content_type.split(";", maxsplit=1)[0].strip().lower()
    if (
        clean_content_type
        and clean_content_type not in SUPPORTED_AUDIO_TYPES[extension]
    ):
        raise AudioRequestError(f"Unsupported audio content type: {content_type}")


def _parse_bool(raw_value: str, field_name: str) -> bool:
    """Parse a required boolean form value.

    Args:
        raw_value: Raw form value.
        field_name: Field name used in validation errors.

    Returns:
        bool: Parsed boolean value.

    Raises:
        AudioRequestError: If the value is not an accepted boolean token.
    """

    normalized_value = raw_value.strip().lower()
    if normalized_value in BOOLEAN_TRUE_VALUES:
        return True
    if normalized_value in BOOLEAN_FALSE_VALUES:
        return False
    raise AudioRequestError(f"Field must be a boolean: {field_name}")


def _load_optional_bool(env_name: str, default_value: bool) -> bool:
    """Load and validate an optional boolean environment variable.

    Args:
        env_name: Environment variable name.
        default_value: Value used when the variable is missing.

    Returns:
        bool: Loaded boolean value.

    Raises:
        ValueError: If the configured value is invalid.
    """

    raw_value = environ.get(env_name)
    if raw_value is None or raw_value.strip() == "":
        return default_value

    normalized_value = raw_value.strip().lower()
    if normalized_value in BOOLEAN_TRUE_VALUES:
        return True
    if normalized_value in BOOLEAN_FALSE_VALUES:
        return False
    accepted_values = ", ".join(sorted(BOOLEAN_TRUE_VALUES.union(BOOLEAN_FALSE_VALUES)))
    raise ValueError(f"{env_name} must be a boolean value ({accepted_values}).")


def _load_optional_int(
    env_name: str,
    default_value: int,
    minimum_value: int,
    maximum_value: int,
) -> int:
    """Load and validate an optional integer environment variable.

    Args:
        env_name: Environment variable name.
        default_value: Value used when the variable is missing.
        minimum_value: Minimum accepted value.
        maximum_value: Maximum accepted value.

    Returns:
        int: Loaded integer value.

    Raises:
        ValueError: If the configured value is invalid.
    """

    raw_value = environ.get(env_name)
    if raw_value is None or raw_value.strip() == "":
        return default_value
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ValueError(
            f"{env_name} must be an integer between {minimum_value} and "
            f"{maximum_value}: {raw_value}"
        ) from exc
    if minimum_value <= value <= maximum_value:
        return value
    raise ValueError(
        f"{env_name} must be between {minimum_value} and {maximum_value}: {value}"
    )


def _format_sse(event_name: str, payload: dict[str, object]) -> str:
    """Format one Server-Sent Event.

    Args:
        event_name: SSE event name.
        payload: JSON-serializable event payload.

    Returns:
        str: Formatted SSE frame.
    """

    return f"event: {event_name}\ndata: {json.dumps(payload)}\n\n"
