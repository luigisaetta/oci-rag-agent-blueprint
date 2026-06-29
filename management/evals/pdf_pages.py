"""
Author: L. Saetta
Date last modified: 2026-06-29
License: MIT
Description: PDF download and page text extraction helpers for evaluations.
"""

from __future__ import annotations

from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from management.evals.page_selection import PdfPageText


def extract_pdf_pages(path: Path) -> list[PdfPageText]:
    """Extract page text from a local PDF file.

    Args:
        path: Local PDF path.

    Returns:
        list[PdfPageText]: Extracted pages with one-based page numbers.

    Raises:
        RuntimeError: If the PDF dependency is unavailable.
    """

    try:
        from pypdf import PdfReader  # pylint: disable=import-outside-toplevel
    except ImportError as exc:
        raise RuntimeError("The pypdf package is required for PDF extraction.") from exc

    reader = PdfReader(str(path))
    pages: list[PdfPageText] = []
    for index, page in enumerate(reader.pages, start=1):
        pages.append(PdfPageText(page_number=index, text=page.extract_text() or ""))
    return pages


def download_pdf_to_tempfile(
    object_storage_client: Any,
    namespace: str,
    bucket: str,
    object_name: str,
) -> Path:
    """Download an Object Storage PDF object to a temporary file.

    Args:
        object_storage_client: OCI Object Storage client.
        namespace: Object Storage namespace.
        bucket: Object Storage bucket.
        object_name: Object Storage object name.

    Returns:
        Path: Temporary local PDF path. The caller is responsible for deletion.
    """

    response = object_storage_client.get_object(namespace, bucket, object_name)
    with NamedTemporaryFile("wb", suffix=".pdf", delete=False) as temp_file:
        for chunk in response.data.raw.stream(1024 * 1024, decode_content=False):
            temp_file.write(chunk)
        return Path(temp_file.name)
