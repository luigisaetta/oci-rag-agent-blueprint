"""
Author: L. Saetta
Date last modified: 2026-06-29
License: MIT
Description: Command-line runner for end-to-end RAG evaluations.
"""

from __future__ import annotations

# pylint: disable=too-many-locals

import argparse
import os
import sys
from pathlib import Path
from typing import Any

from agent.config import OCI_AUTH_MODE_DEFAULT
from management.evals.agent_client import invoke_agent
from management.evals.dataset_io import GoldenRecord, load_jsonl_records
from management.evals.evaluation_results import (
    EvaluationResult,
    build_summary,
    format_summary_table,
    write_results_jsonl,
    write_summary_json,
)
from management.evals.generate_golden_dataset import (
    DEFAULT_EVAL_TEMPERATURE,
    EvalSettings,
    _optional_float_env,
)
from management.evals.judge import (
    JudgeRequest,
    error_judge_result,
    judge_answer,
)
from management.evals.reference_checks import check_references

DEFAULT_RESULTS_PATH = Path("evals/reports/rag_eval_results.jsonl")
DEFAULT_SUMMARY_PATH = Path("evals/reports/rag_eval_summary.json")
DEFAULT_AGENT_TIMEOUT_SECONDS = 120
DEFAULT_JUDGE_TIMEOUT_SECONDS = 120


def build_parser() -> argparse.ArgumentParser:
    """Build the RAG evaluation runner parser.

    Returns:
        argparse.ArgumentParser: Configured parser.
    """

    parser = argparse.ArgumentParser(
        description="Run end-to-end RAG evaluations against an agent endpoint."
    )
    parser.add_argument("--endpoint", required=True, help="Agent /responses endpoint.")
    parser.add_argument("--dataset", required=True, help="Golden dataset JSONL path.")
    parser.add_argument("--output", default=str(DEFAULT_RESULTS_PATH))
    parser.add_argument("--summary-output", default=str(DEFAULT_SUMMARY_PATH))
    parser.add_argument("--max-records", type=int)
    parser.add_argument(
        "--request-timeout-seconds",
        type=int,
        default=DEFAULT_AGENT_TIMEOUT_SECONDS,
    )
    parser.add_argument(
        "--judge-timeout-seconds",
        type=int,
        default=DEFAULT_JUDGE_TIMEOUT_SECONDS,
    )
    parser.add_argument("--no-progress", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the RAG evaluation command-line program.

    Args:
        argv: Optional argument list.

    Returns:
        int: Process exit code.
    """

    args = build_parser().parse_args(argv)
    try:
        records = _load_limited_records(Path(args.dataset), args.max_records)
        if not records:
            raise ValueError("dataset does not contain any records.")

        judge_client = _create_eval_openai_client()
        results = run_evaluation(
            endpoint=args.endpoint,
            records=records,
            judge_client=judge_client,
            request_timeout_seconds=args.request_timeout_seconds,
            judge_timeout_seconds=args.judge_timeout_seconds,
            progress=not args.no_progress,
        )
        results_path = Path(args.output)
        summary_path = Path(args.summary_output)
        write_results_jsonl(results_path, results)
        summary = build_summary(results, results_path, summary_path)
        write_summary_json(summary_path, summary)
        print(format_summary_table(summary))
        print(f"Results: {results_path}")
        print(f"Summary: {summary_path}")
        return 0
    except (RuntimeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


def run_evaluation(
    endpoint: str,
    records: list[GoldenRecord],
    judge_client: Any,
    request_timeout_seconds: int = DEFAULT_AGENT_TIMEOUT_SECONDS,
    judge_timeout_seconds: int = DEFAULT_JUDGE_TIMEOUT_SECONDS,
    progress: bool = True,
) -> list[EvaluationResult]:
    # pylint: disable=too-many-arguments,too-many-positional-arguments
    """Run evaluation records against an agent endpoint.

    Args:
        endpoint: Agent `/responses` endpoint.
        records: Golden dataset records.
        judge_client: OpenAI-compatible judge client.
        request_timeout_seconds: Agent request timeout.
        judge_timeout_seconds: Judge request timeout.
        progress: Whether to show progress for interactive terminals.

    Returns:
        list[EvaluationResult]: Evaluation results.
    """

    eval_region = _required_env("EVAL_OCI_REGION")
    eval_compartment_id = _required_env("EVAL_OCI_COMPARTMENT_ID")
    eval_project_id = _required_env("EVAL_OCI_PROJECT_ID")
    eval_model_id = _required_env("EVAL_OCI_MODEL_ID")
    del eval_region, eval_project_id
    temperature = _optional_float_env(
        "EVAL_GENERATION_TEMPERATURE",
        DEFAULT_EVAL_TEMPERATURE,
    )

    results: list[EvaluationResult] = []
    for record in _with_progress(records, progress, "Running RAG eval"):
        agent_response = invoke_agent(
            endpoint,
            record.question,
            timeout_seconds=request_timeout_seconds,
        )
        references = agent_response.references or []
        reference_check = check_references(
            references,
            record.source_pdf_name,
            record.page_number,
            agent_response.error,
        )

        judge_error = None
        if agent_response.error:
            judge_result = error_judge_result()
        else:
            try:
                judge_result = judge_answer(
                    judge_client,
                    eval_model_id,
                    eval_compartment_id,
                    JudgeRequest(
                        question=record.question,
                        expected_answer=record.answer,
                        agent_answer=agent_response.answer,
                        source_pdf_name=record.source_pdf_name,
                        page_number=record.page_number,
                        references=references,
                        reference_check=reference_check,
                    ),
                    temperature,
                    judge_timeout_seconds,
                )
            except Exception as exc:  # pylint: disable=broad-exception-caught
                judge_error = str(exc)
                judge_result = error_judge_result()

        results.append(
            EvaluationResult(
                id=record.id,
                question=record.question,
                expected_answer=record.answer,
                agent_answer=agent_response.answer,
                source_pdf_name=record.source_pdf_name,
                page_number=record.page_number,
                references=references,
                reference_check=reference_check,
                judge=judge_result,
                agent_error=agent_response.error,
                judge_error=judge_error,
                conversation_id=agent_response.conversation_id,
                response_id=agent_response.response_id,
                usage=agent_response.usage,
                latency_ms=agent_response.latency_ms,
            )
        )
    return results


def _load_limited_records(path: Path, max_records: int | None) -> list[GoldenRecord]:
    """Load and optionally limit golden records.

    Args:
        path: Dataset path.
        max_records: Optional record limit.

    Returns:
        list[GoldenRecord]: Loaded records.
    """

    records = load_jsonl_records(path)
    if max_records is not None:
        if max_records < 1:
            raise ValueError("--max-records must be greater than zero.")
        return records[:max_records]
    return records


def _create_eval_openai_client() -> Any:
    """Create the OpenAI-compatible judge client.

    Returns:
        Any: Configured client.
    """

    from agent.openai_client import (  # pylint: disable=import-outside-toplevel
        create_openai_client,
    )

    return create_openai_client(
        EvalSettings(
            oci_region=_required_env("EVAL_OCI_REGION"),
            oci_compartment_id=_required_env("EVAL_OCI_COMPARTMENT_ID"),
            oci_project_id=_required_env("EVAL_OCI_PROJECT_ID"),
            oci_model_id=_required_env("EVAL_OCI_MODEL_ID"),
            openai_api_key=os.environ.get("OPENAI_API_KEY", ""),
            oci_auth_mode=os.environ.get("OCI_AUTH_MODE", OCI_AUTH_MODE_DEFAULT),
        )
    )


def _required_env(name: str) -> str:
    """Read a required environment variable.

    Args:
        name: Environment variable name.

    Returns:
        str: Environment value.

    Raises:
        ValueError: If missing.
    """

    value = os.environ.get(name, "").strip()
    if not value:
        raise ValueError(f"Missing required environment variable: {name}")
    return value


def _with_progress(
    records: list[GoldenRecord],
    enabled: bool,
    description: str,
) -> list[GoldenRecord] | Any:
    """Wrap records in tqdm when appropriate.

    Args:
        records: Golden records.
        enabled: Whether progress is enabled.
        description: Progress description.

    Returns:
        list[GoldenRecord] | Any: Records or tqdm iterator.
    """

    if not enabled or not sys.stdout.isatty():
        return records
    try:
        from tqdm import tqdm  # pylint: disable=import-outside-toplevel
    except ImportError:
        return records
    return tqdm(records, total=len(records), desc=description, unit="record")


if __name__ == "__main__":
    sys.exit(main())
