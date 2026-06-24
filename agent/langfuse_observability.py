"""
Author: L. Saetta
Date last modified: 2026-06-24
License: MIT
Description: Optional Langfuse tracing helpers for Responses API calls.
"""

from __future__ import annotations

# pylint: disable=duplicate-code

from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from typing import Any, Callable, Iterator, cast

from agent.config import AgentSettings


@dataclass
class ObservationRecorder:
    """Small wrapper used to update optional Langfuse observation content.

    Attributes:
        observation: Active Langfuse observation object, or `None` when
            Langfuse is disabled.
    """

    observation: Any | None = None

    def set_output(self, output: Any) -> None:
        """Set the active Langfuse observation output when available.

        Args:
            output: Output payload to attach to the current observation.
        """

        if self.observation is None:
            return

        update = cast(
            Callable[..., None] | None, getattr(self.observation, "update", None)
        )
        if update is not None:
            update(output=output)


@contextmanager
def responses_observation(  # pylint: disable=too-many-arguments
    settings: AgentSettings,
    *,
    name: str,
    conversation_id: str,
    stream: bool,
    response_id: str | None = None,
    input_data: Any | None = None,
) -> Iterator[ObservationRecorder]:
    """Create an optional Langfuse observation for a Responses API operation.

    Args:
        settings: Runtime settings containing Langfuse configuration.
        name: Langfuse observation name.
        conversation_id: Active Responses API conversation identifier.
        stream: Whether the operation is a streaming Responses API call.
        response_id: Responses API response identifier, when already known.
        input_data: Request input to attach to the Langfuse observation.

    Yields:
        ObservationRecorder: Recorder that updates the active observation when
        Langfuse is enabled; otherwise it safely ignores updates.
    """

    if not settings.langfuse_enabled:
        with nullcontext():
            yield ObservationRecorder()
        return

    with _langfuse_context(
        settings,
        name=name,
        conversation_id=conversation_id,
        stream=stream,
        response_id=response_id,
        input_data=input_data,
    ) as recorder:
        yield recorder


@contextmanager
def _langfuse_context(  # pylint: disable=too-many-arguments
    settings: AgentSettings,
    *,
    name: str,
    conversation_id: str,
    stream: bool,
    response_id: str | None,
    input_data: Any | None,
) -> Iterator[ObservationRecorder]:
    """Create the Langfuse context with propagated session attributes.

    Args:
        settings: Runtime settings containing Langfuse configuration.
        name: Langfuse observation name.
        conversation_id: Active Responses API conversation identifier.
        stream: Whether the operation is a streaming Responses API call.
        response_id: Responses API response identifier, when already known.
        input_data: Request input to attach to the Langfuse observation.

    Yields:
        ObservationRecorder: Recorder for updating observation output.

    Raises:
        ValueError: If Langfuse is enabled but the package is unavailable.
    """

    try:
        # pylint: disable=import-outside-toplevel
        from langfuse import (
            get_client,
            propagate_attributes,
        )
    except ImportError as exc:
        raise ValueError(
            "LANGFUSE_ENABLED is true but the langfuse package is not installed."
        ) from exc

    metadata = _observation_metadata(
        settings,
        conversation_id=conversation_id,
        stream=stream,
        response_id=response_id,
    )

    with propagate_attributes(
        session_id=conversation_id,
        trace_name=name,
        metadata=metadata,
        tags=["oci-rag-agent"],
    ):
        with get_client().start_as_current_observation(
            name=name,
            as_type="span",
            metadata=metadata,
            input=input_data,
        ) as observation:
            yield ObservationRecorder(observation)


def _observation_metadata(
    settings: AgentSettings,
    *,
    conversation_id: str,
    stream: bool,
    response_id: str | None,
) -> dict[str, Any]:
    """Build safe Langfuse metadata for a Responses API operation.

    Args:
        settings: Runtime settings containing operational values.
        conversation_id: Active Responses API conversation identifier.
        stream: Whether the operation is a streaming Responses API call.
        response_id: Responses API response identifier, when known.

    Returns:
        dict[str, Any]: Metadata without prompts, responses, or secrets.
    """

    metadata: dict[str, Any] = {
        "conversation_id": conversation_id,
        "stream": stream,
        "model": settings.oci_model_id,
        "file_search_max_num_results": settings.file_search_max_num_results,
        "stream_finalization_mode": settings.stream_finalization_mode,
    }
    if response_id:
        metadata["response_id"] = response_id
    return metadata
