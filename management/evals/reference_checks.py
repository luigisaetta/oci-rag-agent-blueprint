"""
Author: L. Saetta
Date last modified: 2026-06-29
License: MIT
Description: Reference matching helpers for RAG evaluation results.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import unquote

PAGE_FIELDS = (
    "page",
    "page_number",
    "pageNumber",
    "source_page",
    "sourcePage",
)

PDF_FIELDS = (
    "file_name",
    "filename",
    "source_pdf_name",
    "title",
    "name",
    "path",
    "url",
    "source",
)


@dataclass(frozen=True)
class ReferenceCheck:
    """Deterministic source reference check result."""

    expected_pdf_found: bool
    expected_page_found: bool | None
    reference_match_status: str

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dictionary."""

        return asdict(self)


def check_references(
    references: list[dict[str, Any]],
    expected_pdf_name: str,
    expected_page_number: int,
    agent_error: str | None = None,
) -> ReferenceCheck:
    """Check whether expected PDF and page are present in references.

    Args:
        references: Agent references.
        expected_pdf_name: Expected source PDF file name.
        expected_page_number: Expected one-based page number.
        agent_error: Agent error, when request failed.

    Returns:
        ReferenceCheck: Reference match result.
    """

    if agent_error:
        return ReferenceCheck(False, False, "agent_error")
    if not references:
        return ReferenceCheck(False, False, "no_references")

    matching_pdf_references = [
        reference
        for reference in references
        if _reference_matches_pdf(reference, expected_pdf_name)
    ]
    if not matching_pdf_references:
        return ReferenceCheck(False, False, "pdf_missing")

    page_values = [
        _extract_page_number(reference) for reference in matching_pdf_references
    ]
    known_page_values = [page for page in page_values if page is not None]
    if not known_page_values:
        return ReferenceCheck(True, None, "pdf_found_page_unknown")
    if expected_page_number in known_page_values:
        return ReferenceCheck(True, True, "pdf_and_page_found")
    return ReferenceCheck(True, False, "pdf_found_page_missing")


def _reference_matches_pdf(reference: dict[str, Any], expected_pdf_name: str) -> bool:
    """Return whether one reference matches the expected PDF.

    Args:
        reference: Reference dictionary.
        expected_pdf_name: Expected PDF file name.

    Returns:
        bool: True when the reference points to the expected PDF.
    """

    expected = _normalize_pdf_name(expected_pdf_name)
    for value in _iter_reference_values(reference):
        normalized_value = _normalize_pdf_name(str(value))
        if normalized_value == expected or normalized_value.endswith(f"/{expected}"):
            return True
    return False


def _iter_reference_values(reference: dict[str, Any]) -> list[Any]:
    """Collect candidate PDF reference values.

    Args:
        reference: Reference dictionary.

    Returns:
        list[Any]: Candidate values.
    """

    values: list[Any] = []
    for field_name in PDF_FIELDS:
        value = reference.get(field_name)
        if value:
            values.append(value)
    return values


def _normalize_pdf_name(value: str) -> str:
    """Normalize a PDF name or path for comparison.

    Args:
        value: Raw value.

    Returns:
        str: Normalized lowercase path-like value.
    """

    decoded_value = unquote(value).replace("\\", "/").strip().lower()
    if "?" in decoded_value:
        decoded_value = decoded_value.split("?", maxsplit=1)[0]
    if decoded_value.startswith("http://") or decoded_value.startswith("https://"):
        return PurePosixPath(decoded_value).name
    return decoded_value


def _extract_page_number(reference: dict[str, Any]) -> int | None:
    """Extract page number from a reference dictionary.

    Args:
        reference: Reference dictionary.

    Returns:
        int | None: Page number when present.
    """

    for field_name in PAGE_FIELDS:
        value = reference.get(field_name)
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.strip().isdigit():
            return int(value.strip())
    return None
