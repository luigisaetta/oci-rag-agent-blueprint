"""
Author: L. Saetta
Date last modified: 2026-06-18
License: MIT
Description: Standalone client for requesting an OCI IAM IDCS access token.
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
from datetime import datetime, timezone
from typing import Any

from clients.agent_cli import (
    fetch_idcs_access_token,
    build_client_environment,
    missing_idcs_env_vars,
    resolve_idcs_token_config,
)


def build_parser() -> argparse.ArgumentParser:
    """Build the standalone IDCS token client argument parser.

    Returns:
        argparse.ArgumentParser: Configured parser.
    """

    parser = argparse.ArgumentParser(
        description="Request and print an OCI IAM Identity Domain access token."
    )
    parser.add_argument(
        "--env-file",
        default=".env",
        help="Environment file with IDCS token settings. Default: .env",
    )
    return parser


def decode_jwt_section(encoded_section: str) -> dict[str, Any]:
    """Decode one base64url-encoded JWT JSON section.

    Args:
        encoded_section: Encoded JWT header or payload section.

    Returns:
        dict[str, Any]: Decoded JSON object.

    Raises:
        ValueError: If the section is not valid base64url JSON object data.
    """

    padding = "=" * (-len(encoded_section) % 4)
    try:
        raw_section = base64.urlsafe_b64decode(
            f"{encoded_section}{padding}".encode("ascii")
        )
        decoded_section = json.loads(raw_section.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError("JWT section is not valid base64url JSON.") from exc

    if not isinstance(decoded_section, dict):
        raise ValueError("JWT section must decode to a JSON object.")
    return decoded_section


def decode_jwt(token: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Decode a JWT header and payload without verifying its signature.

    Args:
        token: JWT access token.

    Returns:
        tuple[dict[str, Any], dict[str, Any]]: Decoded header and payload.

    Raises:
        ValueError: If the token does not have a JWT shape or cannot be decoded.
    """

    token_parts = token.split(".")
    if len(token_parts) != 3:
        raise ValueError("Token is not a three-part JWT.")
    return decode_jwt_section(token_parts[0]), decode_jwt_section(token_parts[1])


def format_epoch_claim(value: object) -> str | None:
    """Format a JWT epoch timestamp claim for display.

    Args:
        value: Claim value.

    Returns:
        str | None: ISO timestamp when the value is an integer, otherwise None.
    """

    if not isinstance(value, int):
        return None
    return datetime.fromtimestamp(value, timezone.utc).isoformat()


def print_jwt_details(token: str) -> None:
    """Print decoded JWT header and payload details.

    Args:
        token: JWT access token.
    """

    try:
        header, payload = decode_jwt(token)
    except ValueError as exc:
        print(f"[warning] JWT details could not be decoded: {exc}")
        return

    print("JWT header")
    print("----------")
    print(json.dumps(header, indent=2, sort_keys=True))
    print()
    print("JWT payload")
    print("-----------")
    print(json.dumps(payload, indent=2, sort_keys=True))

    time_claims = {
        claim_name: format_epoch_claim(payload.get(claim_name))
        for claim_name in ("iat", "nbf", "exp")
    }
    rendered_time_claims = {
        claim_name: timestamp
        for claim_name, timestamp in time_claims.items()
        if timestamp is not None
    }
    if rendered_time_claims:
        print()
        print("JWT time claims")
        print("---------------")
        for claim_name, timestamp in rendered_time_claims.items():
            print(f"{claim_name}: {timestamp}")


def main(argv: list[str] | None = None) -> int:
    """Run the standalone IDCS token client.

    Args:
        argv: Optional command-line argument list for tests.

    Returns:
        int: Process exit code.
    """

    parser = build_parser()
    args = parser.parse_args(argv)
    environment = build_client_environment(args.env_file)
    token_config = resolve_idcs_token_config(environment)

    if not token_config:
        missing_values = ", ".join(missing_idcs_env_vars(environment))
        print(
            f"Error: Missing IDCS token configuration: {missing_values}",
            file=sys.stderr,
        )
        return 1

    try:
        access_token = fetch_idcs_access_token(token_config)
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print("IDCS access token")
    print("=================")
    print(access_token)
    print()
    print_jwt_details(access_token)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
