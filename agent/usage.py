"""
Author: L. Saetta
Date last modified: 2026-06-06
License: MIT
Description: Token usage extraction helpers for Responses API payloads.
"""

from __future__ import annotations

from typing import Any


def extract_usage(source: Any) -> dict[str, int | None] | None:
    """Extract normalized token usage from a Responses API payload.

    Args:
        source: Response object or dictionary returned by the Responses API.

    Returns:
        dict[str, int | None] | None: Normalized usage payload, or None when
            usage is not available.
    """

    usage = _get_value(source, "usage")
    if usage is None:
        response = _get_value(source, "response")
        usage = _get_value(response, "usage")

    if usage is None:
        return None

    return {
        "input_tokens": _get_integer(usage, "input_tokens"),
        "output_tokens": _get_integer(usage, "output_tokens"),
        "total_tokens": _get_integer(usage, "total_tokens"),
        "reasoning_tokens": _extract_reasoning_tokens(usage),
    }


def _extract_reasoning_tokens(usage: Any) -> int | None:
    """Extract reasoning token usage from nested output token details.

    Args:
        usage: Responses API usage object or dictionary.

    Returns:
        int | None: Reasoning token count when available.
    """

    output_details = _get_value(usage, "output_tokens_details")
    if output_details is None:
        return None

    return _get_integer(output_details, "reasoning_tokens")


def _get_integer(source: Any, field_name: str) -> int | None:
    """Read an integer field from a dictionary or object.

    Args:
        source: Object or dictionary to inspect.
        field_name: Field name to read.

    Returns:
        int | None: Integer value when available.
    """

    value = _get_value(source, field_name)
    if isinstance(value, int):
        return value

    return None


def _get_value(source: Any, field_name: str) -> Any:
    """Read one value from a dictionary or object.

    Args:
        source: Object or dictionary to inspect.
        field_name: Field name to read.

    Returns:
        Any: Field value, or None when missing.
    """

    if isinstance(source, dict):
        return source.get(field_name)

    return getattr(source, field_name, None)
