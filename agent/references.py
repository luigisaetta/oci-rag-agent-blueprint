"""
Author: L. Saetta
Date last modified: 2026-06-05
License: MIT
Description: Reference and citation extraction helpers for Responses API payloads.
"""

from __future__ import annotations

import json
import re
from typing import Any, Iterator

REFERENCE_SCAN_MAX_DEPTH = 8
PAGE_PATTERN = re.compile(r"\bPage\s+(\d+)\s+of\s+\d+\b", re.IGNORECASE)


def extract_response_text(response: Any) -> str:
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


def extract_references(source: Any) -> list[dict[str, Any]]:
    """Extract normalized references from Responses API data.

    Args:
        source: Response object, stream event, dictionary, or nested data.

    Returns:
        list[dict[str, Any]]: Normalized references compatible with the response
            schema.
    """

    annotation_references = _extract_annotation_references(source)
    if annotation_references:
        return deduplicate_references(annotation_references)

    references: list[dict[str, Any]] = []
    for result in _iter_file_search_results(source):
        reference = _build_reference(result)
        if reference:
            references.append(reference)

    return deduplicate_references(references)


def deduplicate_references(
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
        reference_key = _build_reference_key(reference)
        if reference_key in seen:
            continue

        seen.add(reference_key)
        unique_references.append(reference)

    return unique_references


def get_value(source: Any, field_name: str) -> Any:
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

    text = get_value(text_block, "text")
    if not isinstance(text, str):
        return ""

    annotations = _get_supported_annotations(text_block, len(text))
    for ref_number, annotation in reversed(list(enumerate(annotations, start=1))):
        index = get_value(annotation, "index")
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

    text = get_value(text_block, "text")
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
        if get_value(output_item, "type") != "message":
            continue

        content_items = get_value(output_item, "content")
        if not isinstance(content_items, list):
            continue

        for content_item in content_items:
            if get_value(content_item, "type") == "output_text":
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

    annotations = get_value(text_block, "annotations")
    if not isinstance(annotations, list):
        return []

    supported_annotations = []
    for annotation in annotations:
        annotation_type = get_value(annotation, "type")
        annotation_index = get_value(annotation, "index")
        is_supported_type = annotation_type in (None, "file_citation")
        is_valid_index = (
            isinstance(annotation_index, int) and 0 <= annotation_index <= text_length
        )
        if is_supported_type and is_valid_index:
            supported_annotations.append(annotation)

    return sorted(
        supported_annotations,
        key=lambda annotation: get_value(annotation, "index"),
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

    event_response = get_value(source, "response")
    if event_response is not None:
        yield from _iter_file_search_results(event_response)

    for output_item in _iter_output_items(source):
        if get_value(output_item, "type") != "file_search_call":
            continue

        results = get_value(output_item, "results")
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

    output = get_value(source, "output")
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
    if page is None:
        page = _extract_page_from_text(result)
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
        value = get_value(result, result_field_name)
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


def _extract_page_from_text(result: Any) -> int | None:
    """Extract a page number embedded in retrieved text.

    Args:
        result: Raw file search result object or dictionary.

    Returns:
        int | None: Page number when a supported text pattern is found.
    """

    text = get_value(result, "text")
    if not isinstance(text, str):
        text = get_value(result, "content")

    if not isinstance(text, str):
        return None

    match = PAGE_PATTERN.search(text)
    if not match:
        return None

    return int(match.group(1))


def _build_reference_key(reference: dict[str, Any]) -> str:
    """Build a stable deduplication key for one normalized reference.

    Args:
        reference: Normalized reference.

    Returns:
        str: Stable deduplication key.
    """

    metadata = reference.get("metadata")
    file_id = metadata.get("file_id") if isinstance(metadata, dict) else None
    file_name = reference.get("file_name")
    page = reference.get("page")

    return json.dumps(
        {
            "file": file_id or file_name,
            "page": page,
        },
        sort_keys=True,
    )


def _get_first_string(source: Any, field_names: tuple[str, ...]) -> str | None:
    """Return the first string value found in a source object.

    Args:
        source: Object or dictionary to inspect.
        field_names: Candidate field names.

    Returns:
        str | None: First string value, when available.
    """

    for field_name in field_names:
        value = get_value(source, field_name)
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

    value = get_value(source, field_name)
    if isinstance(value, dict):
        return value

    return {}


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
