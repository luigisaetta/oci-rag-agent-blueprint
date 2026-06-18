"""
Author: L. Saetta
Date last modified: 2026-06-18
License: MIT
Description: Unit tests for the OCI RAG agent command-line test client.
"""

from __future__ import annotations

import argparse
import base64
import json
from typing import Any, Iterator

import pytest

from clients import agent_cli
from clients.agent_cli import (
    IdcsTokenConfig,
    build_client_environment,
    build_payload,
    build_token_endpoint_url,
    fetch_idcs_access_token,
    maybe_fetch_idcs_access_token,
    parse_bool,
    parse_sse_lines,
    render_json_response,
    render_stream,
)


def test_build_payload_for_new_conversation() -> None:
    """Test payload construction for a new conversation."""

    payload = build_payload(
        create_conversation=True,
        user_request="Explain deployment",
    )

    assert payload == {
        "new_conversation": True,
        "user_request": "Explain deployment",
        "stream": True,
    }


def test_build_payload_for_non_streaming_request() -> None:
    """Test payload construction for a non-streaming request."""

    payload = build_payload(
        create_conversation=True,
        user_request="Explain deployment",
        stream=False,
    )

    assert payload == {
        "new_conversation": True,
        "user_request": "Explain deployment",
        "stream": False,
    }


def test_build_payload_for_existing_conversation() -> None:
    """Test payload construction for an existing conversation."""

    payload = build_payload(
        create_conversation=False,
        conversation_id="conv-123",
        user_request="Continue",
    )

    assert payload == {
        "new_conversation": False,
        "conversation_id": "conv-123",
        "user_request": "Continue",
        "stream": True,
    }


def test_build_payload_requires_conversation_id() -> None:
    """Test validation when reusing a conversation without an ID."""

    with pytest.raises(ValueError, match="conversation_id is required"):
        build_payload(create_conversation=False, user_request="Continue")


def test_parse_bool() -> None:
    """Test command-line boolean parsing."""

    assert parse_bool("true") is True
    assert parse_bool("false") is False
    assert parse_bool("TRUE") is True
    assert parse_bool("FALSE") is False


def test_parse_bool_rejects_invalid_values() -> None:
    """Test invalid boolean parsing."""

    with pytest.raises(argparse.ArgumentTypeError, match="value must be true or false"):
        parse_bool("yes")


def test_build_token_endpoint_url() -> None:
    """Test IDCS token endpoint URL construction."""

    assert (
        build_token_endpoint_url("https://idcs.example.identity.oraclecloud.com/")
        == "https://idcs.example.identity.oraclecloud.com/oauth2/v1/token"
    )


def test_build_client_environment_prefers_process_values(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test `.env` loading with process environment override."""

    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "IDENTITY_DOMAIN_URL=https://from-file.example.com",
                "CONFIDENTIAL_APPLICATION_ID=file-client",
                "CONFIDENTIAL_APPLICATION_SECRET='file-secret'",
                'IDCS_SCOPE="file-scope"',
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("CONFIDENTIAL_APPLICATION_ID", "process-client")

    environment = build_client_environment(str(env_file))

    assert environment["IDENTITY_DOMAIN_URL"] == "https://from-file.example.com"
    assert environment["CONFIDENTIAL_APPLICATION_ID"] == "process-client"
    assert environment["CONFIDENTIAL_APPLICATION_SECRET"] == "file-secret"
    assert environment["IDCS_SCOPE"] == "file-scope"


def test_fetch_idcs_access_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test IDCS token request construction and parsing."""

    captured_request: dict[str, Any] = {}

    class FakeResponse:
        """Context manager response for the fake IDCS token endpoint."""

        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            """Return a fake token response body."""

            return json.dumps({"access_token": "jwt-token"}).encode("utf-8")

    def fake_urlopen(http_request: Any, timeout: int) -> FakeResponse:
        """Capture the outgoing token request and return a fake response."""

        captured_request["url"] = http_request.full_url
        captured_request["timeout"] = timeout
        captured_request["body"] = http_request.data.decode("utf-8")
        captured_request["authorization"] = http_request.headers["Authorization"]
        captured_request["content_type"] = http_request.headers["Content-type"]
        return FakeResponse()

    monkeypatch.setattr(agent_cli.request, "urlopen", fake_urlopen)

    token = fetch_idcs_access_token(
        IdcsTokenConfig(
            identity_domain_url="https://idcs.example.identity.oraclecloud.com",
            confidential_application_id="client-id",
            confidential_application_secret="client-secret",
            scope="demo-agent/.default",
        )
    )

    expected_auth = base64.b64encode(b"client-id:client-secret").decode("ascii")
    assert token == "jwt-token"
    assert (
        captured_request["url"]
        == "https://idcs.example.identity.oraclecloud.com/oauth2/v1/token"
    )
    assert captured_request["timeout"] == 60
    assert captured_request["authorization"] == f"Basic {expected_auth}"
    assert captured_request["content_type"] == "application/x-www-form-urlencoded"
    assert "grant_type=client_credentials" in captured_request["body"]
    assert "scope=demo-agent%2F.default" in captured_request["body"]


def test_maybe_fetch_idcs_access_token_auto_without_config() -> None:
    """Test auto auth skips token acquisition when config is absent."""

    assert maybe_fetch_idcs_access_token("auto", {}) is None


def test_maybe_fetch_idcs_access_token_idcs_requires_config() -> None:
    """Test explicit IDCS auth reports missing configuration."""

    with pytest.raises(RuntimeError, match="Missing IDCS token configuration"):
        maybe_fetch_idcs_access_token("idcs", {})


def test_main_prints_token_only(monkeypatch: pytest.MonkeyPatch, capsys: Any) -> None:
    """Test token-only mode prints the acquired IDCS token and exits."""

    monkeypatch.setattr(
        agent_cli,
        "build_client_environment",
        lambda _env_file: {
            "IDENTITY_DOMAIN_URL": "https://idcs.example.identity.oraclecloud.com",
            "CONFIDENTIAL_APPLICATION_ID": "client-id",
            "CONFIDENTIAL_APPLICATION_SECRET": "client-secret",
            "IDCS_SCOPE": "demo-agent/.default",
        },
    )
    monkeypatch.setattr(
        agent_cli,
        "fetch_idcs_access_token",
        lambda _config: "jwt-token",
    )

    exit_code = agent_cli.main(["--auth", "idcs", "--print-token-only"])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "IDCS access token" in output
    assert "jwt-token" in output


def test_parse_sse_lines() -> None:
    """Test Server-Sent Event parsing."""

    events = list(
        parse_sse_lines(
            [
                "event: metadata\n",
                'data: {"conversation_id": "conv-123"}\n',
                "\n",
                "event: token\n",
                'data: {"text": "Hello"}\n',
                "\n",
                "event: references\n",
                'data: {"references": [{"file_name": "guide.md", "page": 3, "metadata": {}}]}\n',
                "\n",
                "event: usage\n",
                (
                    'data: {"usage": {"input_tokens": 10, "output_tokens": 5, '
                    '"total_tokens": 15, "reasoning_tokens": 1}}\n'
                ),
                "\n",
                "event: done\n",
                'data: {"conversation_id": "conv-123"}\n',
                "\n",
            ]
        )
    )

    assert [event.name for event in events] == [
        "metadata",
        "token",
        "references",
        "usage",
        "done",
    ]
    assert events[0].data == {"conversation_id": "conv-123"}
    assert events[1].data == {"text": "Hello"}
    assert events[2].data == {
        "references": [{"file_name": "guide.md", "page": 3, "metadata": {}}]
    }
    assert events[3].data == {
        "usage": {
            "input_tokens": 10,
            "output_tokens": 5,
            "total_tokens": 15,
            "reasoning_tokens": 1,
        }
    }


def test_parse_sse_lines_infers_events_when_gateway_strips_event_names() -> None:
    """Test SSE parsing when a hosted gateway preserves only data frames."""

    events = list(
        parse_sse_lines(
            [
                'data: {"conversation_id": "conv-123"}\n',
                "\n",
                'data: {"text": "ok"}\n',
                "\n",
                'data: {"references": []}\n',
                "\n",
                (
                    'data: {"usage": {"input_tokens": 10, "output_tokens": 5, '
                    '"total_tokens": 15, "reasoning_tokens": 0}}\n'
                ),
                "\n",
                'data: {"conversation_id": "conv-123"}\n',
                "\n",
            ]
        )
    )

    assert [event.name for event in events] == [
        "metadata",
        "token",
        "references",
        "usage",
        "done",
    ]
    assert events[1].data == {"text": "ok"}


def test_render_json_response(monkeypatch: pytest.MonkeyPatch, capsys: Any) -> None:
    """Test non-streaming JSON response rendering."""

    def fake_send_json_request(
        endpoint: str,
        payload: dict[str, object],
    ) -> dict[str, object]:
        """Return a fake JSON response payload.

        Args:
            endpoint: Agent endpoint URL.
            payload: Agent request payload.

        Returns:
            dict[str, object]: Fake agent response payload.
        """

        assert endpoint == "http://localhost:8080/responses"
        assert payload["stream"] is False
        return {
            "conversation_id": "conv-123",
            "response_id": "resp-123",
            "agent_response": "JSON answer",
            "references": [{"file_name": "guide.md", "page": 3, "metadata": {}}],
            "usage": {
                "input_tokens": 10,
                "output_tokens": 5,
                "total_tokens": 15,
                "reasoning_tokens": 1,
            },
            "error": None,
        }

    monkeypatch.setattr(agent_cli, "send_json_request", fake_send_json_request)

    render_json_response(
        "http://localhost:8080/responses",
        {
            "new_conversation": True,
            "user_request": "Hello",
            "stream": False,
        },
    )

    output = capsys.readouterr().out

    assert "Stream: false" in output
    assert "[conversation: conv-123]" in output
    assert "JSON answer" in output
    assert "[references: 1]" in output
    assert "1. guide.md, page 3" in output
    assert "[tokens: input 10, output 5, total 15, reasoning 1]" in output


def test_render_stream_prints_references(
    monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    """Test streaming reference rendering."""

    def fake_send_streaming_request(
        endpoint: str,
        payload: dict[str, object],
    ) -> list[agent_cli.SseEvent]:
        """Return fake streaming events.

        Args:
            endpoint: Agent endpoint URL.
            payload: Agent request payload.

        Returns:
            list[agent_cli.SseEvent]: Fake SSE events.
        """

        assert endpoint == "http://localhost:8080/responses"
        assert payload["stream"] is True
        return [
            agent_cli.SseEvent("metadata", {"conversation_id": "conv-123"}),
            agent_cli.SseEvent("token", {"text": "Streaming answer"}),
            agent_cli.SseEvent(
                "references",
                {"references": [{"file_name": "guide.md", "page": 3}]},
            ),
            agent_cli.SseEvent(
                "usage",
                {
                    "usage": {
                        "input_tokens": 10,
                        "output_tokens": 5,
                        "total_tokens": 15,
                        "reasoning_tokens": 1,
                    }
                },
            ),
            agent_cli.SseEvent("done", {"conversation_id": "conv-123"}),
        ]

    monkeypatch.setattr(
        agent_cli, "send_streaming_request", fake_send_streaming_request
    )

    render_stream(
        "http://localhost:8080/responses",
        {
            "new_conversation": True,
            "user_request": "Hello",
            "stream": True,
        },
    )

    output = capsys.readouterr().out

    assert "Streaming answer" in output
    assert "[references: 1]" in output
    assert "1. guide.md, page 3" in output
    assert "[tokens: input 10, output 5, total 15, reasoning 1]" in output


def test_render_stream_stops_after_done(
    monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    """Test streaming rendering stops when the agent emits done."""

    consumed_events: list[str] = []

    def fake_send_streaming_request(
        _endpoint: str,
        _payload: dict[str, object],
    ) -> Iterator[agent_cli.SseEvent]:
        """Yield a done event followed by an event that must not be consumed.

        Args:
            _endpoint: Agent endpoint URL.
            _payload: Agent request payload.

        Yields:
            SseEvent: Fake stream events.
        """

        for event in [
            agent_cli.SseEvent("metadata", {"conversation_id": "conv-123"}),
            agent_cli.SseEvent("token", {"text": "Streaming answer"}),
            agent_cli.SseEvent("done", {"conversation_id": "conv-123"}),
            agent_cli.SseEvent("token", {"text": "Should not print"}),
        ]:
            consumed_events.append(event.name)
            yield event

    monkeypatch.setattr(
        agent_cli, "send_streaming_request", fake_send_streaming_request
    )

    render_stream(
        "http://localhost:8080/responses",
        {
            "new_conversation": True,
            "user_request": "Hello",
            "stream": True,
        },
    )

    output = capsys.readouterr().out

    assert consumed_events == ["metadata", "token", "done"]
    assert "Streaming answer" in output
    assert "Should not print" not in output


def test_render_stream_stops_after_error(
    monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    """Test streaming rendering stops when the agent emits an error."""

    consumed_events: list[str] = []

    def fake_send_streaming_request(
        _endpoint: str,
        _payload: dict[str, object],
    ) -> Iterator[agent_cli.SseEvent]:
        """Yield an error event followed by an event that must not be consumed.

        Args:
            _endpoint: Agent endpoint URL.
            _payload: Agent request payload.

        Yields:
            SseEvent: Fake stream events.
        """

        for event in [
            agent_cli.SseEvent("metadata", {"conversation_id": "conv-123"}),
            agent_cli.SseEvent("error", {"error": "upstream unavailable"}),
            agent_cli.SseEvent("token", {"text": "Should not print"}),
        ]:
            consumed_events.append(event.name)
            yield event

    monkeypatch.setattr(
        agent_cli, "send_streaming_request", fake_send_streaming_request
    )

    render_stream(
        "http://localhost:8080/responses",
        {
            "new_conversation": True,
            "user_request": "Hello",
            "stream": True,
        },
    )

    output = capsys.readouterr().out

    assert consumed_events == ["metadata", "error"]
    assert "[error] upstream unavailable" in output
    assert "Should not print" not in output
