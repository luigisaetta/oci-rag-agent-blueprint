"""
Author: L. Saetta
Date last modified: 2026-06-29
License: MIT
Description: Result writing and summary helpers for RAG evaluation runs.
"""

from __future__ import annotations

# pylint: disable=too-many-instance-attributes,duplicate-code

import json
import os
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Iterable

from management.evals.judge import JudgeResult
from management.evals.reference_checks import ReferenceCheck


@dataclass(frozen=True)
class EvaluationResult:
    """One RAG evaluation result row."""

    id: str
    question: str
    expected_answer: str
    agent_answer: str
    source_pdf_name: str
    page_number: int
    references: list[dict[str, Any]]
    reference_check: ReferenceCheck
    judge: JudgeResult
    agent_error: str | None
    judge_error: str | None
    conversation_id: str
    response_id: str
    usage: dict[str, Any] | None
    latency_ms: int

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dictionary."""

        payload = asdict(self)
        payload["reference_check"] = self.reference_check.to_dict()
        payload["judge"] = self.judge.to_dict()
        return payload


def write_results_jsonl(path: Path, results: Iterable[EvaluationResult]) -> None:
    """Write evaluation result rows atomically.

    Args:
        path: Target JSONL path.
        results: Evaluation results.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as tmp:
        tmp_path = Path(tmp.name)
        for result in results:
            tmp.write(json.dumps(result.to_dict(), ensure_ascii=False))
            tmp.write("\n")
    os.replace(tmp_path, path)


def build_summary(
    results: list[EvaluationResult],
    results_path: Path,
    summary_path: Path,
) -> dict[str, Any]:
    """Build an aggregate evaluation summary.

    Args:
        results: Evaluation results.
        results_path: Result JSONL path.
        summary_path: Summary JSON path.

    Returns:
        dict[str, Any]: Summary payload.
    """

    total = len(results)
    agent_errors = sum(1 for result in results if result.agent_error)
    judge_errors = sum(1 for result in results if result.judge_error)
    overall_counts = Counter(result.judge.overall for result in results)

    return {
        "total_records": total,
        "completed_records": total - agent_errors,
        "agent_errors": agent_errors,
        "judge_errors": judge_errors,
        "answer_correctness": dict(
            Counter(result.judge.answer_correctness for result in results)
        ),
        "grounding": dict(Counter(result.judge.grounding for result in results)),
        "hallucination_risk": dict(
            Counter(result.judge.hallucination_risk for result in results)
        ),
        "overall": dict(overall_counts),
        "reference_match_status": dict(
            Counter(result.reference_check.reference_match_status for result in results)
        ),
        "pass_rate": _rate(overall_counts.get("pass", 0), total),
        "review_rate": _rate(overall_counts.get("review", 0), total),
        "fail_rate": _rate(overall_counts.get("fail", 0), total),
        "error_rate": _rate(overall_counts.get("error", 0), total),
        "results_path": str(results_path),
        "summary_path": str(summary_path),
    }


def write_summary_json(path: Path, summary: dict[str, Any]) -> None:
    """Write summary JSON atomically.

    Args:
        path: Target JSON path.
        summary: Summary payload.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as tmp:
        tmp_path = Path(tmp.name)
        json.dump(summary, tmp, ensure_ascii=False, indent=2)
        tmp.write("\n")
    os.replace(tmp_path, path)


def format_summary_table(summary: dict[str, Any]) -> str:
    """Format a concise console summary table.

    Args:
        summary: Summary payload.

    Returns:
        str: Human-readable table.
    """

    rows = [
        ("total", summary["total_records"]),
        ("completed", summary["completed_records"]),
        ("pass", summary["overall"].get("pass", 0)),
        ("review", summary["overall"].get("review", 0)),
        ("fail", summary["overall"].get("fail", 0)),
        ("error", summary["overall"].get("error", 0)),
        ("agent_errors", summary["agent_errors"]),
        ("judge_errors", summary["judge_errors"]),
    ]
    label_width = max(len(label) for label, _value in rows)
    value_width = max(len(str(value)) for _label, value in rows)
    line = f"+-{'-' * label_width}-+-{'-' * value_width}-+"
    output = ["Evaluation summary", line]
    for label, value in rows:
        output.append(f"| {label:<{label_width}} | {value:>{value_width}} |")
    output.append(line)
    return "\n".join(output)


def _rate(count: int, total: int) -> float:
    """Calculate a rounded rate.

    Args:
        count: Count.
        total: Total.

    Returns:
        float: Rate rounded to four decimals.
    """

    if total == 0:
        return 0.0
    return round(count / total, 4)
