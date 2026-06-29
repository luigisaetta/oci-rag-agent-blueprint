"""
Author: L. Saetta
Date last modified: 2026-06-29
License: MIT
Description: Unit tests for the RAG evaluation runner.
"""

from __future__ import annotations

# pylint: disable=too-few-public-methods,duplicate-code

import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from management.evals.agent_client import build_agent_request, invoke_agent
from management.evals.dataset_io import GoldenRecord
from management.evals.evaluation_results import (
    EvaluationResult,
    build_summary,
    format_summary_table,
    write_results_jsonl,
    write_summary_json,
)
from management.evals.judge import (
    JudgeRequest,
    JudgeResult,
    build_judge_input,
    judge_answer,
    parse_judge_payload,
)
from management.evals.reference_checks import check_references
from management.evals.run_rag_evaluation import run_evaluation


class FakeHttpClient:
    """Fake HTTPX-like client."""

    def __init__(self, response: httpx.Response | Exception) -> None:
        """Initialize the fake client.

        Args:
            response: Response or exception returned by post.
        """

        self.response = response
        self.last_json: dict[str, object] | None = None

    def post(
        self,
        endpoint: str,
        **kwargs: object,
    ) -> httpx.Response:
        """Return the configured fake response.

        Args:
            endpoint: Request URL.
            kwargs: Request keyword arguments.

        Returns:
            httpx.Response: Fake response.
        """

        del endpoint
        self.last_json = kwargs.get("json")
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def build_streaming_http_client(frames: list[str]) -> httpx.Client:
    """Build an HTTPX client that returns a synthetic SSE stream."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content="".join(frames).encode("utf-8"),
            request=request,
            headers={"Content-Type": "text/event-stream"},
        )

    return httpx.Client(transport=httpx.MockTransport(handler))


class FakeResponses:
    """Fake Responses API."""

    def __init__(self, output_text: str) -> None:
        """Initialize fake responses.

        Args:
            output_text: Output text returned by create.
        """

        self.output_text = output_text
        self.last_kwargs: dict[str, object] = {}

    def create(self, **kwargs: object) -> SimpleNamespace:
        """Return a fake Responses API response."""

        self.last_kwargs = kwargs
        return SimpleNamespace(output_text=self.output_text)


class FakeJudgeClient:
    """Fake OpenAI-compatible judge client."""

    def __init__(self, output_text: str) -> None:
        """Initialize fake judge client."""

        self.responses = FakeResponses(output_text)


def make_result(overall: str = "pass") -> EvaluationResult:
    """Create a test evaluation result.

    Args:
        overall: Overall judge label.

    Returns:
        EvaluationResult: Test result.
    """

    return EvaluationResult(
        id="golden_1",
        question="Question?",
        expected_answer="Expected.",
        agent_answer="Expected.",
        source_pdf_name="doc.pdf",
        page_number=1,
        references=[{"title": "doc.pdf", "page": 1}],
        reference_check=check_references(
            [{"title": "doc.pdf", "page": 1}], "doc.pdf", 1
        ),
        judge=JudgeResult(
            answer_correctness="correct" if overall == "pass" else "incorrect",
            grounding="grounded" if overall == "pass" else "ungrounded",
            hallucination_risk="low" if overall == "pass" else "high",
            overall=overall,
            confidence=0.9,
            rationale="ok",
        ),
        agent_error=None,
        judge_error=None,
        conversation_id="conv",
        response_id="resp",
        usage={"total_tokens": 10},
        latency_ms=123,
    )


def test_build_agent_request_uses_streaming_new_conversation_by_default() -> None:
    """Agent request payload is streaming and starts a new conversation."""

    assert build_agent_request("hello") == {
        "new_conversation": True,
        "user_request": "hello",
        "stream": True,
    }


def test_invoke_agent_parses_success_stream() -> None:
    """Agent client normalizes a successful SSE response."""

    frames = [
        'event: metadata\ndata: {"conversation_id": "conv"}\n\n',
        'event: token\ndata: {"text": "ans"}\n\n',
        'event: token\ndata: {"text": "wer"}\n\n',
        'event: references\ndata: {"references": [{"title": "doc.pdf", "page": 1}]}\n\n',
        'event: usage\ndata: {"usage": {"total_tokens": 10}}\n\n',
        'event: done\ndata: {"conversation_id": "conv", "response_id": "resp"}\n\n',
    ]
    client = build_streaming_http_client(frames)

    result = invoke_agent("http://agent/responses", "question", http_client=client)

    assert result.conversation_id == "conv"
    assert result.response_id == "resp"
    assert result.answer == "answer"
    assert result.references == [{"title": "doc.pdf", "page": 1}]
    assert result.usage == {"total_tokens": 10}
    assert result.error is None
    client.close()


def test_invoke_agent_parses_success_json_response() -> None:
    """Agent client normalizes a successful JSON response."""

    response = httpx.Response(
        200,
        json={
            "conversation_id": "conv",
            "response_id": "resp",
            "agent_response": "answer",
            "references": [{"title": "doc.pdf", "page": 1}],
            "usage": {"total_tokens": 10},
            "error": None,
        },
        request=httpx.Request("POST", "http://agent/responses"),
    )
    fake_client = FakeHttpClient(response)

    result = invoke_agent(
        "http://agent/responses",
        "question",
        http_client=fake_client,
        stream=False,
    )

    assert fake_client.last_json == build_agent_request("question", stream=False)
    assert result.answer == "answer"
    assert result.references == [{"title": "doc.pdf", "page": 1}]
    assert result.error is None


def test_invoke_agent_preserves_http_error() -> None:
    """Agent client captures HTTP request errors."""

    response = httpx.Response(
        500,
        json={"error": "boom"},
        request=httpx.Request("POST", "http://agent/responses"),
    )

    result = invoke_agent(
        "http://agent/responses",
        "question",
        http_client=FakeHttpClient(response),
        stream=False,
    )

    assert result.error


def test_reference_check_matches_pdf_and_page() -> None:
    """Reference checker matches expected PDF and page."""

    result = check_references(
        [{"title": "folder/Doc.PDF", "page_number": "3"}],
        "doc.pdf",
        3,
    )

    assert result.expected_pdf_found
    assert result.expected_page_found
    assert result.reference_match_status == "pdf_and_page_found"


def test_reference_check_reports_unknown_page_when_page_missing() -> None:
    """Reference checker reports unknown when page metadata is absent."""

    result = check_references([{"title": "doc.pdf"}], "doc.pdf", 3)

    assert result.expected_pdf_found
    assert result.expected_page_found is None
    assert result.reference_match_status == "pdf_found_page_unknown"


def test_parse_judge_payload_validates_labels() -> None:
    """Judge payload parsing validates label values."""

    result = parse_judge_payload(
        json.dumps(
            {
                "answer_correctness": "correct",
                "grounding": "grounded",
                "hallucination_risk": "low",
                "overall": "pass",
                "confidence": 0.8,
                "rationale": "Supported.",
            }
        )
    )

    assert result.overall == "pass"

    with pytest.raises(ValueError, match="answer_correctness"):
        parse_judge_payload(
            json.dumps(
                {
                    "answer_correctness": "great",
                    "grounding": "grounded",
                    "hallucination_risk": "low",
                    "overall": "pass",
                    "confidence": 0.8,
                    "rationale": "Unsupported label.",
                }
            )
        )


def test_judge_answer_uses_responses_api_and_compartment() -> None:
    """Judge calls Responses API with the evaluation compartment."""

    client = FakeJudgeClient(
        json.dumps(
            {
                "answer_correctness": "correct",
                "grounding": "grounded",
                "hallucination_risk": "low",
                "overall": "pass",
                "confidence": 0.9,
                "rationale": "Supported.",
            }
        )
    )
    request = JudgeRequest(
        question="Question?",
        expected_answer="Expected.",
        agent_answer="Expected.",
        source_pdf_name="doc.pdf",
        page_number=1,
        references=[{"title": "doc.pdf", "page": 1}],
        reference_check=check_references(
            [{"title": "doc.pdf", "page": 1}], "doc.pdf", 1
        ),
    )

    result = judge_answer(client, "model", "compartment", request)

    assert result.overall == "pass"
    assert client.responses.last_kwargs["extra_body"] == {
        "compartmentId": "compartment"
    }
    assert client.responses.last_kwargs["timeout"] == 120
    assert "temperature" not in client.responses.last_kwargs
    assert "expected_answer" in build_judge_input(request)


def test_results_and_summary_are_written(tmp_path: Path) -> None:
    """Evaluation results and summary are written as JSON artifacts."""

    results_path = tmp_path / "results.jsonl"
    summary_path = tmp_path / "summary.json"
    results = [make_result("pass"), make_result("fail")]

    write_results_jsonl(results_path, results)
    summary = build_summary(results, results_path, summary_path)
    write_summary_json(summary_path, summary)

    assert len(results_path.read_text(encoding="utf-8").splitlines()) == 2
    assert json.loads(summary_path.read_text(encoding="utf-8"))["total_records"] == 2
    assert "pass" in format_summary_table(summary)


def test_run_evaluation_handles_agent_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Evaluation runner records agent errors without calling the judge."""

    monkeypatch.setenv("EVAL_OCI_REGION", "region")
    monkeypatch.setenv("EVAL_OCI_COMPARTMENT_ID", "compartment")
    monkeypatch.setenv("EVAL_OCI_PROJECT_ID", "project")
    monkeypatch.setenv("EVAL_OCI_MODEL_ID", "model")

    def fake_invoke_agent(*_args: object, **_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(
            conversation_id="",
            response_id="",
            answer="",
            references=[],
            usage=None,
            error="agent failed",
            latency_ms=1,
        )

    monkeypatch.setattr(
        "management.evals.run_rag_evaluation.invoke_agent",
        fake_invoke_agent,
    )
    records = [
        GoldenRecord(
            id="golden_1",
            question="Question?",
            answer="Expected.",
            source_pdf_name="doc.pdf",
            page_number=1,
        )
    ]

    results = run_evaluation(
        "http://agent/responses",
        records,
        judge_client=FakeJudgeClient("{}"),
        progress=False,
    )

    assert results[0].agent_error == "agent failed"
    assert results[0].judge.overall == "error"
