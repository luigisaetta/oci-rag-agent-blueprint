"""
Author: L. Saetta
Date last modified: 2026-06-24
License: MIT
Description: Unit tests for the OCI RAG agent FastAPI API.
"""

# pylint: disable=too-few-public-methods,too-many-arguments,too-many-instance-attributes
# pylint: disable=too-many-lines
# pylint: disable=too-many-positional-arguments

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from json import JSONDecodeError
import logging
from types import SimpleNamespace
from typing import Any

from fastapi.testclient import TestClient

from agent.agent import AGENT_INSTRUCTIONS, OUTPUT_TEXT_DELTA_EVENT_TYPE
from agent.audio import AudioTranscriptionClients
from agent.main import app

REQUIRED_ENV = {
    "OCI_REGION": "eu-frankfurt-1",
    "OCI_COMPARTMENT_ID": "ocid1.compartment.oc1..example",
    "OCI_PROJECT_ID": "ocid1.generativeaiproject.oc1..example",
    "OCI_MODEL_ID": "test-model",
    "OCI_VECTOR_STORE_ID": "test-vector-store",
    "OPENAI_API_KEY": "test-api-key",
}


@dataclass
class FakeConversation:
    """Fake conversation object returned by the mocked OpenAI client.

    Attributes:
        id: Conversation identifier.
    """

    id: str


@dataclass
class FakeResponse:
    """Fake response object returned by the mocked OpenAI client.

    Attributes:
        id: Response identifier.
        output_text: Response text.
        output: Responses API output items.
        usage: Responses API token usage payload.
        nested_payload: Optional nested payload used to test defensive parsing.
    """

    id: str
    output_text: str
    output: list[dict[str, Any]]
    usage: dict[str, Any] | None = None
    nested_payload: dict[str, Any] | None = None

    def model_dump(self) -> dict[str, Any]:
        """Dump fake response data like an SDK model object.

        Returns:
            dict[str, Any]: Serialized fake response payload.
        """

        payload: dict[str, Any] = {
            "id": self.id,
            "output_text": self.output_text,
            "output": self.output,
            "usage": self.usage,
        }
        if self.nested_payload:
            payload["nested_payload"] = self.nested_payload

        return payload


class FakeConversations:
    """Mock Conversations API surface."""

    def __init__(self, fail: bool = False) -> None:
        """Initialize fake conversations state.

        Args:
            fail: Whether conversation creation should raise an error.
        """

        self.fail = fail
        self.create_calls = 0

    def create(self) -> FakeConversation:
        """Mock conversation creation.

        Returns:
            FakeConversation: Created fake conversation.
        """

        if self.fail:
            raise RuntimeError("conversation unavailable")

        self.create_calls += 1
        return FakeConversation(id="conv-new")


class FakeResponses:
    """Mock Responses API surface."""

    def __init__(
        self,
        fail: bool = False,
        fail_stream_after_token: bool = False,
        nested_results: bool = False,
        annotation_refs: bool = False,
        page_in_text: bool = False,
        stream_references: bool = True,
        stream_usage: bool = True,
    ) -> None:
        """Initialize fake responses state.

        Args:
            fail: Whether response creation should raise an error.
            fail_stream_after_token: Whether streaming should fail after a token.
            nested_results: Whether file search results use an alternate shape.
            annotation_refs: Whether references are returned as text annotations.
            page_in_text: Whether page numbers are embedded in result text.
            stream_references: Whether final stream events include references.
            stream_usage: Whether final stream events include token usage.
        """

        self.fail = fail
        self.fail_stream_after_token = fail_stream_after_token
        self.nested_results = nested_results
        self.annotation_refs = annotation_refs
        self.page_in_text = page_in_text
        self.stream_references = stream_references
        self.stream_usage = stream_usage
        self.create_calls: list[dict[str, Any]] = []
        self.retrieve_calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> FakeResponse | list[dict[str, Any]]:
        """Mock response creation.

        Args:
            **kwargs: Responses API call arguments.

        Returns:
            FakeResponse | list[dict[str, str]]: Created fake response or stream.

        Raises:
            RuntimeError: If this fake is configured to fail.
        """

        if self.fail:
            raise RuntimeError("upstream unavailable")

        self.create_calls.append(kwargs)
        if kwargs.get("stream") and self.fail_stream_after_token:
            return _stream_with_json_decode_error()

        if kwargs.get("stream"):
            return [
                {
                    "type": "response.created",
                    "response": {"id": "resp-stream"},
                },
                {
                    "type": "response.reasoning_text.delta",
                    "delta": "I should plan this.",
                },
                {"type": OUTPUT_TEXT_DELTA_EVENT_TYPE, "delta": "Agent "},
                {"type": OUTPUT_TEXT_DELTA_EVENT_TYPE, "delta": "answer"},
                {
                    "type": "response.completed",
                    "response": {
                        "output": _fake_stream_output(
                            self.annotation_refs,
                            self.page_in_text,
                            self.stream_references,
                        ),
                        "usage": _fake_usage() if self.stream_usage else None,
                    },
                },
            ]

        return FakeResponse(
            id="resp-123",
            output_text="Agent answer",
            output=_fake_response_output(
                self.nested_results,
                self.annotation_refs,
                self.page_in_text,
            ),
            usage=_fake_usage(),
            nested_payload=(
                _fake_nested_file_search_payload() if self.nested_results else None
            ),
        )

    def retrieve(self, response_id: str, **kwargs: Any) -> FakeResponse:
        """Mock response retrieval after streaming.

        Args:
            response_id: Response identifier to retrieve.
            **kwargs: Retrieval arguments.

        Returns:
            FakeResponse: Retrieved fake response.
        """

        self.retrieve_calls.append({"response_id": response_id, **kwargs})
        return FakeResponse(
            id=response_id,
            output_text="Agent answer",
            output=_fake_response_output(
                self.nested_results,
                self.annotation_refs,
                self.page_in_text,
            ),
            usage=_fake_usage(),
        )


class FakeOpenAIClient:
    """Mock OpenAI-compatible client."""

    def __init__(
        self,
        fail: bool = False,
        fail_conversation: bool = False,
        fail_stream_after_token: bool = False,
        nested_results: bool = False,
        annotation_refs: bool = False,
        page_in_text: bool = False,
        stream_references: bool = True,
        stream_usage: bool = True,
    ) -> None:
        """Initialize fake OpenAI-compatible client.

        Args:
            fail: Whether Responses API calls should fail.
            fail_conversation: Whether conversation creation should fail.
            fail_stream_after_token: Whether streaming should fail after a token.
            nested_results: Whether file search results use an alternate shape.
            annotation_refs: Whether references are returned as text annotations.
            page_in_text: Whether page numbers are embedded in result text.
            stream_references: Whether final stream events include references.
            stream_usage: Whether final stream events include token usage.
        """

        self.conversations = FakeConversations(fail=fail_conversation)
        self.responses = FakeResponses(
            fail=fail,
            fail_stream_after_token=fail_stream_after_token,
            nested_results=nested_results,
            annotation_refs=annotation_refs,
            page_in_text=page_in_text,
            stream_references=stream_references,
            stream_usage=stream_usage,
        )


class FakeAudioObjectStorageClient:
    """Fake Object Storage client for audio transcription tests."""

    def __init__(self, transcript_payload: bytes | None = None) -> None:
        """Initialize fake Object Storage state."""

        self.transcript_payload = transcript_payload or (
            b'{"transcription": "What is in the uploaded audio?"}'
        )
        self.put_calls: list[tuple[str, bytes]] = []

    def put_object(
        self,
        namespace_name: str,
        bucket_name: str,
        object_name: str,
        put_object_body: Any,
    ) -> None:
        """Record uploaded audio bytes."""

        del namespace_name, bucket_name
        self.put_calls.append((object_name, put_object_body.read()))

    def get_object(
        self,
        namespace_name: str,
        bucket_name: str,
        object_name: str,
    ) -> Any:
        """Return fake transcript JSON."""

        del namespace_name, bucket_name, object_name
        return SimpleNamespace(data=SimpleNamespace(content=self.transcript_payload))


class FakeAudioSpeechClient:
    """Fake OCI Speech client for audio transcription tests."""

    def __init__(self, lifecycle_state: str = "SUCCEEDED") -> None:
        """Initialize fake Speech state."""

        self.lifecycle_state = lifecycle_state
        self.created_details: Any | None = None

    def create_transcription_job(self, details: Any) -> Any:
        """Record created transcription job details."""

        self.created_details = details
        return SimpleNamespace(data=SimpleNamespace(id="job-123"))

    def list_transcription_tasks(self, transcription_job_id: str) -> Any:
        """Return one fake transcription task."""

        del transcription_job_id
        return SimpleNamespace(
            data=SimpleNamespace(
                items=[
                    SimpleNamespace(
                        id="task-123",
                        lifecycle_state=self.lifecycle_state,
                        lifecycle_details="speech failed",
                    )
                ]
            )
        )

    def get_transcription_task(self, transcription_job_id: str, task_id: str) -> Any:
        """Return a fake completed transcription task."""

        del transcription_job_id, task_id
        return SimpleNamespace(
            data=SimpleNamespace(
                output_location=SimpleNamespace(
                    namespace_name="namespace",
                    bucket_name="bucket",
                    object_names=["speech-output/job-123/transcript.json"],
                )
            )
        )


class FakeAudioModels:
    """Fake OCI Speech models module."""

    CreateTranscriptionJobDetails = SimpleNamespace
    ObjectListInlineInputLocation = SimpleNamespace
    ObjectLocation = SimpleNamespace
    OutputLocation = SimpleNamespace
    TranscriptionModelDetails = SimpleNamespace
    TranscriptionSettings = SimpleNamespace


def test_health_endpoint() -> None:
    """Test the health endpoint."""

    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_runtime_environment_endpoint_redacts_secret_values(monkeypatch: Any) -> None:
    """Test runtime environment diagnostics omit secret values."""

    monkeypatch.setenv("OCI_REGION", "eu-frankfurt-1")
    monkeypatch.setenv("RAG_VISIBLE_SETTING", "visible-value")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-secret-value")
    monkeypatch.setenv("IDCS_TOKEN_ENDPOINT", "https://token.example.com")
    monkeypatch.setenv("CONFIDENTIAL_APPLICATION_SECRET", "client-secret-value")
    client = TestClient(app)

    response = client.get("/config/environment")

    assert response.status_code == 200
    payload = response.json()
    assert payload["environment"]["OCI_REGION"] == "eu-frankfurt-1"
    assert payload["environment"]["RAG_VISIBLE_SETTING"] == "visible-value"
    assert "OPENAI_API_KEY" not in payload["environment"]
    assert "IDCS_TOKEN_ENDPOINT" not in payload["environment"]
    assert "CONFIDENTIAL_APPLICATION_SECRET" not in payload["environment"]
    assert "OPENAI_API_KEY" in payload["redacted"]
    assert "IDCS_TOKEN_ENDPOINT" in payload["redacted"]
    assert "CONFIDENTIAL_APPLICATION_SECRET" in payload["redacted"]
    assert "openai-secret-value" not in response.text
    assert "https://token.example.com" not in response.text
    assert "client-secret-value" not in response.text


def test_runtime_environment_endpoint_returns_sorted_names(monkeypatch: Any) -> None:
    """Test runtime environment diagnostics use deterministic key ordering."""

    monkeypatch.setenv("RAG_Z_SETTING", "last")
    monkeypatch.setenv("RAG_A_SETTING", "first")
    monkeypatch.setenv("RAG_M_SECRET", "secret-value")
    monkeypatch.setenv("RAG_B_TOKEN", "token-value")
    client = TestClient(app)

    response = client.get("/config/environment")

    assert response.status_code == 200
    payload = response.json()
    visible_names = list(payload["environment"])
    redacted_names = payload["redacted"]
    assert visible_names == sorted(visible_names)
    assert redacted_names == sorted(redacted_names)


def test_local_cors_preflight() -> None:
    """Test that local browser clients can call the agent API."""

    client = TestClient(app)

    response = client.options(
        "/responses",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "*"


def test_rejects_invalid_payload_before_api_call(monkeypatch: Any) -> None:
    """Test that schema validation prevents API calls."""

    fake_client = FakeOpenAIClient()
    _set_required_env(monkeypatch)
    _set_client_factory(fake_client)
    client = TestClient(app)

    response = client.post("/responses", json={"new_conversation": True})

    assert response.status_code == 400
    assert "Missing required field: user_request" in response.json()["error"]
    assert fake_client.conversations.create_calls == 0
    assert not fake_client.responses.create_calls


def test_rejects_missing_conversation_id(monkeypatch: Any) -> None:
    """Test validation for existing conversation requests."""

    _set_required_env(monkeypatch)
    _set_client_factory(FakeOpenAIClient())
    client = TestClient(app)

    response = client.post(
        "/responses",
        json={"new_conversation": False, "user_request": "Hello"},
    )

    assert response.status_code == 400
    assert "conversation_id is required" in response.json()["error"]


def test_rejects_missing_environment_variables(monkeypatch: Any) -> None:
    """Test missing environment variable handling."""

    for env_name in REQUIRED_ENV:
        monkeypatch.delenv(env_name, raising=False)
    _set_client_factory(FakeOpenAIClient())
    client = TestClient(app)

    response = client.post(
        "/responses",
        json={"new_conversation": True, "user_request": "Hello"},
    )

    assert response.status_code == 500
    assert "Missing required environment variables" in response.json()["error"]


def test_creates_new_conversation_and_response(monkeypatch: Any) -> None:
    """Test new conversation handling and Responses API call shape."""

    fake_client = FakeOpenAIClient()
    _set_required_env(monkeypatch)
    _set_client_factory(fake_client)
    client = TestClient(app)

    response = client.post(
        "/responses",
        json={"new_conversation": True, "user_request": "Answer this"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "conversation_id": "conv-new",
        "response_id": "resp-123",
        "agent_response": "Agent answer",
        "references": [
            {
                "file_name": "architecture.md",
                "page": 2,
                "metadata": {
                    "attributes": {"page": 2, "section": "overview"},
                    "file_id": "file-123",
                    "score": 0.91,
                    "text": "Architecture overview excerpt",
                },
            }
        ],
        "usage": {
            "input_tokens": 100,
            "output_tokens": 50,
            "total_tokens": 150,
            "reasoning_tokens": 3,
        },
        "error": None,
    }
    assert fake_client.conversations.create_calls == 1
    assert fake_client.responses.create_calls == [
        {
            "model": "test-model",
            "instructions": AGENT_INSTRUCTIONS,
            "input": "Answer this",
            "conversation": "conv-new",
            "tools": [
                {
                    "type": "file_search",
                    "vector_store_ids": ["test-vector-store"],
                    "max_num_results": 10,
                }
            ],
            "tool_choice": "required",
            "include": ["file_search_call.results"],
            "timeout": 60,
        }
    ]


def test_attaches_to_existing_conversation(monkeypatch: Any) -> None:
    """Test existing conversation handling."""

    fake_client = FakeOpenAIClient()
    _set_required_env(monkeypatch)
    _set_client_factory(fake_client)
    client = TestClient(app)

    response = client.post(
        "/responses",
        json={
            "new_conversation": False,
            "conversation_id": "conv-existing",
            "user_request": "Continue",
            "user_id": "user-1",
            "user_role": "developer",
        },
    )

    assert response.status_code == 200
    assert response.json()["conversation_id"] == "conv-existing"
    assert fake_client.conversations.create_calls == 0
    assert fake_client.responses.create_calls[0]["conversation"] == "conv-existing"


def test_uses_runtime_tuning_for_non_streaming_request(monkeypatch: Any) -> None:
    """Test runtime tuning values in non-streaming Responses API calls."""

    fake_client = FakeOpenAIClient()
    _set_required_env(monkeypatch)
    monkeypatch.setenv("FILE_SEARCH_MAX_NUM_RESULTS", "3")
    monkeypatch.setenv("RESPONSES_TIMEOUT_SECONDS", "42")
    _set_client_factory(fake_client)
    client = TestClient(app)

    response = client.post(
        "/responses",
        json={"new_conversation": True, "user_request": "Answer this"},
    )

    assert response.status_code == 200
    create_call = fake_client.responses.create_calls[0]
    assert create_call["timeout"] == 42
    assert create_call["tools"][0]["max_num_results"] == 3


def test_extracts_references_from_nested_response_payload(monkeypatch: Any) -> None:
    """Test defensive reference extraction for alternate SDK payload shapes."""

    _set_required_env(monkeypatch)
    _set_client_factory(FakeOpenAIClient(nested_results=True))
    client = TestClient(app)

    response = client.post(
        "/responses",
        json={"new_conversation": True, "user_request": "Answer this"},
    )

    assert response.status_code == 200
    assert response.json()["references"] == [
        {
            "file_name": "nested-guide.md",
            "page": 4,
            "metadata": {
                "attributes": {"page_number": "4"},
                "file_id": "file-nested",
                "score": 0.77,
                "text": "Nested excerpt",
            },
        }
    ]


def test_extracts_references_from_output_text_annotations(monkeypatch: Any) -> None:
    """Test reference extraction from Responses API citation annotations."""

    _set_required_env(monkeypatch)
    _set_client_factory(FakeOpenAIClient(annotation_refs=True))
    client = TestClient(app)

    response = client.post(
        "/responses",
        json={"new_conversation": True, "user_request": "Answer this"},
    )

    assert response.status_code == 200
    assert response.json()["agent_response"] == "Agent [1] answer"
    assert response.json()["references"] == [
        {
            "file_name": "annotated-guide.md",
            "page": 7,
            "metadata": {
                "attributes": {"page_numbers": [7, 8]},
                "file_id": "file-annotated",
            },
        }
    ]


def test_extracts_page_number_from_result_text(monkeypatch: Any) -> None:
    """Test page extraction when OCI returns page data only in result text."""

    _set_required_env(monkeypatch)
    _set_client_factory(FakeOpenAIClient(page_in_text=True))
    client = TestClient(app)

    response = client.post(
        "/responses",
        json={"new_conversation": True, "user_request": "Answer this"},
    )

    assert response.status_code == 200
    assert response.json()["references"] == [
        {
            "file_name": "guide-with-page-text.pdf",
            "page": 44,
            "metadata": {
                "file_id": "file-page-text",
                "score": 0.81,
                "text": "Oracle AI Vector Search User's Guide Page 44 of 56",
            },
        }
    ]


def test_responses_api_failure_logs_phase(monkeypatch: Any, caplog: Any) -> None:
    """Test Responses API failures log request and processing phase context."""

    _set_required_env(monkeypatch)
    _set_client_factory(FakeOpenAIClient(fail=True))
    client = TestClient(app)

    with caplog.at_level(logging.INFO):
        response = client.post(
            "/responses",
            json={"new_conversation": True, "user_request": "Hello"},
        )

    assert response.status_code == 502
    assert "Responses API failure: upstream unavailable" in response.json()["error"]
    assert "Request started request_id=" in caplog.text
    assert "Agent request failed during response creation" in caplog.text
    assert "Responses API failure request_id=" in caplog.text


def test_unhandled_request_failure_logs_request_id(
    monkeypatch: Any, caplog: Any
) -> None:
    """Test unexpected request failures include a request id in logs and response."""

    _set_required_env(monkeypatch)
    _set_client_factory(FakeOpenAIClient())

    async def fail_unhandled_route() -> None:
        raise RuntimeError("response schema unavailable")

    route_path = "/__test_unhandled_logging"
    if not any(route.path == route_path for route in app.routes):
        app.add_api_route(route_path, fail_unhandled_route, methods=["GET"])

    client = TestClient(app, raise_server_exceptions=False)

    with caplog.at_level(logging.INFO):
        response = client.get(route_path)

    assert response.status_code == 500
    assert "request_id=" in response.json()["error"]
    assert "Unhandled request failure request_id=" in caplog.text
    assert "response schema unavailable" in caplog.text


def test_streams_response_tokens(monkeypatch: Any) -> None:
    """Test streaming response handling."""

    fake_client = FakeOpenAIClient()
    _set_required_env(monkeypatch)
    _set_client_factory(fake_client)
    client = TestClient(app)

    response = client.post(
        "/responses",
        json={
            "new_conversation": True,
            "user_request": "Stream this",
            "stream": True,
        },
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert 'event: metadata\ndata: {"conversation_id": "conv-new"}' in response.text
    assert 'event: token\ndata: {"text": "Agent "}' in response.text
    assert 'event: token\ndata: {"text": "answer"}' in response.text
    assert "event: references" in response.text
    assert '"file_name": "architecture.md"' in response.text
    assert "event: usage" in response.text
    assert '"total_tokens": 150' in response.text
    assert "I should plan this." not in response.text
    assert 'event: done\ndata: {"conversation_id": "conv-new"}' in response.text
    assert fake_client.responses.create_calls[0]["stream"] is True
    assert fake_client.responses.create_calls[0]["instructions"] == AGENT_INSTRUCTIONS
    assert not fake_client.responses.retrieve_calls


def test_uses_runtime_tuning_for_streaming_request(monkeypatch: Any) -> None:
    """Test runtime tuning values in streaming create calls."""

    fake_client = FakeOpenAIClient()
    _set_required_env(monkeypatch)
    monkeypatch.setenv("FILE_SEARCH_MAX_NUM_RESULTS", "4")
    monkeypatch.setenv("RESPONSES_TIMEOUT_SECONDS", "55")
    _set_client_factory(fake_client)
    client = TestClient(app)

    response = client.post(
        "/responses",
        json={
            "new_conversation": True,
            "user_request": "Stream this",
            "stream": True,
        },
    )

    assert response.status_code == 200
    create_call = fake_client.responses.create_calls[0]
    assert create_call["stream"] is True
    assert create_call["timeout"] == 55
    assert create_call["tools"][0]["max_num_results"] == 4
    assert not fake_client.responses.retrieve_calls


def test_auto_stream_finalization_retrieves_missing_metadata(
    monkeypatch: Any,
) -> None:
    """Test auto finalization retrieves missing stream metadata."""

    fake_client = FakeOpenAIClient(stream_usage=False)
    _set_required_env(monkeypatch)
    monkeypatch.setenv("STREAM_FINALIZATION_MODE", "auto")
    _set_client_factory(fake_client)
    client = TestClient(app)

    response = client.post(
        "/responses",
        json={
            "new_conversation": True,
            "user_request": "Stream this",
            "stream": True,
        },
    )

    assert response.status_code == 200
    assert "event: usage" in response.text
    assert '"total_tokens": 150' in response.text
    assert fake_client.responses.retrieve_calls == [
        {
            "response_id": "resp-stream",
            "include": ["file_search_call.results"],
            "timeout": 60,
        }
    ]


def test_auto_stream_finalization_skips_retrieve_when_metadata_is_complete(
    monkeypatch: Any,
) -> None:
    """Test auto finalization uses complete stream metadata without retrieve."""

    fake_client = FakeOpenAIClient()
    _set_required_env(monkeypatch)
    monkeypatch.setenv("STREAM_FINALIZATION_MODE", "auto")
    _set_client_factory(fake_client)
    client = TestClient(app)

    response = client.post(
        "/responses",
        json={
            "new_conversation": True,
            "user_request": "Stream this",
            "stream": True,
        },
    )

    assert response.status_code == 200
    assert "event: references" in response.text
    assert "event: usage" in response.text
    assert not fake_client.responses.retrieve_calls


def test_always_stream_finalization_retrieves_response(monkeypatch: Any) -> None:
    """Test always finalization retrieves completed streaming responses."""

    fake_client = FakeOpenAIClient()
    _set_required_env(monkeypatch)
    monkeypatch.setenv("STREAM_FINALIZATION_MODE", "always")
    _set_client_factory(fake_client)
    client = TestClient(app)

    response = client.post(
        "/responses",
        json={
            "new_conversation": True,
            "user_request": "Stream this",
            "stream": True,
        },
    )

    assert response.status_code == 200
    assert fake_client.responses.retrieve_calls == [
        {
            "response_id": "resp-stream",
            "include": ["file_search_call.results"],
            "timeout": 60,
        }
    ]


def test_rejects_invalid_stream_field(monkeypatch: Any) -> None:
    """Test schema validation for the stream field."""

    fake_client = FakeOpenAIClient()
    _set_required_env(monkeypatch)
    _set_client_factory(fake_client)
    client = TestClient(app)

    response = client.post(
        "/responses",
        json={
            "new_conversation": True,
            "user_request": "Hello",
            "stream": "yes",
        },
    )

    assert response.status_code == 400
    assert "Field must be a boolean: stream" in response.json()["error"]
    assert not fake_client.responses.create_calls


def test_streams_error_when_conversation_creation_fails(monkeypatch: Any) -> None:
    """Test streaming error events for early Responses API failures."""

    _set_required_env(monkeypatch)
    _set_client_factory(FakeOpenAIClient(fail_conversation=True))
    client = TestClient(app)

    response = client.post(
        "/responses",
        json={
            "new_conversation": True,
            "user_request": "Stream this",
            "stream": True,
        },
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: error" in response.text
    assert "Responses API failure: conversation unavailable" in response.text


def test_stream_parser_failure_after_token_ends_stream(monkeypatch: Any) -> None:
    """Test SDK parser failures after partial output do not append user errors."""

    _set_required_env(monkeypatch)
    _set_client_factory(FakeOpenAIClient(fail_stream_after_token=True))
    client = TestClient(app)

    response = client.post(
        "/responses",
        json={
            "new_conversation": True,
            "user_request": "Stream this",
            "stream": True,
        },
    )

    assert response.status_code == 200
    assert 'event: token\ndata: {"text": "Partial answer"}' in response.text
    assert "event: references" in response.text
    assert '"references": []' in response.text
    assert "event: usage" not in response.text
    assert 'event: done\ndata: {"conversation_id": "conv-new"}' in response.text
    assert "event: error" not in response.text


def test_audio_response_accepts_webm_and_streams_agent_answer(
    monkeypatch: Any,
) -> None:
    """Test audio endpoint accepts browser audio and streams transcribed output."""

    object_storage_client, speech_client = _set_audio_env_and_clients(monkeypatch)
    fake_client = FakeOpenAIClient()
    _set_client_factory(fake_client)
    client = TestClient(app)

    response = client.post(
        "/responses/audio",
        data={"new_conversation": "true", "stream": "true"},
        files={"file": ("question.webm", b"audio bytes", "audio/webm")},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: transcript" in response.text
    assert "What is in the uploaded audio?" in response.text
    assert 'event: metadata\ndata: {"conversation_id": "conv-new"}' in response.text
    assert "event: token" in response.text
    assert 'event: token\ndata: {"text": "Agent "}' in response.text
    assert 'event: token\ndata: {"text": "answer"}' in response.text
    assert "event: references" in response.text
    assert "event: usage" in response.text
    assert 'event: done\ndata: {"conversation_id": "conv-new"}' in response.text
    assert object_storage_client.put_calls
    assert object_storage_client.put_calls[0][0].startswith("speech-input/")
    assert object_storage_client.put_calls[0][1] == b"audio bytes"
    assert speech_client.created_details.model_details.model_type == "WHISPER_MEDIUM"
    assert (
        fake_client.responses.create_calls[0]["input"]
        == "What is in the uploaded audio?"
    )
    assert fake_client.responses.create_calls[0]["stream"] is True


def test_audio_response_preserves_existing_conversation_id(
    monkeypatch: Any,
) -> None:
    """Test audio endpoint uses the supplied conversation id for continuation."""

    _set_audio_env_and_clients(monkeypatch)
    fake_client = FakeOpenAIClient()
    _set_client_factory(fake_client)
    client = TestClient(app)

    response = client.post(
        "/responses/audio",
        data={
            "new_conversation": "false",
            "conversation_id": "conv-existing",
            "stream": "true",
        },
        files={"file": ("question.wav", b"audio bytes", "audio/wav")},
    )

    assert response.status_code == 200
    assert (
        'event: metadata\ndata: {"conversation_id": "conv-existing"}' in response.text
    )
    assert 'event: done\ndata: {"conversation_id": "conv-existing"}' in response.text
    assert fake_client.responses.create_calls[0]["conversation"] == "conv-existing"


def test_audio_response_maps_large_turbo_model(monkeypatch: Any) -> None:
    """Test large turbo model setting maps to the OCI Speech model type."""

    _, speech_client = _set_audio_env_and_clients(monkeypatch)
    _set_client_factory(FakeOpenAIClient())
    monkeypatch.setenv("OCI_SPEECH_MODEL", "whisper-large-v3-turbo")
    client = TestClient(app)

    response = client.post(
        "/responses/audio",
        data={"new_conversation": "true", "stream": "true"},
        files={"file": ("question.webm", b"audio bytes", "audio/webm")},
    )

    assert response.status_code == 200
    assert speech_client.created_details.model_details.model_type == "WHISPER_LARGE_V3T"


def test_audio_response_requires_file() -> None:
    """Test audio endpoint rejects missing files."""

    client = TestClient(app)

    response = client.post(
        "/responses/audio",
        data={"new_conversation": "true", "stream": "true"},
    )

    assert response.status_code == 400
    assert response.json()["error"] == "Audio file is required."


def test_audio_response_rejects_unsupported_format(monkeypatch: Any) -> None:
    """Test audio endpoint rejects unsupported audio extensions."""

    _set_audio_env_and_clients(monkeypatch)
    client = TestClient(app)

    response = client.post(
        "/responses/audio",
        data={"new_conversation": "true", "stream": "true"},
        files={"file": ("question.txt", b"audio bytes", "text/plain")},
    )

    assert response.status_code == 400
    assert "Unsupported audio extension" in response.json()["error"]


def test_audio_response_requires_conversation_id_for_existing_conversation(
    monkeypatch: Any,
) -> None:
    """Test audio endpoint validates conversation continuation fields."""

    _set_audio_env_and_clients(monkeypatch)
    client = TestClient(app)

    response = client.post(
        "/responses/audio",
        data={"new_conversation": "false", "stream": "true"},
        files={"file": ("question.webm", b"audio bytes", "audio/webm")},
    )

    assert response.status_code == 400
    assert (
        response.json()["error"]
        == "conversation_id is required when new_conversation=false."
    )


def test_audio_response_can_be_disabled(monkeypatch: Any) -> None:
    """Test audio endpoint returns 404 when speech-to-text is disabled."""

    monkeypatch.setenv("SPEECH_TO_TEXT_ENABLED", "false")
    client = TestClient(app)

    response = client.post(
        "/responses/audio",
        data={"new_conversation": "true", "stream": "true"},
        files={"file": ("question.webm", b"audio bytes", "audio/webm")},
    )

    assert response.status_code == 404
    assert response.json()["error"] == "Speech-to-text is not enabled."


def test_audio_response_rejects_oversized_upload(monkeypatch: Any) -> None:
    """Test audio endpoint enforces configured upload size limits."""

    _set_audio_env_and_clients(monkeypatch)
    monkeypatch.setenv("AUDIO_UPLOAD_MAX_SIZE_MB", "1")
    client = TestClient(app)

    response = client.post(
        "/responses/audio",
        data={"new_conversation": "true", "stream": "true"},
        files={"file": ("question.webm", b"x" * (1024 * 1024 + 1), "audio/webm")},
    )

    assert response.status_code == 413
    assert response.json()["error"] == "Audio file is larger than the configured limit."


def test_audio_response_reports_transcription_failure(monkeypatch: Any) -> None:
    """Test audio endpoint maps OCI Speech failures to a gateway error."""

    _set_audio_env_and_clients(
        monkeypatch,
        speech_client=FakeAudioSpeechClient(lifecycle_state="FAILED"),
    )
    client = TestClient(app)

    response = client.post(
        "/responses/audio",
        data={"new_conversation": "true", "stream": "true"},
        files={"file": ("question.webm", b"audio bytes", "audio/webm")},
    )

    assert response.status_code == 502
    assert "OCI Speech transcription failed" in response.json()["error"]


def _stream_with_json_decode_error() -> Iterator[dict[str, Any]]:
    """Build a fake stream that fails after one valid token event.

    Yields:
        dict[str, Any]: Stream events before the simulated parser error.

    Raises:
        JSONDecodeError: Simulated SDK stream parser failure.
    """

    yield {"type": "response.created", "response": {"id": "resp-stream"}}
    yield {"type": OUTPUT_TEXT_DELTA_EVENT_TYPE, "delta": "Partial answer"}
    raise JSONDecodeError(
        "Expecting property name enclosed in double quotes",
        "{not valid json}",
        1,
    )


def _fake_file_search_call() -> dict[str, Any]:
    """Build a fake Responses API file search call output item.

    Returns:
        dict[str, Any]: Fake file search call with one result.
    """

    return {
        "type": "file_search_call",
        "results": [
            {
                "filename": "architecture.md",
                "file_id": "file-123",
                "score": 0.91,
                "text": "Architecture overview excerpt",
                "attributes": {"page": 2, "section": "overview"},
            }
        ],
    }


def _fake_usage() -> dict[str, Any]:
    """Build a fake Responses API usage payload.

    Returns:
        dict[str, Any]: Fake token usage payload.
    """

    return {
        "input_tokens": 100,
        "output_tokens": 50,
        "total_tokens": 150,
        "output_tokens_details": {"reasoning_tokens": 3},
    }


def _fake_file_search_call_with_page_text() -> dict[str, Any]:
    """Build a fake file search call with page data embedded in text.

    Returns:
        dict[str, Any]: Fake file search call with page text.
    """

    return {
        "type": "file_search_call",
        "results": [
            {
                "attributes": {},
                "filename": "guide-with-page-text.pdf",
                "file_id": "file-page-text",
                "score": 0.81,
                "text": "Oracle AI Vector Search User's Guide Page 44 of 56",
            }
        ],
    }


def _fake_stream_output_item(
    annotation_refs: bool,
    page_in_text: bool,
) -> dict[str, Any]:
    """Build a fake stream completion output item.

    Args:
        annotation_refs: Whether to return an annotated message.
        page_in_text: Whether to return page data embedded in result text.

    Returns:
        dict[str, Any]: Fake stream output item.
    """

    if annotation_refs:
        return _fake_annotated_message()
    if page_in_text:
        return _fake_file_search_call_with_page_text()

    return _fake_file_search_call()


def _fake_stream_output(
    annotation_refs: bool,
    page_in_text: bool,
    stream_references: bool,
) -> list[dict[str, Any]]:
    """Build fake stream completion output items.

    Args:
        annotation_refs: Whether to return an annotated message.
        page_in_text: Whether to return page data embedded in result text.
        stream_references: Whether stream events include references.

    Returns:
        list[dict[str, Any]]: Fake stream output items.
    """

    if not stream_references:
        return []

    return [_fake_stream_output_item(annotation_refs, page_in_text)]


def _fake_response_output(
    nested_results: bool,
    annotation_refs: bool,
    page_in_text: bool = False,
) -> list[dict[str, Any]]:
    """Build fake response output for reference extraction tests.

    Args:
        nested_results: Whether to omit direct file search call results.
        annotation_refs: Whether to return an annotated output text message.
        page_in_text: Whether to return page data embedded in result text.

    Returns:
        list[dict[str, Any]]: Fake Responses API output.
    """

    if annotation_refs:
        return [_fake_annotated_message()]
    if page_in_text:
        return [_fake_file_search_call_with_page_text()]
    if nested_results:
        return []

    return [_fake_file_search_call()]


def _fake_annotated_message() -> dict[str, Any]:
    """Build a fake output text message with one file citation annotation.

    Returns:
        dict[str, Any]: Fake Responses API message output item.
    """

    return {
        "type": "message",
        "content": [
            {
                "type": "output_text",
                "text": "Agent answer",
                "annotations": [
                    {
                        "type": "file_citation",
                        "index": 6,
                        "filename": "annotated-guide.md",
                        "file_id": "file-annotated",
                        "additional_properties": {"page_numbers": [7, 8]},
                    }
                ],
            }
        ],
    }


def _fake_nested_file_search_payload() -> dict[str, Any]:
    """Build a fake nested file search result payload.

    Returns:
        dict[str, Any]: Nested payload containing file search results.
    """

    return {
        "event": {
            "item": {
                "results": [
                    {
                        "fileName": "nested-guide.md",
                        "fileId": "file-nested",
                        "score": 0.77,
                        "content": "Nested excerpt",
                        "attributes": {"page_number": "4"},
                    }
                ]
            }
        }
    }


def _set_required_env(monkeypatch: Any) -> None:
    """Set all required environment variables for tests.

    Args:
        monkeypatch: Pytest monkeypatch fixture.
    """

    for env_name, env_value in REQUIRED_ENV.items():
        monkeypatch.setenv(env_name, env_value)


def _set_client_factory(fake_client: FakeOpenAIClient) -> None:
    """Inject a fake OpenAI client factory into the FastAPI app.

    Args:
        fake_client: Fake client to return for agent requests.
    """

    app.state.openai_client_factory = lambda _settings: fake_client


def _set_audio_env_and_clients(
    monkeypatch: Any,
    object_storage_client: FakeAudioObjectStorageClient | None = None,
    speech_client: FakeAudioSpeechClient | None = None,
) -> tuple[FakeAudioObjectStorageClient, FakeAudioSpeechClient]:
    """Set speech-to-text test environment and fake OCI clients."""

    _set_required_env(monkeypatch)
    monkeypatch.delenv("SPEECH_TO_TEXT_ENABLED", raising=False)
    monkeypatch.setenv("OCI_SPEECH_STAGING_NAMESPACE", "namespace")
    monkeypatch.setenv("OCI_SPEECH_STAGING_BUCKET", "bucket")
    object_storage_client = object_storage_client or FakeAudioObjectStorageClient()
    speech_client = speech_client or FakeAudioSpeechClient()
    app.state.audio_transcription_client_factory = lambda: AudioTranscriptionClients(
        object_storage_client=object_storage_client,
        speech_client=speech_client,
        speech_models=FakeAudioModels,
    )
    return object_storage_client, speech_client
