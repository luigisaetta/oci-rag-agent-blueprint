"""
Author: L. Saetta
Date last modified: 2026-06-29
License: MIT
Description: JSONL golden dataset record helpers and atomic file operations.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Iterable


@dataclass(frozen=True)
class GoldenRecord:
    """One golden dataset example grounded in a source PDF page.

    Attributes:
        id: Deterministic record identifier.
        source_pdf_name: PDF file name derived from the object name.
        page_number: One-based page number.
        question: Generated question grounded in the page.
        expected_answer: Generated expected answer grounded in the page.
    """

    id: str
    source_pdf_name: str
    page_number: int
    question: str
    expected_answer: str

    @property
    def source_key(self) -> tuple[str, int]:
        """Return the logical source key used for overwrite matching.

        Returns:
            tuple[str, int]: Source PDF name and page.
        """

        return (self.source_pdf_name, self.page_number)


def build_record_id(source_pdf_name: str, page_number: int) -> str:
    """Build a deterministic golden dataset record identifier.

    Args:
        source_pdf_name: PDF file name.
        page_number: One-based page number.

    Returns:
        str: Stable record identifier.
    """

    raw_key = "\n".join([source_pdf_name, str(page_number)])
    return f"golden_{hashlib.sha256(raw_key.encode('utf-8')).hexdigest()[:24]}"


def load_jsonl_records(path: Path) -> list[GoldenRecord]:
    """Load golden records from a JSONL file.

    Args:
        path: JSONL file path.

    Returns:
        list[GoldenRecord]: Loaded records.

    Raises:
        ValueError: If a line is not valid JSON or lacks required fields.
    """

    if not path.exists():
        return []

    records: list[GoldenRecord] = []
    with path.open("r", encoding="utf-8") as file_handle:
        for line_number, line in enumerate(file_handle, start=1):
            stripped_line = line.strip()
            if not stripped_line:
                continue
            try:
                payload = json.loads(stripped_line)
                records.append(_golden_record_from_payload(payload))
            except (TypeError, json.JSONDecodeError) as exc:
                raise ValueError(
                    f"Invalid JSONL record in {path} at line {line_number}: {exc}"
                ) from exc
    return records


def _golden_record_from_payload(payload: dict[str, object]) -> GoldenRecord:
    """Build a golden record from current or older JSONL payloads.

    Args:
        payload: JSON object loaded from a JSONL line.

    Returns:
        GoldenRecord: Normalized golden record.
    """

    allowed_fields = {field.name for field in fields(GoldenRecord)}
    normalized_payload = {
        field_name: payload[field_name]
        for field_name in allowed_fields
        if field_name in payload
    }
    return GoldenRecord(**normalized_payload)


def merge_records(
    existing_records: Iterable[GoldenRecord],
    new_records: Iterable[GoldenRecord],
    overwrite: bool = False,
) -> tuple[list[GoldenRecord], int, int, int]:
    """Merge existing and new records according to incremental update rules.

    Args:
        existing_records: Records already present in the dataset.
        new_records: Newly generated records.
        overwrite: Whether to replace existing records by logical source key.

    Returns:
        tuple[list[GoldenRecord], int, int, int]: Merged records, kept count,
        added count, and replaced count.
    """

    merged = list(existing_records)
    added = 0
    replaced = 0

    if overwrite:
        index_by_source_key = {
            record.source_key: index for index, record in enumerate(merged)
        }
        for record in new_records:
            existing_index = index_by_source_key.get(record.source_key)
            if existing_index is None:
                index_by_source_key[record.source_key] = len(merged)
                merged.append(record)
                added += 1
                continue
            merged[existing_index] = record
            replaced += 1
        kept = len(merged) - added - replaced
        return merged, kept, added, replaced

    existing_ids = {record.id for record in merged}
    for record in new_records:
        if record.id in existing_ids:
            continue
        existing_ids.add(record.id)
        merged.append(record)
        added += 1

    kept = len(merged) - added
    return merged, kept, added, replaced


def write_jsonl_records_atomic(path: Path, records: Iterable[GoldenRecord]) -> None:
    """Write JSONL records atomically.

    Args:
        path: Target JSONL path.
        records: Records to write.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        delete=False,
    ) as temp_file:
        temp_path = Path(temp_file.name)
        for record in records:
            temp_file.write(
                json.dumps(asdict(record), ensure_ascii=False, sort_keys=True)
            )
            temp_file.write("\n")

    os.replace(temp_path, path)
