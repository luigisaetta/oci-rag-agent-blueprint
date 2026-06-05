"""
Author: L. Saetta
Date last modified: 2026-06-05
License: MIT
Description: Command-line client for testing the local OCI RAG agent endpoint.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from typing import Iterable
from urllib import error, request

DEFAULT_ENDPOINT = "http://localhost:8080/responses"
JSON_HEADERS = {"Content-Type": "application/json", "Accept": "application/json"}
STREAM_HEADERS = {"Content-Type": "application/json", "Accept": "text/event-stream"}


@dataclass(frozen=True)
class SseEvent:
    """Server-Sent Event parsed from the agent stream.

    Attributes:
        name: Event name.
        data: Parsed JSON event payload.
    """

    name: str
    data: dict[str, object]


def parse_bool(value: str) -> bool:
    """Parse a command-line boolean value.

    Args:
        value: Text value provided by the user.

    Returns:
        bool: Parsed boolean value.

    Raises:
        argparse.ArgumentTypeError: If the value is not true or false.
    """

    normalized_value = value.strip().lower()
    if normalized_value == "true":
        return True
    if normalized_value == "false":
        return False

    raise argparse.ArgumentTypeError("value must be true or false")


def build_payload(
    create_conversation: bool,
    user_request: str,
    stream: bool = True,
    conversation_id: str | None = None,
) -> dict[str, object]:
    """Build the JSON payload expected by the agent.

    Args:
        create_conversation: Whether to create a new conversation.
        user_request: User request text.
        stream: Whether to request Server-Sent Event streaming.
        conversation_id: Existing conversation identifier.

    Returns:
        dict[str, object]: Agent request payload.

    Raises:
        ValueError: If an existing conversation is requested without an ID.
    """

    payload: dict[str, object] = {
        "new_conversation": create_conversation,
        "user_request": user_request,
        "stream": stream,
    }

    if not create_conversation:
        if not conversation_id:
            raise ValueError(
                "conversation_id is required when create_conversation is false"
            )
        payload["conversation_id"] = conversation_id

    return payload


def parse_sse_lines(lines: Iterable[str]) -> Iterable[SseEvent]:
    """Parse Server-Sent Event lines.

    Args:
        lines: Iterable of decoded text lines.

    Yields:
        SseEvent: Parsed SSE events with JSON payloads.
    """

    event_name = "message"
    data_lines: list[str] = []

    for line in lines:
        clean_line = line.rstrip("\n")
        if not clean_line:
            if data_lines:
                yield _build_sse_event(event_name, data_lines)
            event_name = "message"
            data_lines = []
            continue

        if clean_line.startswith("event:"):
            event_name = clean_line.split(":", 1)[1].strip()
        elif clean_line.startswith("data:"):
            data_lines.append(clean_line.split(":", 1)[1].strip())

    if data_lines:
        yield _build_sse_event(event_name, data_lines)


def _build_sse_event(event_name: str, data_lines: list[str]) -> SseEvent:
    """Build one parsed Server-Sent Event.

    Args:
        event_name: SSE event name.
        data_lines: One or more SSE data lines.

    Returns:
        SseEvent: Parsed event with JSON payload.
    """

    data = "\n".join(data_lines)
    return SseEvent(name=event_name, data=json.loads(data))


def send_streaming_request(
    endpoint: str, payload: dict[str, object]
) -> Iterable[SseEvent]:
    """Send a streaming request to the agent endpoint.

    Args:
        endpoint: Agent endpoint URL.
        payload: JSON request payload.

    Yields:
        SseEvent: Events returned by the agent stream.

    Raises:
        RuntimeError: If the HTTP request fails.
    """

    http_request = _build_post_request(endpoint, payload, STREAM_HEADERS)

    try:
        with request.urlopen(http_request, timeout=120) as response:
            lines = (line.decode("utf-8") for line in response)
            yield from parse_sse_lines(lines)
    except error.HTTPError as exc:
        message = exc.read().decode("utf-8")
        raise RuntimeError(f"HTTP {exc.code}: {message}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"Unable to reach agent endpoint: {exc.reason}") from exc


def send_json_request(endpoint: str, payload: dict[str, object]) -> dict[str, object]:
    """Send a non-streaming JSON request to the agent endpoint.

    Args:
        endpoint: Agent endpoint URL.
        payload: JSON request payload.

    Returns:
        dict[str, object]: Parsed JSON response payload.

    Raises:
        RuntimeError: If the HTTP request fails.
    """

    http_request = _build_post_request(endpoint, payload, JSON_HEADERS)

    try:
        with request.urlopen(http_request, timeout=120) as response:
            response_body = response.read().decode("utf-8")
            return json.loads(response_body)
    except error.HTTPError as exc:
        message = exc.read().decode("utf-8")
        raise RuntimeError(f"HTTP {exc.code}: {message}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"Unable to reach agent endpoint: {exc.reason}") from exc


def _build_post_request(
    endpoint: str,
    payload: dict[str, object],
    headers: dict[str, str],
) -> request.Request:
    """Build an HTTP POST request for the agent endpoint.

    Args:
        endpoint: Agent endpoint URL.
        payload: JSON request payload.
        headers: HTTP headers for the expected response mode.

    Returns:
        request.Request: Configured HTTP request.
    """

    request_body = json.dumps(payload).encode("utf-8")
    return request.Request(
        endpoint,
        data=request_body,
        headers=headers,
        method="POST",
    )


def render_stream(endpoint: str, payload: dict[str, object]) -> None:
    """Render a streaming response to the console.

    Args:
        endpoint: Agent endpoint URL.
        payload: JSON request payload.
    """

    _print_request_header(endpoint, payload, stream=True)
    print("Response")
    print("--------")
    references: list[object] = []

    for event in send_streaming_request(endpoint, payload):
        if event.name == "metadata":
            conversation_id = event.data.get("conversation_id", "")
            print(f"\n[conversation: {conversation_id}]\n")
        elif event.name == "token":
            print(event.data.get("text", ""), end="", flush=True)
        elif event.name == "references":
            event_references = event.data.get("references", [])
            if isinstance(event_references, list):
                references = event_references
        elif event.name == "error":
            print(f"\n\n[error] {event.data.get('error', 'Unknown error')}")
        elif event.name == "done":
            _print_references(references)
            print("\n\n[done]")


def render_json_response(endpoint: str, payload: dict[str, object]) -> None:
    """Render a non-streaming JSON response to the console.

    Args:
        endpoint: Agent endpoint URL.
        payload: JSON request payload.
    """

    _print_request_header(endpoint, payload, stream=False)

    response_payload = send_json_request(endpoint, payload)
    conversation_id = response_payload.get("conversation_id", "")
    if conversation_id:
        print(f"[conversation: {conversation_id}]\n")

    error_message = response_payload.get("error")
    if error_message:
        print(f"[error] {error_message}")
        return

    print("Response")
    print("--------")
    print(response_payload.get("agent_response", ""))
    _print_references(response_payload.get("references", []))


def _print_references(references: object) -> None:
    """Print response references in a readable CLI format.

    Args:
        references: References returned by the agent.
    """

    if not isinstance(references, list):
        return

    print(f"\n[references: {len(references)}]")
    for index, reference in enumerate(references, start=1):
        if not isinstance(reference, dict):
            continue

        file_name = reference.get("file_name", "unknown")
        page = reference.get("page")
        page_label = f", page {page}" if page else ""
        print(f"  {index}. {file_name}{page_label}")


def _print_request_header(
    endpoint: str,
    payload: dict[str, object],
    stream: bool,
) -> None:
    """Print the common CLI request header.

    Args:
        endpoint: Agent endpoint URL.
        payload: JSON request payload.
        stream: Whether the request uses streaming.
    """

    print("OCI RAG Agent CLI")
    print("=================")
    print(f"Endpoint: {endpoint}")
    print(f"Create conversation: {payload['new_conversation']}")
    print(f"Stream: {str(stream).lower()}")
    if "conversation_id" in payload:
        print(f"Conversation id: {payload['conversation_id']}")
    print()


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line argument parser.

    Returns:
        argparse.ArgumentParser: Configured parser.
    """

    parser = argparse.ArgumentParser(description="Test the OCI RAG agent endpoint.")
    parser.add_argument(
        "--endpoint",
        default=DEFAULT_ENDPOINT,
        help=f"Agent endpoint URL. Default: {DEFAULT_ENDPOINT}",
    )
    parser.add_argument(
        "--create-conversation",
        required=True,
        type=parse_bool,
        help="Use true to create a new conversation, false to reuse one.",
    )
    parser.add_argument(
        "--conversation-id",
        help="Existing conversation identifier. Required when create-conversation is false.",
    )
    parser.add_argument(
        "--stream",
        default=True,
        type=parse_bool,
        help="Use true for SSE streaming, false for a JSON response. Default: true.",
    )
    parser.add_argument("user_request", help="User request text.")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the command-line client.

    Args:
        argv: Optional command-line argument list for tests.

    Returns:
        int: Process exit code.
    """

    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        payload = build_payload(
            create_conversation=args.create_conversation,
            conversation_id=args.conversation_id,
            stream=args.stream,
            user_request=args.user_request,
        )
        if args.stream:
            render_stream(args.endpoint, payload)
        else:
            render_json_response(args.endpoint, payload)
    except ValueError as exc:
        parser.error(str(exc))
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
