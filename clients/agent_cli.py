"""
Author: L. Saetta
Date last modified: 2026-06-18
License: MIT
Description: Command-line client for testing the local OCI RAG agent endpoint.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
from dataclasses import dataclass
from typing import Iterable
from urllib import error, parse, request

DEFAULT_ENDPOINT = "http://localhost:8080/responses"
JSON_HEADERS = {"Content-Type": "application/json", "Accept": "application/json"}
STREAM_HEADERS = {"Content-Type": "application/json", "Accept": "text/event-stream"}
IDCS_AUTH_ENV_VARS = (
    "IDENTITY_DOMAIN_URL",
    "CONFIDENTIAL_APPLICATION_ID",
    "CONFIDENTIAL_APPLICATION_SECRET",
    "IDCS_SCOPE",
)


@dataclass(frozen=True)
class SseEvent:
    """Server-Sent Event parsed from the agent stream.

    Attributes:
        name: Event name.
        data: Parsed JSON event payload.
    """

    name: str
    data: dict[str, object]


@dataclass(frozen=True)
class IdcsTokenConfig:
    """Configuration required to request an IDCS access token.

    Attributes:
        identity_domain_url: Exact Identity Domain URL from OCI Console.
        confidential_application_id: Confidential application client identifier.
        confidential_application_secret: Confidential application client secret.
        scope: OAuth scope requested for the Hosted Application.
    """

    identity_domain_url: str
    confidential_application_id: str
    confidential_application_secret: str
    scope: str


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


def load_env_file(path: str) -> dict[str, str]:
    """Load simple key-value pairs from a dotenv-style file.

    Args:
        path: Path to the environment file.

    Returns:
        dict[str, str]: Parsed environment values. Missing files return an empty
        dictionary.
    """

    if not path or not os.path.exists(path):
        return {}

    values: dict[str, str] = {}
    with open(path, encoding="utf-8") as env_file:
        for raw_line in env_file:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, value = line.split("=", maxsplit=1)
            values[name.strip()] = _strip_env_value(value.strip())
    return values


def _strip_env_value(value: str) -> str:
    """Strip optional dotenv quotes from an environment value.

    Args:
        value: Raw value text.

    Returns:
        str: Unquoted value.
    """

    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def build_client_environment(env_file: str) -> dict[str, str]:
    """Build the client environment from `.env` and process variables.

    Args:
        env_file: Dotenv file path.

    Returns:
        dict[str, str]: Combined environment where process variables win.
    """

    environment = load_env_file(env_file)
    environment.update(os.environ)
    return environment


def resolve_idcs_token_config(environment: dict[str, str]) -> IdcsTokenConfig | None:
    """Resolve IDCS token configuration from environment values.

    Args:
        environment: Environment values.

    Returns:
        IdcsTokenConfig | None: Token config when all required values are set.
    """

    values = {name: environment.get(name, "").strip() for name in IDCS_AUTH_ENV_VARS}
    if not all(values.values()):
        return None
    return IdcsTokenConfig(
        identity_domain_url=values["IDENTITY_DOMAIN_URL"],
        confidential_application_id=values["CONFIDENTIAL_APPLICATION_ID"],
        confidential_application_secret=values["CONFIDENTIAL_APPLICATION_SECRET"],
        scope=values["IDCS_SCOPE"],
    )


def missing_idcs_env_vars(environment: dict[str, str]) -> list[str]:
    """Return missing IDCS token environment variable names.

    Args:
        environment: Environment values.

    Returns:
        list[str]: Missing or empty variable names.
    """

    return [
        name for name in IDCS_AUTH_ENV_VARS if not environment.get(name, "").strip()
    ]


def build_token_endpoint_url(identity_domain_url: str) -> str:
    """Build the IDCS OAuth token endpoint URL.

    Args:
        identity_domain_url: Exact Identity Domain URL.

    Returns:
        str: OAuth token endpoint URL.
    """

    return f"{identity_domain_url.rstrip('/')}/oauth2/v1/token"


def fetch_idcs_access_token(config: IdcsTokenConfig) -> str:
    """Request an IDCS access token with client credentials.

    Args:
        config: IDCS token configuration.

    Returns:
        str: Access token returned by IDCS.

    Raises:
        RuntimeError: If IDCS rejects the request or omits the access token.
    """

    credentials = (
        f"{config.confidential_application_id}:"
        f"{config.confidential_application_secret}"
    ).encode("utf-8")
    auth_header = base64.b64encode(credentials).decode("ascii")
    form_body = parse.urlencode(
        {
            "grant_type": "client_credentials",
            "scope": config.scope,
        }
    ).encode("utf-8")
    token_request = request.Request(
        build_token_endpoint_url(config.identity_domain_url),
        data=form_body,
        headers={
            "Authorization": f"Basic {auth_header}",
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
        method="POST",
    )

    try:
        with request.urlopen(token_request, timeout=60) as response:
            token_payload = json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        message = exc.read().decode("utf-8")
        raise RuntimeError(
            f"IDCS token request failed with HTTP {exc.code}: {message}"
        ) from exc
    except error.URLError as exc:
        raise RuntimeError(
            f"Unable to reach IDCS token endpoint: {exc.reason}"
        ) from exc

    access_token = token_payload.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise RuntimeError("IDCS token response did not include access_token.")
    return access_token


def maybe_fetch_idcs_access_token(
    auth_mode: str,
    environment: dict[str, str],
) -> str | None:
    """Fetch an IDCS token when requested by the selected auth mode.

    Args:
        auth_mode: One of `auto`, `none`, or `idcs`.
        environment: Client environment values.

    Returns:
        str | None: Access token when fetched.

    Raises:
        RuntimeError: If `idcs` mode is selected and required values are missing.
    """

    if auth_mode == "none":
        return None

    token_config = resolve_idcs_token_config(environment)
    if token_config:
        return fetch_idcs_access_token(token_config)

    if auth_mode == "idcs":
        missing_values = ", ".join(missing_idcs_env_vars(environment))
        raise RuntimeError(f"Missing IDCS token configuration: {missing_values}")

    return None


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
    metadata_seen = False

    for line in lines:
        clean_line = line.rstrip("\n")
        if not clean_line:
            if data_lines:
                event = _build_sse_event(event_name, data_lines, metadata_seen)
                if event.name == "metadata":
                    metadata_seen = True
                yield event
            event_name = "message"
            data_lines = []
            continue

        if clean_line.startswith("event:"):
            event_name = clean_line.split(":", 1)[1].strip()
        elif clean_line.startswith("data:"):
            data_lines.append(clean_line.split(":", 1)[1].strip())

    if data_lines:
        yield _build_sse_event(event_name, data_lines, metadata_seen)


def _build_sse_event(
    event_name: str,
    data_lines: list[str],
    metadata_seen: bool = False,
) -> SseEvent:
    """Build one parsed Server-Sent Event.

    Args:
        event_name: SSE event name.
        data_lines: One or more SSE data lines.
        metadata_seen: Whether a metadata event has already been parsed.

    Returns:
        SseEvent: Parsed event with JSON payload.
    """

    data = "\n".join(data_lines)
    payload = json.loads(data)
    return SseEvent(
        name=_normalize_sse_event_name(event_name, payload, metadata_seen),
        data=payload,
    )


def _normalize_sse_event_name(
    event_name: str,
    payload: dict[str, object],
    metadata_seen: bool,
) -> str:
    """Infer stripped SSE event names from their payload shape.

    Some hosted gateways preserve `data:` frames but strip explicit `event:`
    lines. When that happens, the SSE event defaults to `message`; the CLI still
    needs to recognize the agent's payload contract and finish cleanly.

    Args:
        event_name: Event name parsed from the SSE frame.
        payload: Parsed event payload.
        metadata_seen: Whether a metadata event has already been parsed.

    Returns:
        str: Original or inferred SSE event name.
    """

    if event_name != "message":
        return event_name

    payload_key_events = {
        "text": "token",
        "references": "references",
        "usage": "usage",
        "error": "error",
    }
    for payload_key, inferred_event_name in payload_key_events.items():
        if payload_key in payload:
            return inferred_event_name

    if "conversation_id" in payload:
        return "done" if metadata_seen else "metadata"

    return event_name


def send_streaming_request(
    endpoint: str,
    payload: dict[str, object],
    access_token: str | None = None,
) -> Iterable[SseEvent]:
    """Send a streaming request to the agent endpoint.

    Args:
        endpoint: Agent endpoint URL.
        payload: JSON request payload.
        access_token: Optional IDCS access token to send as a Bearer token.

    Yields:
        SseEvent: Events returned by the agent stream.

    Raises:
        RuntimeError: If the HTTP request fails.
    """

    http_request = _build_post_request(endpoint, payload, STREAM_HEADERS, access_token)

    try:
        with request.urlopen(http_request, timeout=120) as response:
            lines = (line.decode("utf-8") for line in response)
            yield from parse_sse_lines(lines)
    except error.HTTPError as exc:
        message = exc.read().decode("utf-8")
        raise RuntimeError(f"HTTP {exc.code}: {message}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"Unable to reach agent endpoint: {exc.reason}") from exc


def send_json_request(
    endpoint: str,
    payload: dict[str, object],
    access_token: str | None = None,
) -> dict[str, object]:
    """Send a non-streaming JSON request to the agent endpoint.

    Args:
        endpoint: Agent endpoint URL.
        payload: JSON request payload.
        access_token: Optional IDCS access token to send as a Bearer token.

    Returns:
        dict[str, object]: Parsed JSON response payload.

    Raises:
        RuntimeError: If the HTTP request fails.
    """

    http_request = _build_post_request(endpoint, payload, JSON_HEADERS, access_token)

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
    access_token: str | None = None,
) -> request.Request:
    """Build an HTTP POST request for the agent endpoint.

    Args:
        endpoint: Agent endpoint URL.
        payload: JSON request payload.
        headers: HTTP headers for the expected response mode.
        access_token: Optional IDCS access token to send as a Bearer token.

    Returns:
        request.Request: Configured HTTP request.
    """

    request_body = json.dumps(payload).encode("utf-8")
    request_headers = dict(headers)
    if access_token:
        request_headers["Authorization"] = f"Bearer {access_token}"

    return request.Request(
        endpoint,
        data=request_body,
        headers=request_headers,
        method="POST",
    )


def render_stream(
    endpoint: str,
    payload: dict[str, object],
    access_token: str | None = None,
) -> None:
    """Render a streaming response to the console.

    Args:
        endpoint: Agent endpoint URL.
        payload: JSON request payload.
        access_token: Optional IDCS access token to send as a Bearer token.
    """

    _print_request_header(endpoint, payload, stream=True)
    print("Response")
    print("--------")
    references: list[object] = []
    usage: object = None

    for event in send_streaming_request(endpoint, payload, access_token):
        if event.name == "metadata":
            conversation_id = event.data.get("conversation_id", "")
            print(f"\n[conversation: {conversation_id}]\n")
        elif event.name == "token":
            print(event.data.get("text", ""), end="", flush=True)
        elif event.name == "references":
            event_references = event.data.get("references", [])
            if isinstance(event_references, list):
                references = event_references
        elif event.name == "usage":
            usage = event.data.get("usage")
        elif event.name == "error":
            print(f"\n\n[error] {event.data.get('error', 'Unknown error')}")
            return
        elif event.name == "done":
            _print_references(references)
            _print_usage(usage)
            print("\n\n[done]")
            return


def render_json_response(
    endpoint: str,
    payload: dict[str, object],
    access_token: str | None = None,
) -> None:
    """Render a non-streaming JSON response to the console.

    Args:
        endpoint: Agent endpoint URL.
        payload: JSON request payload.
        access_token: Optional IDCS access token to send as a Bearer token.
    """

    _print_request_header(endpoint, payload, stream=False)

    response_payload = send_json_request(endpoint, payload, access_token)
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
    _print_usage(response_payload.get("usage"))


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


def _print_usage(usage: object) -> None:
    """Print token usage in a compact format.

    Args:
        usage: Usage payload returned by the agent.
    """

    if not isinstance(usage, dict):
        return

    input_tokens = usage.get("input_tokens", "n/a")
    output_tokens = usage.get("output_tokens", "n/a")
    total_tokens = usage.get("total_tokens", "n/a")
    reasoning_tokens = usage.get("reasoning_tokens")

    details = f"input {input_tokens}, output {output_tokens}, total {total_tokens}"
    if reasoning_tokens is not None:
        details = f"{details}, reasoning {reasoning_tokens}"

    print(f"\n[tokens: {details}]")


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
    parser.add_argument(
        "--auth",
        choices=("auto", "none", "idcs"),
        default="auto",
        help=(
            "Token acquisition mode. auto fetches an IDCS token when all "
            "required variables are set. Default: auto."
        ),
    )
    parser.add_argument(
        "--env-file",
        default=".env",
        help="Environment file for optional IDCS token settings. Default: .env",
    )
    parser.add_argument(
        "--print-token-only",
        action="store_true",
        help="Fetch and print the IDCS token, then exit without calling the agent.",
    )
    parser.add_argument("user_request", nargs="?", help="User request text.")
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
        access_token = maybe_fetch_idcs_access_token(
            args.auth,
            build_client_environment(args.env_file),
        )
        if access_token:
            print("IDCS access token")
            print("=================")
            print(access_token)
            print()
        if args.print_token_only:
            if not access_token:
                raise RuntimeError(
                    "--print-token-only requires IDCS token configuration."
                )
            return 0

        if args.create_conversation is None:
            parser.error(
                "--create-conversation is required unless --print-token-only is used"
            )
        if not args.user_request:
            parser.error("user_request is required unless --print-token-only is used")

        payload = build_payload(
            create_conversation=args.create_conversation,
            conversation_id=args.conversation_id,
            stream=args.stream,
            user_request=args.user_request,
        )
        if args.stream:
            render_stream(args.endpoint, payload, access_token)
        else:
            render_json_response(args.endpoint, payload, access_token)
    except ValueError as exc:
        parser.error(str(exc))
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
