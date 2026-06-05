"""
Author: L. Saetta
Date last modified: 2026-06-05
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
        file_search_max_num_results: Maximum number of file search results.
        responses_timeout_seconds: Timeout for Responses API calls.
    """

    oci_region: str
    oci_compartment_id: str
    oci_project_id: str
    oci_model_id: str
    oci_vector_store_id: str
    openai_api_key: str
    file_search_max_num_results: int = FILE_SEARCH_MAX_NUM_RESULTS_DEFAULT
    responses_timeout_seconds: int = RESPONSES_TIMEOUT_SECONDS_DEFAULT

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
        file_search_max_num_results=_load_optional_int(
            "FILE_SEARCH_MAX_NUM_RESULTS",
            FILE_SEARCH_MAX_NUM_RESULTS_DEFAULT,
            FILE_SEARCH_MAX_NUM_RESULTS_MIN,
            FILE_SEARCH_MAX_NUM_RESULTS_MAX,
        ),
        responses_timeout_seconds=_load_optional_int(
            "RESPONSES_TIMEOUT_SECONDS",
            RESPONSES_TIMEOUT_SECONDS_DEFAULT,
            RESPONSES_TIMEOUT_SECONDS_MIN,
            RESPONSES_TIMEOUT_SECONDS_MAX,
        ),
    )


def _load_optional_int(
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
