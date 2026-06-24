"""
Author: L. Saetta
Date last modified: 2026-06-24
License: MIT
Description: Helpers for safe runtime environment diagnostics.
"""

from __future__ import annotations

from collections.abc import Mapping

SECRET_NAME_FRAGMENTS = (
    "SECRET",
    "TOKEN",
    "PASSWORD",
    "PASS",
    "API_KEY",
    "PRIVATE_KEY",
    "CLIENT_SECRET",
    "AUTH",
)


def build_environment_diagnostics(
    environment: Mapping[str, str],
) -> dict[str, dict[str, str] | list[str]]:
    """Build a redacted diagnostic view of process environment variables.

    Args:
        environment: Environment variables keyed by variable name.

    Returns:
        dict[str, dict[str, str] | list[str]]: Diagnostic payload containing
            non-secret values in `environment` and secret variable names in
            `redacted`.
    """

    visible_environment: dict[str, str] = {}
    redacted_names: list[str] = []

    for name in sorted(environment):
        if is_secret_environment_name(name):
            redacted_names.append(name)
            continue

        visible_environment[name] = environment[name]

    return {
        "environment": visible_environment,
        "redacted": redacted_names,
    }


def is_secret_environment_name(name: str) -> bool:
    """Return whether an environment variable name should be treated as secret.

    Args:
        name: Environment variable name to classify.

    Returns:
        bool: `True` when the variable name contains a secret-like fragment.
    """

    normalized_name = name.upper()
    return any(fragment in normalized_name for fragment in SECRET_NAME_FRAGMENTS)
