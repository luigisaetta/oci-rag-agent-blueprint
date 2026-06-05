"""
Author: L. Saetta
Date last modified: 2026-06-05
License: MIT
Description: Unit tests for the OCI RAG agent command-line test client.
"""

from __future__ import annotations

import argparse

import pytest

from clients.agent_cli import build_payload, parse_bool, parse_sse_lines


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
                "event: done\n",
                'data: {"conversation_id": "conv-123"}\n',
                "\n",
            ]
        )
    )

    assert [event.name for event in events] == ["metadata", "token", "done"]
    assert events[0].data == {"conversation_id": "conv-123"}
    assert events[1].data == {"text": "Hello"}
