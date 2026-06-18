"""
Author: L. Saetta
Date last modified: 2026-06-18
License: MIT
Description: Diagnostic self-test client for OCI Hosted Application deployments.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from urllib import error, request

from clients.agent_cli import (
    build_client_environment,
    build_payload,
    maybe_fetch_idcs_access_token,
    parse_bool,
    send_json_request,
    send_streaming_request,
)
from clients.idcs_token_client import decode_jwt, format_epoch_claim


@dataclass(frozen=True)
class HostedSelfTestConfig:
    """Configuration for a Hosted Application self-test run.

    Attributes:
        endpoint: Hosted Application `/responses` endpoint.
        auth_mode: Token acquisition mode.
        env_file: Environment file path.
        create_conversation: Whether to create a new conversation.
        conversation_id: Existing conversation ID when reusing one.
        user_request: User request text.
        show_output: Whether to print agent response text.
    """

    endpoint: str
    auth_mode: str
    env_file: str
    create_conversation: bool
    conversation_id: str | None
    user_request: str
    show_output: bool


@dataclass(frozen=True)
class HostedRequestConfig:
    """Configuration for one Hosted Application `/responses` check.

    Attributes:
        endpoint: Hosted Application `/responses` endpoint.
        create_conversation: Whether to create a new conversation.
        conversation_id: Existing conversation ID when reusing one.
        user_request: User request text.
        access_token: Optional IDCS access token.
        show_output: Whether to print agent response text.
    """

    endpoint: str
    create_conversation: bool
    conversation_id: str | None
    user_request: str
    access_token: str | None
    show_output: bool


def build_parser() -> argparse.ArgumentParser:
    """Build the hosted self-test command-line parser.

    Returns:
        argparse.ArgumentParser: Configured parser.
    """

    parser = argparse.ArgumentParser(
        description="Run diagnostics against an OCI Hosted Application endpoint."
    )
    parser.add_argument(
        "--endpoint",
        required=True,
        help="Hosted Application /actions/invoke/responses endpoint.",
    )
    parser.add_argument(
        "--auth",
        choices=("auto", "none", "idcs"),
        default="idcs",
        help="Token acquisition mode. Default: idcs.",
    )
    parser.add_argument(
        "--env-file",
        default=".env",
        help="Environment file for optional IDCS token settings. Default: .env",
    )
    parser.add_argument(
        "--create-conversation",
        default=True,
        type=parse_bool,
        help="Use true to create a new conversation, false to reuse one.",
    )
    parser.add_argument(
        "--conversation-id",
        help="Existing conversation identifier. Required when create-conversation is false.",
    )
    parser.add_argument(
        "--show-output",
        default=False,
        type=parse_bool,
        help="Use true to print agent response text. Default: false.",
    )
    parser.add_argument("user_request", help="User request text.")
    return parser


def build_health_endpoint(responses_endpoint: str) -> str:
    """Build the health endpoint matching a responses endpoint.

    Args:
        responses_endpoint: Hosted Application `/responses` endpoint.

    Returns:
        str: Matching Hosted Application `/health` endpoint.
    """

    clean_endpoint = responses_endpoint.rstrip("/")
    if clean_endpoint.endswith("/responses"):
        return f"{clean_endpoint.removesuffix('/responses')}/health"
    return f"{clean_endpoint}/health"


def run_self_test(config: HostedSelfTestConfig) -> None:
    """Run the Hosted Application diagnostic self-test.

    Args:
        config: Self-test configuration.

    Raises:
        RuntimeError: If any diagnostic step fails.
    """

    print("Hosted Application self-test")
    print("============================")
    print(f"Responses endpoint: {config.endpoint}")
    print(f"Health endpoint:    {build_health_endpoint(config.endpoint)}")
    print()

    environment = build_client_environment(config.env_file)
    access_token = _step_token(config.auth_mode, environment)
    _step_health(build_health_endpoint(config.endpoint), access_token)
    request_config = HostedRequestConfig(
        endpoint=config.endpoint,
        create_conversation=config.create_conversation,
        conversation_id=config.conversation_id,
        user_request=config.user_request,
        access_token=access_token,
        show_output=config.show_output,
    )
    _step_json_response(request_config)
    _step_streaming_response(request_config)
    print("[PASS] Hosted Application self-test completed.")


def _step_token(auth_mode: str, environment: dict[str, str]) -> str | None:
    """Validate token acquisition and print non-secret JWT diagnostics."""

    if auth_mode == "none":
        print("[SKIP] IDCS token acquisition disabled.")
        return None

    access_token = maybe_fetch_idcs_access_token(auth_mode, environment)
    if access_token is None:
        print("[SKIP] IDCS token configuration not present.")
        return None

    _print_token_diagnostics(access_token)
    return access_token


def _print_token_diagnostics(access_token: str) -> None:
    """Print decoded JWT diagnostics without printing the raw token."""

    try:
        _header, payload = decode_jwt(access_token)
    except ValueError as exc:
        raise RuntimeError(f"IDCS token is not a decodable JWT: {exc}") from exc

    print("[PASS] IDCS token acquired.")
    print(f"       JWT audience: {payload.get('aud', 'n/a')}")
    print(f"       JWT scope:    {payload.get('scope', 'n/a')}")
    print(f"       JWT expires:  {format_epoch_claim(payload.get('exp'))}")


def _step_health(health_endpoint: str, access_token: str | None) -> None:
    """Validate the Hosted Application health endpoint."""

    headers = {"Accept": "application/json"}
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"
    health_request = request.Request(health_endpoint, headers=headers, method="GET")

    try:
        with request.urlopen(health_request, timeout=60) as response:
            response_body = response.read().decode("utf-8")
    except error.HTTPError as exc:
        message = exc.read().decode("utf-8")
        raise RuntimeError(
            f"Health check failed with HTTP {exc.code}: {message}"
        ) from exc
    except error.URLError as exc:
        raise RuntimeError(f"Unable to reach health endpoint: {exc.reason}") from exc

    try:
        health_payload = json.loads(response_body)
    except json.JSONDecodeError:
        health_payload = {"raw": response_body}

    print("[PASS] Health endpoint responded.")
    print(f"       Payload: {health_payload}")


def _step_json_response(config: HostedRequestConfig) -> None:
    """Validate non-streaming `/responses` behavior."""

    payload = build_payload(
        create_conversation=config.create_conversation,
        conversation_id=config.conversation_id,
        stream=False,
        user_request=config.user_request,
    )
    response_payload = send_json_request(config.endpoint, payload, config.access_token)
    if response_payload.get("error"):
        raise RuntimeError(
            f"Non-streaming response returned error: {response_payload['error']}"
        )

    answer = str(response_payload.get("agent_response", ""))
    references = response_payload.get("references", [])
    print("[PASS] Non-streaming /responses request completed.")
    print(f"       Conversation: {response_payload.get('conversation_id', 'n/a')}")
    print(f"       Answer chars: {len(answer)}")
    print(
        f"       References:   {len(references) if isinstance(references, list) else 'n/a'}"
    )
    if config.show_output:
        print("       Agent output:")
        print(_indent_output(answer))


def _step_streaming_response(config: HostedRequestConfig) -> None:
    """Validate streaming `/responses` behavior."""

    payload = build_payload(
        create_conversation=config.create_conversation,
        conversation_id=config.conversation_id,
        stream=True,
        user_request=config.user_request,
    )
    token_chars = 0
    references_count = 0
    conversation = "n/a"
    response_chunks: list[str] = []

    for event in send_streaming_request(config.endpoint, payload, config.access_token):
        if event.name == "metadata":
            conversation = str(event.data.get("conversation_id", "n/a"))
        elif event.name == "token":
            text = str(event.data.get("text", ""))
            token_chars += len(text)
            response_chunks.append(text)
        elif event.name == "references":
            references = event.data.get("references", [])
            if isinstance(references, list):
                references_count = len(references)
        elif event.name == "error":
            raise RuntimeError(
                f"Streaming response returned error: {event.data.get('error')}"
            )
        elif event.name == "done":
            print("[PASS] Streaming /responses request completed.")
            print(f"       Conversation: {conversation}")
            print(f"       Stream chars: {token_chars}")
            print(f"       References:   {references_count}")
            if config.show_output:
                print("       Agent stream output:")
                print(_indent_output("".join(response_chunks)))
            return

    raise RuntimeError("Streaming response ended without a done event.")


def _indent_output(text: str) -> str:
    """Indent multi-line agent output for diagnostic display.

    Args:
        text: Agent response text.

    Returns:
        str: Indented response text.
    """

    if not text:
        return "         <empty>"
    return "\n".join(f"         {line}" for line in text.splitlines())


def main(argv: list[str] | None = None) -> int:
    """Run the hosted self-test client.

    Args:
        argv: Optional command-line arguments for tests.

    Returns:
        int: Process exit code.
    """

    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        run_self_test(
            HostedSelfTestConfig(
                endpoint=args.endpoint,
                auth_mode=args.auth,
                env_file=args.env_file,
                create_conversation=args.create_conversation,
                conversation_id=args.conversation_id,
                user_request=args.user_request,
                show_output=args.show_output,
            )
        )
    except ValueError as exc:
        parser.error(str(exc))
    except RuntimeError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
