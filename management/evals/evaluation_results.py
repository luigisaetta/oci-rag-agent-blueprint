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


@dataclass(frozen=True)
class SummaryCounts:
    """Precomputed counts used to build aggregate summary metrics."""

    total: int
    agent_errors: int
    judge_errors: int
    overall: Counter[str]
    answer_correctness: Counter[str]
    grounding: Counter[str]
    hallucination_risk: Counter[str]
    reference_match_status: Counter[str]


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
    counts = SummaryCounts(
        total=total,
        agent_errors=agent_errors,
        judge_errors=judge_errors,
        overall=Counter(result.judge.overall for result in results),
        answer_correctness=Counter(
            result.judge.answer_correctness for result in results
        ),
        grounding=Counter(result.judge.grounding for result in results),
        hallucination_risk=Counter(
            result.judge.hallucination_risk for result in results
        ),
        reference_match_status=Counter(
            result.reference_check.reference_match_status for result in results
        ),
    )

    return {
        "total_records": total,
        "completed_records": total - agent_errors,
        "agent_errors": agent_errors,
        "judge_errors": judge_errors,
        "answer_correctness": dict(counts.answer_correctness),
        "grounding": dict(counts.grounding),
        "hallucination_risk": dict(counts.hallucination_risk),
        "overall": dict(counts.overall),
        "reference_match_status": dict(counts.reference_match_status),
        "pass_rate": _rate(counts.overall.get("pass", 0), total),
        "review_rate": _rate(counts.overall.get("review", 0), total),
        "fail_rate": _rate(counts.overall.get("fail", 0), total),
        "error_rate": _rate(counts.overall.get("error", 0), total),
        "metrics": _build_summary_metrics(counts),
        "criteria": build_summary_criteria(),
        "results_path": str(results_path),
        "summary_path": str(summary_path),
    }


def build_summary_criteria() -> dict[str, Any]:
    """Return the evaluation criteria embedded in each summary report.

    Returns:
        dict[str, Any]: Machine-readable criteria and label definitions.
    """

    return {
        "retrieval": {
            "expected_pdf_found": (
                "At least one returned reference must match the golden "
                "source_pdf_name case-insensitively."
            ),
            "expected_page_found": (
                "At least one returned reference must expose the golden "
                "page_number when page metadata is available."
            ),
            "exact_evidence_match": (
                "The strongest deterministic retrieval outcome is "
                "reference_match_status=pdf_and_page_found."
            ),
        },
        "answer_correctness": {
            "correct": (
                "The answer is semantically equivalent to the expected answer "
                "and addresses the question."
            ),
            "partially_correct": (
                "The answer contains the main idea but misses important "
                "constraints, caveats, or details."
            ),
            "incorrect": (
                "The answer contradicts the expected answer or answers a "
                "different question."
            ),
            "not_answered": "The answer refuses, says it does not know, or is empty.",
        },
        "grounding": {
            "grounded": (
                "The answer is supported by returned references and expected "
                "PDF evidence is present."
            ),
            "weakly_grounded": (
                "The answer is plausible and partly supported, but expected "
                "page evidence is missing or references are incomplete."
            ),
            "ungrounded": "The answer is not supported by returned references.",
            "unknown": "References do not expose enough information to assess grounding.",
        },
        "hallucination_risk": {
            "low": "No unsupported claims are apparent.",
            "medium": "The answer includes plausible but not clearly supported details.",
            "high": (
                "The answer includes unsupported, contradictory, or fabricated "
                "claims."
            ),
            "unknown": "There is insufficient information to assess hallucination risk.",
        },
        "overall": {
            "pass": (
                "answer_correctness=correct, grounding is grounded or "
                "weakly_grounded, and hallucination_risk=low."
            ),
            "review": (
                "The answer is useful but needs inspection because correctness "
                "is partial, grounding is weak or unknown, or hallucination risk "
                "is medium."
            ),
            "fail": (
                "The answer is incorrect, not answered, ungrounded, or has high "
                "hallucination risk."
            ),
            "error": "The agent or judge failed.",
        },
    }


def _build_summary_metrics(counts: SummaryCounts) -> dict[str, float]:
    """Build derived evaluation metrics for the summary report.

    Args:
        counts: Precomputed summary counts.

    Returns:
        dict[str, float]: Named metrics rounded to four decimal places.
    """

    return {
        "completion_rate": _rate(counts.total - counts.agent_errors, counts.total),
        "agent_success_rate": _rate(counts.total - counts.agent_errors, counts.total),
        "judge_success_rate": _rate(counts.total - counts.judge_errors, counts.total),
        "pass_rate": _rate(counts.overall.get("pass", 0), counts.total),
        "review_rate": _rate(counts.overall.get("review", 0), counts.total),
        "fail_rate": _rate(counts.overall.get("fail", 0), counts.total),
        "error_rate": _rate(counts.overall.get("error", 0), counts.total),
        "answer_correct_rate": _rate(
            counts.answer_correctness.get("correct", 0), counts.total
        ),
        "answer_acceptable_rate": _rate(
            counts.answer_correctness.get("correct", 0)
            + counts.answer_correctness.get("partially_correct", 0),
            counts.total,
        ),
        "grounded_rate": _rate(counts.grounding.get("grounded", 0), counts.total),
        "grounded_or_weakly_grounded_rate": _rate(
            counts.grounding.get("grounded", 0)
            + counts.grounding.get("weakly_grounded", 0),
            counts.total,
        ),
        "low_hallucination_risk_rate": _rate(
            counts.hallucination_risk.get("low", 0), counts.total
        ),
        "expected_pdf_match_rate": _rate(
            counts.reference_match_status.get("pdf_and_page_found", 0)
            + counts.reference_match_status.get("pdf_found_page_unknown", 0)
            + counts.reference_match_status.get("pdf_found_page_missing", 0),
            counts.total,
        ),
        "expected_page_match_rate": _rate(
            counts.reference_match_status.get("pdf_and_page_found", 0), counts.total
        ),
        "exact_evidence_match_rate": _rate(
            counts.reference_match_status.get("pdf_and_page_found", 0), counts.total
        ),
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
