"""
Author: L. Saetta
Date last modified: 2026-06-18
License: MIT
Description: Standalone client for requesting an OCI IAM IDCS access token.
"""

from __future__ import annotations

import argparse
import sys

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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
