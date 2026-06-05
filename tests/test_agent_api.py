"""
Author: L. Saetta
Date last modified: 2026-06-05
License: MIT
Description: Unit tests for the OCI RAG agent FastAPI API.
"""

# pylint: disable=too-few-public-methods

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi.testclient import TestClient

from agent.main import app

REQUIRED_ENV = {
    "OCI_REGION": "eu-frankfurt-1",
    "OCI_COMPARTMENT_ID": "ocid1.compartment.oc1..example",
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
    """

    id: str
    output_text: str


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

    def __init__(self, fail: bool = False) -> None:
        """Initialize fake responses state.

        Args:
            fail: Whether response creation should raise an error.
        """

        self.fail = fail
        self.create_calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> FakeResponse | list[dict[str, str]]:
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
        if kwargs.get("stream"):
            return [{"delta": "Agent "}, {"delta": "answer"}]

        return FakeResponse(id="resp-123", output_text="Agent answer")


class FakeOpenAIClient:
    """Mock OpenAI-compatible client."""

    def __init__(self, fail: bool = False, fail_conversation: bool = False) -> None:
        """Initialize fake OpenAI-compatible client.

        Args:
            fail: Whether Responses API calls should fail.
            fail_conversation: Whether conversation creation should fail.
        """

        self.conversations = FakeConversations(fail=fail_conversation)
        self.responses = FakeResponses(fail=fail)


def test_health_endpoint() -> None:
    """Test the health endpoint."""

    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


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
        "references": [],
        "error": None,
    }
    assert fake_client.conversations.create_calls == 1
    assert fake_client.responses.create_calls == [
        {
            "model": "test-model",
            "input": "Answer this",
            "conversation": "conv-new",
            "tools": [
                {
                    "type": "file_search",
                    "vector_store_ids": ["test-vector-store"],
                }
            ],
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


def test_responses_api_failure(monkeypatch: Any) -> None:
    """Test Responses API failure handling."""

    _set_required_env(monkeypatch)
    _set_client_factory(FakeOpenAIClient(fail=True))
    client = TestClient(app)

    response = client.post(
        "/responses",
        json={"new_conversation": True, "user_request": "Hello"},
    )

    assert response.status_code == 502
    assert "Responses API failure: upstream unavailable" in response.json()["error"]


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
    assert 'event: done\ndata: {"conversation_id": "conv-new"}' in response.text
    assert fake_client.responses.create_calls[0]["stream"] is True


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
