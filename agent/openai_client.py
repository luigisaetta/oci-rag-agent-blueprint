"""
Author: L. Saetta
Date last modified: 2026-06-23
License: MIT
Description: OpenAI-compatible client creation for OCI Enterprise AI.
"""

from __future__ import annotations

# pylint: disable=duplicate-code

import json
import os
from typing import Any

from openai import OpenAI

from agent.config import AgentSettings


def create_openai_client(settings: AgentSettings) -> Any:
    """Create an OpenAI-compatible client for OCI Enterprise AI.

    Args:
        settings: Runtime settings used to configure authentication and base URL.

    Returns:
        Any: Configured OpenAI client instance.
    """

    client_class = _resolve_client_class(settings)
    return client_class(
        api_key=settings.openai_api_key,
        base_url=settings.base_url,
        project=settings.oci_project_id,
        default_headers={
            "extra_body": json.dumps({"compartmentId": settings.oci_compartment_id})
        },
    )


def _resolve_client_class(settings: AgentSettings) -> Any:
    """Return the OpenAI-compatible client class for the current settings.

    Args:
        settings: Runtime settings that control optional Langfuse usage.

    Returns:
        Any: Standard OpenAI client class or Langfuse-instrumented equivalent.

    Raises:
        ValueError: If Langfuse is enabled but the package is unavailable.
    """

    if not settings.langfuse_enabled:
        return OpenAI

    _configure_langfuse_environment(settings)
    try:
        # pylint: disable=import-outside-toplevel
        from langfuse.openai import (
            OpenAI as LangfuseOpenAI,
        )
    except ImportError as exc:
        raise ValueError(
            "LANGFUSE_ENABLED is true but the langfuse package is not installed."
        ) from exc

    return LangfuseOpenAI


def _configure_langfuse_environment(settings: AgentSettings) -> None:
    """Expose configured Langfuse values to the native Langfuse integration.

    Args:
        settings: Runtime settings containing validated Langfuse values.
    """

    os.environ["LANGFUSE_PUBLIC_KEY"] = settings.langfuse_public_key
    os.environ["LANGFUSE_SECRET_KEY"] = settings.langfuse_secret_key
    os.environ["LANGFUSE_HOST"] = settings.langfuse_base_url
