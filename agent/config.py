"""
Author: L. Saetta
Date last modified: 2026-06-05
License: MIT
Description: Runtime configuration loading for the OCI RAG agent.
"""

from __future__ import annotations

from dataclasses import dataclass
from os import environ

REQUIRED_ENV_VARS = (
    "OCI_REGION",
    "OCI_COMPARTMENT_ID",
    "OCI_PROJECT_ID",
    "OCI_MODEL_ID",
    "OCI_VECTOR_STORE_ID",
    "OPENAI_API_KEY",
)


@dataclass(frozen=True)
class AgentSettings:
    """Runtime settings required by the RAG agent.

    Attributes:
        oci_region: OCI region used to build the OCI Enterprise AI endpoint.
        oci_compartment_id: OCI compartment identifier.
        oci_project_id: OCI Enterprise AI project identifier.
        oci_model_id: Model identifier used by Responses API calls.
        oci_vector_store_id: Vector store identifier used for file search.
        openai_api_key: OpenAI-compatible API key for OCI Enterprise AI.
    """

    oci_region: str
    oci_compartment_id: str
    oci_project_id: str
    oci_model_id: str
    oci_vector_store_id: str
    openai_api_key: str

    @property
    def base_url(self) -> str:
        """Build the OpenAI-compatible OCI Enterprise AI base URL.

        Returns:
            The base URL derived from the configured OCI region.
        """

        return (
            f"https://inference.generativeai.{self.oci_region}.oci.oraclecloud.com"
            "/openai/v1"
        )


def load_settings() -> AgentSettings:
    """Load agent settings from environment variables.

    Returns:
        AgentSettings: The validated runtime settings.

    Raises:
        ValueError: If one or more required environment variables are missing.
    """

    missing_vars = [name for name in REQUIRED_ENV_VARS if not environ.get(name)]
    if missing_vars:
        names = ", ".join(missing_vars)
        raise ValueError(f"Missing required environment variables: {names}")

    return AgentSettings(
        oci_region=environ["OCI_REGION"],
        oci_compartment_id=environ["OCI_COMPARTMENT_ID"],
        oci_project_id=environ["OCI_PROJECT_ID"],
        oci_model_id=environ["OCI_MODEL_ID"],
        oci_vector_store_id=environ["OCI_VECTOR_STORE_ID"],
        openai_api_key=environ["OPENAI_API_KEY"],
    )
