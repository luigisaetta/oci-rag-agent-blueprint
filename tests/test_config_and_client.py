"""
Author: L. Saetta
Date last modified: 2026-06-23
License: MIT
Description: Unit tests for agent configuration and OpenAI client creation.
"""

# pylint: disable=too-few-public-methods,duplicate-code

from __future__ import annotations

import sys
import types
from typing import Any

import pytest

from agent.config import AgentSettings, load_settings
from agent.langfuse_observability import responses_observation
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


class FakeObservation:
    """Fake Langfuse observation context manager."""

    def __init__(self, updates: list[dict[str, Any]]) -> None:
        """Initialize the fake observation.

        Args:
            updates: Mutable list used to capture observation updates.
        """

        self.updates = updates

    def __enter__(self) -> "FakeObservation":
        """Enter the fake observation context.

        Returns:
            FakeObservation: Current fake observation.
        """

        return self

    def __exit__(self, *_args: Any) -> None:
        """Exit the fake observation context."""

    def update(self, **kwargs: Any) -> None:
        """Record a fake observation update.

        Args:
            **kwargs: Observation update keyword arguments.
        """

        self.updates.append(kwargs)


class FakeLangfuseClient:
    """Fake Langfuse client used to capture observation arguments."""

    def __init__(
        self,
        calls: list[dict[str, Any]],
        updates: list[dict[str, Any]],
    ) -> None:
        """Initialize the fake client.

        Args:
            calls: Mutable call list used by assertions.
            updates: Mutable update list used by assertions.
        """

        self.calls = calls
        self.updates = updates

    def start_as_current_observation(self, **kwargs: Any) -> FakeObservation:
        """Record observation arguments and return a fake context manager.

        Args:
            **kwargs: Langfuse observation keyword arguments.

        Returns:
            FakeObservation: Fake observation context manager.
        """

        self.calls.append(kwargs)
        return FakeObservation(self.updates)


class FakePropagateAttributes:
    """Fake Langfuse attribute propagation context manager."""

    def __init__(self, calls: list[dict[str, Any]], kwargs: dict[str, Any]) -> None:
        """Initialize the fake context.

        Args:
            calls: Mutable call list used by assertions.
            kwargs: Propagated attributes.
        """

        self.calls = calls
        self.kwargs = kwargs

    def __enter__(self) -> "FakePropagateAttributes":
        """Record propagated attributes.

        Returns:
            FakePropagateAttributes: Current fake context.
        """

        self.calls.append(self.kwargs)
        return self

    def __exit__(self, *_args: Any) -> None:
        """Exit the fake propagation context."""


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
    assert settings.stream_finalization_mode == "never"
    assert settings.langfuse_enabled is False


def test_load_settings_reads_runtime_tuning(monkeypatch: Any) -> None:
    """Test optional runtime tuning values."""

    for env_name, env_value in REQUIRED_ENV.items():
        monkeypatch.setenv(env_name, env_value)
    monkeypatch.setenv("FILE_SEARCH_MAX_NUM_RESULTS", "7")
    monkeypatch.setenv("RESPONSES_TIMEOUT_SECONDS", "120")
    monkeypatch.setenv("STREAM_FINALIZATION_MODE", "AUTO")

    settings = load_settings()

    assert settings.file_search_max_num_results == 7
    assert settings.responses_timeout_seconds == 120
    assert settings.stream_finalization_mode == "auto"


def test_load_settings_reads_langfuse_configuration(monkeypatch: Any) -> None:
    """Test optional Langfuse configuration values."""

    for env_name, env_value in REQUIRED_ENV.items():
        monkeypatch.setenv(env_name, env_value)
    monkeypatch.setenv("LANGFUSE_ENABLED", "yes")
    monkeypatch.setenv("LANGFUSE_BASE_URL", "https://langfuse.example.com")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "public-key")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "secret-key")

    settings = load_settings()

    assert settings.langfuse_enabled is True
    assert settings.langfuse_base_url == "https://langfuse.example.com"
    assert settings.langfuse_public_key == "public-key"
    assert settings.langfuse_secret_key == "secret-key"


@pytest.mark.parametrize(
    ("env_name", "env_value", "expected_message"),
    [
        ("FILE_SEARCH_MAX_NUM_RESULTS", "0", "integer from 1 to 50"),
        ("FILE_SEARCH_MAX_NUM_RESULTS", "51", "integer from 1 to 50"),
        ("FILE_SEARCH_MAX_NUM_RESULTS", "many", "integer from 1 to 50"),
        ("RESPONSES_TIMEOUT_SECONDS", "0", "integer from 1 to 300"),
        ("RESPONSES_TIMEOUT_SECONDS", "301", "integer from 1 to 300"),
        ("RESPONSES_TIMEOUT_SECONDS", "slow", "integer from 1 to 300"),
        ("STREAM_FINALIZATION_MODE", "sometimes", "must be one of"),
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


def test_load_settings_rejects_invalid_langfuse_enabled(monkeypatch: Any) -> None:
    """Test invalid Langfuse boolean configuration fails loading."""

    for required_name, required_value in REQUIRED_ENV.items():
        monkeypatch.setenv(required_name, required_value)
    monkeypatch.setenv("LANGFUSE_ENABLED", "maybe")

    with pytest.raises(ValueError, match="LANGFUSE_ENABLED must be a boolean value"):
        load_settings()


@pytest.mark.parametrize(
    "missing_env_name",
    ["LANGFUSE_BASE_URL", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY"],
)
def test_load_settings_requires_langfuse_values_when_enabled(
    monkeypatch: Any,
    missing_env_name: str,
) -> None:
    """Test Langfuse required values are enforced only when enabled."""

    for required_name, required_value in REQUIRED_ENV.items():
        monkeypatch.setenv(required_name, required_value)
    monkeypatch.setenv("LANGFUSE_ENABLED", "true")
    monkeypatch.setenv("LANGFUSE_BASE_URL", "https://langfuse.example.com")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "public-key")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "secret-key")
    monkeypatch.delenv(missing_env_name)

    with pytest.raises(ValueError, match=missing_env_name):
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


def test_create_openai_client_uses_langfuse_client_when_enabled(
    monkeypatch: Any,
) -> None:
    """Test Langfuse-enabled client creation uses Langfuse OpenAI wrapper."""

    fake_langfuse_openai = type("FakeLangfuseOpenAI", (FakeOpenAI,), {})
    fake_openai_module = types.ModuleType("langfuse.openai")
    fake_openai_module.OpenAI = fake_langfuse_openai
    fake_langfuse_module = types.ModuleType("langfuse")
    monkeypatch.setitem(sys.modules, "langfuse", fake_langfuse_module)
    monkeypatch.setitem(sys.modules, "langfuse.openai", fake_openai_module)
    settings = AgentSettings(
        oci_region="eu-frankfurt-1",
        oci_compartment_id="ocid1.compartment.oc1..example",
        oci_project_id="ocid1.generativeaiproject.oc1..example",
        oci_model_id="test-model",
        oci_vector_store_id="test-vector-store",
        openai_api_key="test-api-key",
        langfuse_enabled=True,
        langfuse_base_url="https://langfuse.example.com",
        langfuse_public_key="public-key",
        langfuse_secret_key="secret-key",
    )

    client = create_openai_client(settings)

    assert isinstance(client, fake_langfuse_openai)
    assert client.base_url == settings.base_url
    assert client.project == settings.oci_project_id
    assert client.default_headers["extra_body"] == (
        '{"compartmentId": "ocid1.compartment.oc1..example"}'
    )
    assert client.api_key == "test-api-key"


def test_langfuse_observation_uses_conversation_as_session(
    monkeypatch: Any,
) -> None:
    """Test Langfuse observation propagates conversation session metadata."""

    observation_calls: list[dict[str, Any]] = []
    observation_updates: list[dict[str, Any]] = []
    propagation_calls: list[dict[str, Any]] = []
    fake_langfuse_module = types.ModuleType("langfuse")
    fake_langfuse_module.get_client = lambda: FakeLangfuseClient(
        observation_calls,
        observation_updates,
    )
    fake_langfuse_module.propagate_attributes = (
        lambda **kwargs: FakePropagateAttributes(propagation_calls, kwargs)
    )
    monkeypatch.setitem(sys.modules, "langfuse", fake_langfuse_module)
    settings = AgentSettings(
        oci_region="eu-frankfurt-1",
        oci_compartment_id="ocid1.compartment.oc1..example",
        oci_project_id="ocid1.generativeaiproject.oc1..example",
        oci_model_id="test-model",
        oci_vector_store_id="test-vector-store",
        openai_api_key="test-api-key",
        langfuse_enabled=True,
        langfuse_base_url="https://langfuse.example.com",
        langfuse_public_key="public-key",
        langfuse_secret_key="secret-key",
    )

    with responses_observation(
        settings,
        name="oci-rag-agent-response",
        conversation_id="conv-123",
        stream=True,
        response_id="resp-123",
        input_data="What is OCI RAG?",
    ) as observation:
        observation.set_output("OCI RAG answer")

    assert propagation_calls[0]["session_id"] == "conv-123"
    assert propagation_calls[0]["trace_name"] == "oci-rag-agent-response"
    assert propagation_calls[0]["metadata"]["response_id"] == "resp-123"
    assert observation_calls[0]["name"] == "oci-rag-agent-response"
    assert observation_calls[0]["as_type"] == "span"
    assert observation_calls[0]["input"] == "What is OCI RAG?"
    assert observation_updates == [{"output": "OCI RAG answer"}]
