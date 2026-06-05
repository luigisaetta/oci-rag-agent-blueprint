"""
Author: L. Saetta
Date last modified: 2026-06-05
License: MIT
Description: Unit tests for agent configuration and OpenAI client creation.
"""

# pylint: disable=too-few-public-methods,duplicate-code

from __future__ import annotations

from typing import Any

from agent.config import AgentSettings, load_settings
from agent.openai_client import create_openai_client

REQUIRED_ENV = {
    "OCI_REGION": "eu-frankfurt-1",
    "OCI_COMPARTMENT_ID": "ocid1.compartment.oc1..example",
    "OCI_PROJECT_ID": "ocid1.generativeaiproject.oc1..example",
    "OCI_MODEL_ID": "test-model",
    "OCI_VECTOR_STORE_ID": "test-vector-store",
    "OPENAI_API_KEY": "test-api-key",
}


class FakeOpenAI:
    """Fake OpenAI class used to verify client configuration.

    Attributes:
        api_key: API key passed to the client constructor.
        base_url: Base URL passed to the client constructor.
        project: Project identifier passed to the client constructor.
    """

    def __init__(self, api_key: str, base_url: str, project: str) -> None:
        """Store constructor arguments for assertions.

        Args:
            api_key: API key passed by the application.
            base_url: Base URL passed by the application.
            project: Project identifier passed by the application.
        """

        self.api_key = api_key
        self.base_url = base_url
        self.project = project


def test_load_settings_builds_base_url(monkeypatch: Any) -> None:
    """Test environment loading and OCI Enterprise AI base URL construction."""

    for env_name, env_value in REQUIRED_ENV.items():
        monkeypatch.setenv(env_name, env_value)

    settings = load_settings()

    assert settings.oci_region == "eu-frankfurt-1"
    assert settings.oci_project_id == "ocid1.generativeaiproject.oc1..example"
    assert settings.oci_model_id == "test-model"
    assert (
        settings.base_url
        == "https://inference.generativeai.eu-frankfurt-1.oci.oraclecloud.com"
        "/openai/v1"
    )


def test_create_openai_client_uses_api_key_and_base_url(monkeypatch: Any) -> None:
    """Test OpenAI-compatible client creation without external API calls."""

    monkeypatch.setattr("agent.openai_client.OpenAI", FakeOpenAI)
    settings = AgentSettings(
        oci_region="eu-frankfurt-1",
        oci_compartment_id="ocid1.compartment.oc1..example",
        oci_project_id="ocid1.generativeaiproject.oc1..example",
        oci_model_id="test-model",
        oci_vector_store_id="test-vector-store",
        openai_api_key="test-api-key",
    )

    client = create_openai_client(settings)

    assert client.api_key == "test-api-key"
    assert client.project == "ocid1.generativeaiproject.oc1..example"
    assert (
        client.base_url
        == "https://inference.generativeai.eu-frankfurt-1.oci.oraclecloud.com"
        "/openai/v1"
    )
