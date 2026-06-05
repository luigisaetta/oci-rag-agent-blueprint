"""
Author: L. Saetta
Date last modified: 2026-06-05
License: MIT
Description: Unit tests for the OCI RAG agent command-line test client.
"""

from __future__ import annotations

import argparse
from typing import Any

import pytest

from clients import agent_cli
from clients.agent_cli import (
    build_payload,
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
