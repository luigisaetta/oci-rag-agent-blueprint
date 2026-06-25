"""
Author: L. Saetta
Date last modified: 2026-06-25
License: MIT
Description: OpenAI-compatible client creation for OCI Enterprise AI.
"""

from __future__ import annotations

# pylint: disable=duplicate-code

import json
import os
from typing import Any

import httpx
from openai import OpenAI

from agent.config import AgentSettings

OPENAI_COMPATIBLE_IAM_API_KEY_PLACEHOLDER = "not-used"


def create_openai_client(settings: AgentSettings) -> Any:
    """Create an OpenAI-compatible client for OCI Enterprise AI.

    Args:
        settings: Runtime settings used to configure authentication and base URL.

    Returns:
        Any: Configured OpenAI client instance.
    """

    client_class = _resolve_client_class(settings)
    client_kwargs = _build_openai_client_kwargs(settings)
    return client_class(**client_kwargs)


def _build_openai_client_kwargs(settings: AgentSettings) -> dict[str, Any]:
    """Build constructor arguments for the OpenAI-compatible client.

    Args:
        settings: Runtime settings used to configure authentication and base URL.

    Returns:
        dict[str, Any]: Keyword arguments for the OpenAI client constructor.
    """

    client_kwargs: dict[str, Any] = {
        "api_key": _client_api_key(settings),
        "base_url": settings.base_url,
        "project": settings.oci_project_id,
        "default_headers": {
            "extra_body": json.dumps({"compartmentId": settings.oci_compartment_id})
        },
    }
    if settings.oci_auth_mode != "openai_api_key":
        client_kwargs["http_client"] = _build_oci_signed_http_client(settings)
    return client_kwargs


def _client_api_key(settings: AgentSettings) -> str:
    """Return the API key value expected by the OpenAI SDK.

    Args:
        settings: Runtime settings containing the selected OCI auth mode.

    Returns:
        str: Real API key for OpenAI-compatible API key mode, otherwise a
        placeholder required by the OpenAI SDK constructor.
    """

    if settings.oci_auth_mode == "openai_api_key":
        return settings.openai_api_key
    return OPENAI_COMPATIBLE_IAM_API_KEY_PLACEHOLDER


def _build_oci_signed_http_client(settings: AgentSettings) -> httpx.Client:
    """Build an HTTPX client that signs OCI Generative AI requests.

    Args:
        settings: Runtime settings containing the selected OCI auth mode.

    Returns:
        httpx.Client: HTTP client configured with OCI request signing auth.

    Raises:
        ValueError: If the OCI GenAI auth dependency is unavailable or the mode
            is not supported.
    """

    try:
        from oci_genai_auth import (  # pylint: disable=import-outside-toplevel
            OciResourcePrincipalAuth,
            OciUserPrincipalAuth,
        )
    except ImportError as exc:
        raise ValueError(
            "OCI_AUTH_MODE requires the oci-genai-auth package when set to "
            "resource_principal or config_file."
        ) from exc

    if settings.oci_auth_mode == "resource_principal":
        return httpx.Client(auth=OciResourcePrincipalAuth())
    if settings.oci_auth_mode == "config_file":
        return httpx.Client(
            auth=OciUserPrincipalAuth(
                config_file=os.environ.get("OCI_CONFIG_FILE", "~/.oci/config"),
                profile_name=os.environ.get("OCI_PROFILE", "DEFAULT"),
            )
        )

    raise ValueError(f"Unsupported OCI_AUTH_MODE: {settings.oci_auth_mode}")


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
