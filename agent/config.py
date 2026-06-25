"""
Author: L. Saetta
Date last modified: 2026-06-25
License: MIT
Description: Runtime configuration loading for the OCI RAG agent.
"""

from __future__ import annotations

# pylint: disable=too-many-instance-attributes

from dataclasses import dataclass
from os import environ

FILE_SEARCH_MAX_NUM_RESULTS_DEFAULT = 10
FILE_SEARCH_MAX_NUM_RESULTS_MIN = 1
FILE_SEARCH_MAX_NUM_RESULTS_MAX = 50

RESPONSES_TIMEOUT_SECONDS_DEFAULT = 60
RESPONSES_TIMEOUT_SECONDS_MIN = 1
RESPONSES_TIMEOUT_SECONDS_MAX = 300

STREAM_FINALIZATION_MODE_DEFAULT = "never"
STREAM_FINALIZATION_MODES = frozenset({"never", "auto", "always"})

LANGFUSE_ENABLED_DEFAULT = False
LANGFUSE_TRUE_VALUES = frozenset({"true", "1", "yes", "on"})
LANGFUSE_FALSE_VALUES = frozenset({"false", "0", "no", "off"})
LANGFUSE_REQUIRED_ENV_VARS = (
    "LANGFUSE_BASE_URL",
    "LANGFUSE_PUBLIC_KEY",
    "LANGFUSE_SECRET_KEY",
)

OCI_AUTH_MODE_DEFAULT = "openai_api_key"
OCI_AUTH_MODES = frozenset({"openai_api_key", "resource_principal", "config_file"})

REQUIRED_ENV_VARS = (
    "OCI_REGION",
    "OCI_COMPARTMENT_ID",
    "OCI_PROJECT_ID",
    "OCI_MODEL_ID",
    "OCI_VECTOR_STORE_ID",
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
        file_search_max_num_results: Maximum number of file search results.
        responses_timeout_seconds: Timeout for Responses API calls.
        stream_finalization_mode: Post-stream retrieve behavior.
        langfuse_enabled: Whether Langfuse observability is enabled.
        langfuse_base_url: Langfuse instance URL.
        langfuse_public_key: Langfuse public key.
        langfuse_secret_key: Langfuse secret key.
        oci_auth_mode: Authentication mode for OCI Enterprise AI Responses API.
    """

    oci_region: str
    oci_compartment_id: str
    oci_project_id: str
    oci_model_id: str
    oci_vector_store_id: str
    openai_api_key: str = ""
    file_search_max_num_results: int = FILE_SEARCH_MAX_NUM_RESULTS_DEFAULT
    responses_timeout_seconds: int = RESPONSES_TIMEOUT_SECONDS_DEFAULT
    stream_finalization_mode: str = STREAM_FINALIZATION_MODE_DEFAULT
    langfuse_enabled: bool = LANGFUSE_ENABLED_DEFAULT
    langfuse_base_url: str = ""
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    oci_auth_mode: str = OCI_AUTH_MODE_DEFAULT

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
    oci_auth_mode = load_optional_choice_env(
        "OCI_AUTH_MODE",
        OCI_AUTH_MODE_DEFAULT,
        OCI_AUTH_MODES,
    )
    if oci_auth_mode == "openai_api_key" and not environ.get("OPENAI_API_KEY"):
        missing_vars.append("OPENAI_API_KEY")
    if missing_vars:
        names = ", ".join(missing_vars)
        raise ValueError(f"Missing required environment variables: {names}")

    langfuse_enabled = _load_optional_bool(
        "LANGFUSE_ENABLED",
        LANGFUSE_ENABLED_DEFAULT,
    )
    langfuse_values = _load_langfuse_values(langfuse_enabled)

    return AgentSettings(
        oci_region=environ["OCI_REGION"],
        oci_compartment_id=environ["OCI_COMPARTMENT_ID"],
        oci_project_id=environ["OCI_PROJECT_ID"],
        oci_model_id=environ["OCI_MODEL_ID"],
        oci_vector_store_id=environ["OCI_VECTOR_STORE_ID"],
        openai_api_key=environ.get("OPENAI_API_KEY", ""),
        file_search_max_num_results=load_optional_int_env(
            "FILE_SEARCH_MAX_NUM_RESULTS",
            FILE_SEARCH_MAX_NUM_RESULTS_DEFAULT,
            FILE_SEARCH_MAX_NUM_RESULTS_MIN,
            FILE_SEARCH_MAX_NUM_RESULTS_MAX,
        ),
        responses_timeout_seconds=load_optional_int_env(
            "RESPONSES_TIMEOUT_SECONDS",
            RESPONSES_TIMEOUT_SECONDS_DEFAULT,
            RESPONSES_TIMEOUT_SECONDS_MIN,
            RESPONSES_TIMEOUT_SECONDS_MAX,
        ),
        stream_finalization_mode=load_optional_choice_env(
            "STREAM_FINALIZATION_MODE",
            STREAM_FINALIZATION_MODE_DEFAULT,
            STREAM_FINALIZATION_MODES,
        ),
        langfuse_enabled=langfuse_enabled,
        langfuse_base_url=langfuse_values["LANGFUSE_BASE_URL"],
        langfuse_public_key=langfuse_values["LANGFUSE_PUBLIC_KEY"],
        langfuse_secret_key=langfuse_values["LANGFUSE_SECRET_KEY"],
        oci_auth_mode=oci_auth_mode,
    )


def _load_optional_bool(env_name: str, default_value: bool) -> bool:
    """Load and validate an optional boolean environment variable.

    Args:
        env_name: Environment variable name.
        default_value: Value to use when the variable is not configured.

    Returns:
        bool: The configured or default boolean value.

    Raises:
        ValueError: If the configured value is not an accepted boolean token.
    """

    raw_value = environ.get(env_name)
    if raw_value is None or raw_value.strip() == "":
        return default_value

    normalized_value = raw_value.strip().lower()
    if normalized_value in LANGFUSE_TRUE_VALUES:
        return True
    if normalized_value in LANGFUSE_FALSE_VALUES:
        return False

    accepted_values = ", ".join(
        sorted(LANGFUSE_TRUE_VALUES.union(LANGFUSE_FALSE_VALUES))
    )
    raise ValueError(
        f"{env_name} must be a boolean value ({accepted_values}): {raw_value}"
    )


def _load_langfuse_values(langfuse_enabled: bool) -> dict[str, str]:
    """Load and validate optional Langfuse configuration values.

    Args:
        langfuse_enabled: Whether Langfuse observability is enabled.

    Returns:
        dict[str, str]: Langfuse values keyed by environment variable name.

    Raises:
        ValueError: If Langfuse is enabled and a required value is missing.
    """

    values = {
        env_name: environ.get(env_name, "").strip()
        for env_name in LANGFUSE_REQUIRED_ENV_VARS
    }
    if not langfuse_enabled:
        return values

    missing_vars = [env_name for env_name, value in values.items() if not value]
    if missing_vars:
        names = ", ".join(missing_vars)
        raise ValueError(
            "Missing required Langfuse environment variables when "
            f"LANGFUSE_ENABLED is true: {names}"
        )

    return values


def load_optional_int_env(
    env_name: str,
    default_value: int,
    minimum_value: int,
    maximum_value: int,
) -> int:
    """Load and validate an optional integer environment variable.

    Args:
        env_name: Environment variable name.
        default_value: Value to use when the variable is not configured.
        minimum_value: Minimum accepted integer value.
        maximum_value: Maximum accepted integer value.

    Returns:
        int: The configured or default integer value.

    Raises:
        ValueError: If the configured value is not an integer in the accepted
            range.
    """

    raw_value = environ.get(env_name)
    if raw_value is None or raw_value.strip() == "":
        return default_value

    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ValueError(
            _format_int_validation_error(
                env_name,
                raw_value,
                minimum_value,
                maximum_value,
            )
        ) from exc

    if minimum_value <= value <= maximum_value:
        return value

    raise ValueError(
        _format_int_validation_error(
            env_name,
            raw_value,
            minimum_value,
            maximum_value,
        )
    )


def _format_int_validation_error(
    env_name: str,
    raw_value: str,
    minimum_value: int,
    maximum_value: int,
) -> str:
    """Build a readable validation error for integer environment variables.

    Args:
        env_name: Environment variable name.
        raw_value: Invalid raw environment value.
        minimum_value: Minimum accepted integer value.
        maximum_value: Maximum accepted integer value.

    Returns:
        str: Validation error message.
    """

    return (
        f"{env_name} must be an integer from {minimum_value} to {maximum_value}: "
        f"{raw_value}"
    )


def load_optional_choice_env(
    env_name: str,
    default_value: str,
    accepted_values: frozenset[str],
) -> str:
    """Load and validate an optional enumerated environment variable.

    Args:
        env_name: Environment variable name.
        default_value: Value to use when the variable is not configured.
        accepted_values: Accepted normalized string values.

    Returns:
        str: The configured or default value.

    Raises:
        ValueError: If the configured value is not in the accepted set.
    """

    raw_value = environ.get(env_name)
    if raw_value is None or raw_value.strip() == "":
        return default_value

    value = raw_value.strip().lower()
    if value in accepted_values:
        return value

    accepted_values_text = ", ".join(sorted(accepted_values))
    raise ValueError(f"{env_name} must be one of {accepted_values_text}: {raw_value}")
