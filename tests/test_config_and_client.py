"""
Author: L. Saetta
Date last modified: 2026-06-05
License: MIT
Description: Unit tests for agent configuration and OpenAI client creation.
"""

# pylint: disable=too-few-public-methods,duplicate-code

from __future__ import annotations

from typing import Any

import pytest

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
        default_headers: Default headers passed to the client constructor.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str,
        project: str,
        default_headers: dict[str, str],
    ) -> None:
        """Store constructor arguments for assertions.

        Args:
            api_key: API key passed by the application.
            base_url: Base URL passed by the application.
            project: Project identifier passed by the application.
            default_headers: Default headers passed by the application.
        """

        self.api_key = api_key
        self.base_url = base_url
        self.project = project
        self.default_headers = default_headers


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
    assert settings.file_search_max_num_results == 10
    assert settings.responses_timeout_seconds == 60


def test_load_settings_reads_runtime_tuning(monkeypatch: Any) -> None:
    """Test optional runtime tuning values."""

    for env_name, env_value in REQUIRED_ENV.items():
        monkeypatch.setenv(env_name, env_value)
    monkeypatch.setenv("FILE_SEARCH_MAX_NUM_RESULTS", "7")
    monkeypatch.setenv("RESPONSES_TIMEOUT_SECONDS", "120")

    settings = load_settings()

    assert settings.file_search_max_num_results == 7
    assert settings.responses_timeout_seconds == 120


@pytest.mark.parametrize(
    ("env_name", "env_value", "expected_message"),
    [
        ("FILE_SEARCH_MAX_NUM_RESULTS", "0", "integer from 1 to 50"),
        ("FILE_SEARCH_MAX_NUM_RESULTS", "51", "integer from 1 to 50"),
        ("FILE_SEARCH_MAX_NUM_RESULTS", "many", "integer from 1 to 50"),
        ("RESPONSES_TIMEOUT_SECONDS", "0", "integer from 1 to 300"),
        ("RESPONSES_TIMEOUT_SECONDS", "301", "integer from 1 to 300"),
        ("RESPONSES_TIMEOUT_SECONDS", "slow", "integer from 1 to 300"),
    ],
)
def test_load_settings_rejects_invalid_runtime_tuning(
    monkeypatch: Any,
    env_name: str,
    env_value: str,
    expected_message: str,
) -> None:
    """Test invalid runtime tuning values fail configuration loading."""

    for required_name, required_value in REQUIRED_ENV.items():
        monkeypatch.setenv(required_name, required_value)
    monkeypatch.setenv(env_name, env_value)

    with pytest.raises(ValueError, match=expected_message):
        load_settings()


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
    assert (
        client.default_headers["extra_body"]
        == '{"compartmentId": "ocid1.compartment.oc1..example"}'
    )
