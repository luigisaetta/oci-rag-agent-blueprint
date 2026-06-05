"""
Author: L. Saetta
Date last modified: 2026-06-05
License: MIT
Description: OpenAI-compatible client creation for OCI Enterprise AI.
"""

from __future__ import annotations

import json
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

    return OpenAI(
        api_key=settings.openai_api_key,
        base_url=settings.base_url,
        project=settings.oci_project_id,
        default_headers={
            "extra_body": json.dumps({"compartmentId": settings.oci_compartment_id})
        },
    )
