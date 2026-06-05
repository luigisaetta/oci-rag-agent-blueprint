"""
Author: L. Saetta
Date last modified: 2026-06-05
License: MIT
Description: Core request processing logic for the OCI RAG agent.
"""

from __future__ import annotations

import json
import logging
from json import JSONDecodeError
from typing import Any, Callable, Iterator

from agent.config import AgentSettings

LOGGER = logging.getLogger(__name__)
RESPONSES_TIMEOUT_SECONDS = 60
OUTPUT_TEXT_DELTA_EVENT_TYPE = "response.output_text.delta"
REFERENCE_SCAN_MAX_DEPTH = 8

AGENT_INSTRUCTIONS = """
You are an OCI Enterprise AI RAG agent.
Answer the user directly and concisely using the available knowledge base.
Do not expose internal reasoning, planning, tool-selection narration, or analysis.
Do not mention web search or external tools.
If the knowledge base does not contain enough information, say so plainly.
""".strip()


def process_agent_request(
    payload: dict[str, Any],
    settings: AgentSettings,
    client_factory: Callable[[AgentSettings], Any],
) -> dict[str, Any]:
    """Process one validated agent request.

    Args:
        payload: Validated request payload.
        settings: Runtime settings for model, vector store, and API access.
        client_factory: Callable that creates an OpenAI-compatible client.

    Returns:
        dict[str, Any]: Agent response payload.

    Raises:
        Exception: Propagates Responses API errors to the FastAPI layer, which
            converts them into deterministic JSON error responses.
    """

    client = client_factory(settings)
    conversation_id = _resolve_conversation_id(payload, client)

    LOGGER.info("Processing request for conversation_id=%s", conversation_id)

    response = client.responses.create(
        **_build_response_request(payload, settings, conversation_id),
        timeout=RESPONSES_TIMEOUT_SECONDS,
    )

    response_id = getattr(response, "id", None)
    if response_id:
        LOGGER.info("Responses API returned response_id=%s", response_id)

    return {
        "conversation_id": conversation_id,
        "response_id": response_id,
        "agent_response": _extract_response_text(response),
        "references": _extract_references(response),
        "error": None,
    }


def stream_agent_request(
    payload: dict[str, Any],
    settings: AgentSettings,
    client_factory: Callable[[AgentSettings], Any],
) -> Iterator[str]:
    """Stream one validated agent request using Server-Sent Events.

    Args:
        payload: Validated request payload.
        settings: Runtime settings for model, vector store, and API access.
        client_factory: Callable that creates an OpenAI-compatible client.

    Yields:
        str: Server-Sent Event frames.
    """

    conversation_id = ""
    token_events_emitted = 0
    references: list[dict[str, Any]] = []

    try:
        client = client_factory(settings)
        conversation_id = _resolve_conversation_id(payload, client)
        LOGGER.info("Streaming request for conversation_id=%s", conversation_id)
        yield _format_sse_event("metadata", {"conversation_id": conversation_id})

        for token in _stream_response_tokens(
            payload, settings, client, conversation_id, references
        ):
            token_events_emitted += 1
            yield _format_sse_event("token", {"text": token})

        yield _format_sse_event(
            "references",
            {"references": _deduplicate_references(references)},
        )
        yield _format_sse_event("done", {"conversation_id": conversation_id})
    except JSONDecodeError as exc:
        if token_events_emitted:
            LOGGER.warning(
                "Responses API stream parser failure after %s token events: %s",
                token_events_emitted,
                exc,
            )
            yield _format_sse_event("done", {"conversation_id": conversation_id})
        else:
            LOGGER.exception("Responses API streaming parser failure")
            yield _format_sse_event("error", {"error": f"Responses API failure: {exc}"})
    except Exception as exc:  # pylint: disable=broad-exception-caught
        LOGGER.exception("Responses API streaming failure")
        yield _format_sse_event("error", {"error": f"Responses API failure: {exc}"})


def _stream_response_tokens(
    payload: dict[str, Any],
    settings: AgentSettings,
    client: Any,
    conversation_id: str,
    references: list[dict[str, Any]],
) -> Iterator[str]:
    """Yield final-answer tokens from a Responses API stream.

    Args:
        payload: Validated request payload.
        settings: Runtime settings for model and vector store access.
        client: OpenAI-compatible client.
        conversation_id: Active conversation identifier.
        references: Mutable list receiving references found in stream events.

    Yields:
        str: Final-answer text tokens.
    """

    stream = client.responses.create(
        **_build_response_request(payload, settings, conversation_id),
        timeout=RESPONSES_TIMEOUT_SECONDS,
        stream=True,
    )

    for event in stream:
        references.extend(_extract_references(event))
        token = _extract_stream_token(event)
        if token:
            yield token


def _resolve_conversation_id(payload: dict[str, Any], client: Any) -> str:
    """Resolve the conversation identifier for the current request.

    Args:
        payload: Validated request payload.
        client: OpenAI-compatible client.

    Returns:
        str: Conversation identifier to pass to Responses API calls.
    """

    if payload["new_conversation"]:
        conversation = client.conversations.create()
        conversation_id = conversation.id
        LOGGER.info("Created conversation_id=%s", conversation_id)
        return conversation_id

    return payload["conversation_id"]


def _build_response_request(
    payload: dict[str, Any],
    settings: AgentSettings,
    conversation_id: str,
) -> dict[str, Any]:
    """Build common Responses API request parameters.

    Args:
        payload: Validated request payload.
        settings: Runtime settings for model and vector store access.
        conversation_id: Active conversation identifier.

    Returns:
        dict[str, Any]: Responses API request parameters.
    """

    return {
        "model": settings.oci_model_id,
        "instructions": AGENT_INSTRUCTIONS,
        "input": payload["user_request"],
        "conversation": conversation_id,
        "tools": [_build_file_search_tool(settings)],
        "tool_choice": "required",
        "include": ["file_search_call.results"],
    }


def _build_file_search_tool(settings: AgentSettings) -> dict[str, Any]:
    """Build the Responses API file search tool configuration.

    Args:
        settings: Runtime settings containing the configured vector store.

    Returns:
        dict[str, Any]: File search tool configuration.
    """

    return {
        "type": "file_search",
        "vector_store_ids": [settings.oci_vector_store_id],
        "max_num_results": 10,
    }


def _extract_response_text(response: Any) -> str:
    """Extract response text from a Responses API response object.

    Args:
        response: Responses API response object.

    Returns:
        str: Extracted output text, or an empty string when unavailable.
    """

    output_text = _extract_output_text_with_inline_citations(response)
    if output_text:
        return output_text

    output_text = getattr(response, "output_text", None)
    if isinstance(output_text, str):
        return output_text

    return ""


def _extract_references(source: Any) -> list[dict[str, Any]]:
    """Extract normalized references from Responses API data.

    Args:
        source: Response object, stream event, dictionary, or nested data.

    Returns:
        list[dict[str, Any]]: Normalized references compatible with the response
            schema.
    """

    references: list[dict[str, Any]] = []
    references.extend(_extract_annotation_references(source))

    for result in _iter_file_search_results(source):
        reference = _build_reference(result)
        if reference:
            references.append(reference)

    return _deduplicate_references(references)


def _extract_output_text_with_inline_citations(source: Any) -> str:
    """Extract output text and insert citation markers when annotations exist.

    Args:
        source: Response object or dictionary.

    Returns:
        str: Output text with inline citation markers, when available.
    """

    text_block = _get_last_output_text_block(source)
    if text_block is None:
        return ""

    text = _get_value(text_block, "text")
    if not isinstance(text, str):
        return ""

    annotations = _get_supported_annotations(text_block, len(text))
    for ref_number, annotation in reversed(list(enumerate(annotations, start=1))):
        index = _get_value(annotation, "index")
        marker = f"[{ref_number}] "
        text = text[:index] + marker + text[index:]

    return text


def _extract_annotation_references(source: Any) -> list[dict[str, Any]]:
    """Extract references from output text citation annotations.

    Args:
        source: Response object or dictionary.

    Returns:
        list[dict[str, Any]]: Normalized citation references.
    """

    text_block = _get_last_output_text_block(source)
    if text_block is None:
        return []

    text = _get_value(text_block, "text")
    text_length = len(text) if isinstance(text, str) else 0
    annotations = _get_supported_annotations(text_block, text_length)

    references: list[dict[str, Any]] = []
    for annotation in annotations:
        reference = _build_reference(annotation, allow_unknown_file=True)
        if reference:
            references.append(reference)

    return references


def _get_last_output_text_block(source: Any) -> Any | None:
    """Return the last Responses API output text block.

    Args:
        source: Response object or dictionary.

    Returns:
        Any | None: Last output text block, when present.
    """

    text_block = None
    for output_item in _iter_output_items(source):
        if _get_value(output_item, "type") != "message":
            continue

        content_items = _get_value(output_item, "content")
        if not isinstance(content_items, list):
            continue

        for content_item in content_items:
            if _get_value(content_item, "type") == "output_text":
                text_block = content_item

    return text_block


def _get_supported_annotations(text_block: Any, text_length: int) -> list[Any]:
    """Return supported file citation annotations ordered by insertion index.

    Args:
        text_block: Responses API output text block.
        text_length: Length of the text that owns the annotations.

    Returns:
        list[Any]: Supported annotations sorted by index.
    """

    annotations = _get_value(text_block, "annotations")
    if not isinstance(annotations, list):
        return []

    supported_annotations = []
    for annotation in annotations:
        annotation_type = _get_value(annotation, "type")
        annotation_index = _get_value(annotation, "index")
        is_supported_type = annotation_type in (None, "file_citation")
        is_valid_index = (
            isinstance(annotation_index, int) and 0 <= annotation_index <= text_length
        )
        if is_supported_type and is_valid_index:
            supported_annotations.append(annotation)

    return sorted(
        supported_annotations,
        key=lambda annotation: _get_value(annotation, "index"),
    )


def _iter_file_search_results(source: Any) -> Iterator[Any]:
    """Yield file search results from a response or stream event.

    Args:
        source: Response object, stream event, dictionary, or nested data.

    Yields:
        Any: Raw file search result objects.
    """

    if source is None:
        return

    if isinstance(source, list):
        for item in source:
            yield from _iter_file_search_results(item)
        return

    event_response = _get_value(source, "response")
    if event_response is not None:
        yield from _iter_file_search_results(event_response)

    for output_item in _iter_output_items(source):
        if _get_value(output_item, "type") != "file_search_call":
            continue

        results = _get_value(output_item, "results")
        if isinstance(results, list):
            yield from results

    yield from _iter_nested_file_search_results(source)


def _iter_nested_file_search_results(
    source: Any,
    depth: int = 0,
) -> Iterator[Any]:
    """Yield file search results from nested response structures.

    Args:
        source: Object, dictionary, list, or scalar to inspect.
        depth: Current recursion depth.

    Yields:
        Any: Raw file search result objects.
    """

    if source is None or depth > REFERENCE_SCAN_MAX_DEPTH:
        return

    if isinstance(source, list):
        for item in source:
            yield from _iter_nested_file_search_results(item, depth + 1)
        return

    source_mapping = _as_mapping(source)
    if not source_mapping:
        return

    results = source_mapping.get("results")
    if _looks_like_file_search_results(results):
        yield from results

    for value in source_mapping.values():
        yield from _iter_nested_file_search_results(value, depth + 1)


def _looks_like_file_search_results(value: Any) -> bool:
    """Return whether a value looks like file search results.

    Args:
        value: Value to inspect.

    Returns:
        bool: True when the value is a list containing file search results.
    """

    return isinstance(value, list) and any(
        _looks_like_file_search_result(item) for item in value
    )


def _looks_like_file_search_result(value: Any) -> bool:
    """Return whether a value looks like one file search result.

    Args:
        value: Value to inspect.

    Returns:
        bool: True when the value contains a recognizable source file name.
    """

    return (
        _get_first_string(
            value,
            ("filename", "file_name", "fileName", "name"),
        )
        is not None
    )


def _iter_output_items(source: Any) -> Iterator[Any]:
    """Yield output items from a Responses API object.

    Args:
        source: Response object or dictionary.

    Yields:
        Any: Output items.
    """

    output = _get_value(source, "output")
    if isinstance(output, list):
        yield from output


def _build_reference(
    result: Any,
    allow_unknown_file: bool = False,
) -> dict[str, Any] | None:
    """Build one normalized reference from a file search result.

    Args:
        result: Raw file search result object or dictionary.
        allow_unknown_file: Whether to keep a reference without a source file
            name using a deterministic placeholder.

    Returns:
        dict[str, Any] | None: Normalized reference, or None when the result
            does not contain a usable source file name.
    """

    file_name = _get_first_string(
        result,
        ("filename", "file_name", "fileName", "name"),
    )
    if not file_name:
        if not allow_unknown_file:
            return None

        file_name = "unknown_file"

    attributes = _get_mapping(result, "additional_properties")
    if not attributes:
        attributes = _get_mapping(result, "attributes")
    page = _extract_page(attributes)
    metadata = _build_reference_metadata(result, attributes)

    return {
        "file_name": file_name,
        "page": page,
        "metadata": metadata,
    }


def _build_reference_metadata(
    result: Any,
    attributes: dict[str, Any],
) -> dict[str, Any]:
    """Build metadata for a normalized reference.

    Args:
        result: Raw file search result object or dictionary.
        attributes: File search result attributes.

    Returns:
        dict[str, Any]: JSON-serializable metadata.
    """

    metadata: dict[str, Any] = {}
    if attributes:
        metadata["attributes"] = attributes

    for metadata_name, result_field_name in (
        ("file_id", "file_id"),
        ("file_id", "fileId"),
        ("score", "score"),
        ("text", "text"),
        ("text", "content"),
    ):
        value = _get_value(result, result_field_name)
        if value is not None:
            metadata[metadata_name] = value

    return metadata


def _extract_page(attributes: dict[str, Any]) -> int | None:
    """Extract a page number from file search attributes.

    Args:
        attributes: File search result attributes.

    Returns:
        int | None: Page number when available.
    """

    for key in ("page", "page_number"):
        value = attributes.get(key)
        if isinstance(value, int) and value > 0:
            return value
        if isinstance(value, str) and value.isdigit() and int(value) > 0:
            return int(value)

    page_numbers = attributes.get("page_numbers")
    if not isinstance(page_numbers, list):
        page_numbers = [page_numbers]

    for page_number in page_numbers:
        if isinstance(page_number, int) and page_number > 0:
            return page_number
        if (
            isinstance(page_number, str)
            and page_number.isdigit()
            and int(page_number) > 0
        ):
            return int(page_number)

    return None


def _deduplicate_references(
    references: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Remove duplicate references while preserving order.

    Args:
        references: References to deduplicate.

    Returns:
        list[dict[str, Any]]: Deduplicated references.
    """

    seen: set[str] = set()
    unique_references = []
    for reference in references:
        reference_key = json.dumps(reference, sort_keys=True)
        if reference_key in seen:
            continue

        seen.add(reference_key)
        unique_references.append(reference)

    return unique_references


def _get_first_string(source: Any, field_names: tuple[str, ...]) -> str | None:
    """Return the first string value found in a source object.

    Args:
        source: Object or dictionary to inspect.
        field_names: Candidate field names.

    Returns:
        str | None: First string value, when available.
    """

    for field_name in field_names:
        value = _get_value(source, field_name)
        if isinstance(value, str) and value:
            return value

    return None


def _get_mapping(source: Any, field_name: str) -> dict[str, Any]:
    """Return a dictionary field from an object or dictionary.

    Args:
        source: Object or dictionary to inspect.
        field_name: Field name to read.

    Returns:
        dict[str, Any]: Field value when it is a dictionary, otherwise empty.
    """

    value = _get_value(source, field_name)
    if isinstance(value, dict):
        return value

    return {}


def _get_value(source: Any, field_name: str) -> Any:
    """Read one value from a dictionary or object.

    Args:
        source: Object or dictionary to inspect.
        field_name: Field name to read.

    Returns:
        Any: Field value, or None when missing.
    """

    if isinstance(source, dict):
        return source.get(field_name)

    return getattr(source, field_name, None)


def _as_mapping(source: Any) -> dict[str, Any]:
    """Convert dictionary-like objects to plain dictionaries.

    Args:
        source: Object or dictionary to inspect.

    Returns:
        dict[str, Any]: Plain dictionary representation, when available.
    """

    if isinstance(source, dict):
        return source

    model_dump = getattr(source, "model_dump", None)
    if callable(model_dump):
        dumped_value = model_dump()
        if isinstance(dumped_value, dict):
            return dumped_value

    dict_method = getattr(source, "dict", None)
    if callable(dict_method):
        dumped_value = dict_method()
        if isinstance(dumped_value, dict):
            return dumped_value

    return {}


def _extract_stream_token(event: Any) -> str:
    """Extract a final-answer text delta from a Responses API stream event.

    Args:
        event: Stream event object or dictionary.

    Returns:
        str: Final-answer text delta, or an empty string for non-output events.
    """

    if isinstance(event, dict):
        event_type = event.get("type")
        delta = event.get("delta")
    else:
        event_type = getattr(event, "type", None)
        delta = getattr(event, "delta", None)

    if event_type != OUTPUT_TEXT_DELTA_EVENT_TYPE:
        return ""

    if isinstance(delta, str):
        return delta

    return ""


def _format_sse_event(event_name: str, payload: dict[str, Any]) -> str:
    """Format one Server-Sent Event frame.

    Args:
        event_name: SSE event name.
        payload: JSON-serializable event payload.

    Returns:
        str: Formatted SSE frame.
    """

    return f"event: {event_name}\ndata: {json.dumps(payload)}\n\n"
