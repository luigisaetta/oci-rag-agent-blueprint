"""
Author: L. Saetta
Date last modified: 2026-06-29
License: MIT
Description: Unit tests for evaluation golden dataset generation helpers.
"""

from __future__ import annotations

# pylint: disable=too-few-public-methods

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from management.evals.dataset_io import (
    GoldenRecord,
    build_record_id,
    hash_text,
    load_jsonl_records,
    merge_records,
    write_jsonl_records_atomic,
)
from management.evals.generate_golden_dataset import (
    GoldenDatasetConfig,
    SourcePdfObject,
    _with_progress,
    discover_pdf_objects,
    generate_dataset,
    parse_args,
    validate_config,
)
from management.evals.page_selection import (
    PdfPageText,
    score_page,
    select_significant_pages,
)
from management.evals.question_generation import (
    generate_question_answer,
    parse_generated_payload,
    validate_question,
)


class FakeObjectStorageClient:
    """Fake Object Storage client for dataset generation tests."""

    def __init__(self, objects: list[SimpleNamespace]) -> None:
        """Initialize the fake client.

        Args:
            objects: Object summaries returned by list operations.
        """

        self.objects = objects

    def list_objects(
        self,
        namespace_name: str,
        bucket_name: str,
        prefix: str | None = None,
        start: str | None = None,
    ) -> SimpleNamespace:
        """Return configured object summaries.

        Args:
            namespace_name: Ignored namespace.
            bucket_name: Ignored bucket.
            prefix: Optional prefix filter.
            start: Ignored pagination cursor.

        Returns:
            SimpleNamespace: OCI-like response object.
        """

        del namespace_name, bucket_name, start
        objects = [
            item for item in self.objects if not prefix or item.name.startswith(prefix)
        ]
        return SimpleNamespace(
            data=SimpleNamespace(objects=objects, next_start_with=None)
        )

    def get_object(
        self,
        namespace_name: str,
        bucket_name: str,
        object_name: str,
    ) -> SimpleNamespace:
        """Return a fake PDF byte stream.

        Args:
            namespace_name: Ignored namespace.
            bucket_name: Ignored bucket.
            object_name: Ignored object name.

        Returns:
            SimpleNamespace: OCI-like response object.
        """

        del namespace_name, bucket_name, object_name
        stream = SimpleNamespace(stream=lambda *_args, **_kwargs: [b"%PDF-FAKE"])
        return SimpleNamespace(data=SimpleNamespace(raw=stream))


class FakeChatCompletions:
    """Fake chat completions API returning queued contents."""

    def __init__(self, contents: list[str]) -> None:
        """Initialize the fake completions API.

        Args:
            contents: Raw message contents returned by create calls.
        """

        self.contents = contents
        self.calls = 0

    def create(self, **_kwargs: object) -> SimpleNamespace:
        """Return the next fake completion.

        Returns:
            SimpleNamespace: OpenAI-like response.
        """

        content = self.contents[min(self.calls, len(self.contents) - 1)]
        self.calls += 1
        message = SimpleNamespace(content=content)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class FakeLlmClient:
    """Fake OpenAI-compatible client."""

    def __init__(self, contents: list[str]) -> None:
        """Initialize the fake client.

        Args:
            contents: Completion contents returned in order.
        """

        self.chat = SimpleNamespace(completions=FakeChatCompletions(contents))


def make_config(output: Path, dry_run: bool = False) -> GoldenDatasetConfig:
    """Build a valid test config.

    Args:
        output: Output JSONL path.
        dry_run: Whether dry-run mode is enabled.

    Returns:
        GoldenDatasetConfig: Valid configuration.
    """

    return GoldenDatasetConfig(
        namespace="namespace",
        bucket="bucket",
        output=output,
        eval_region="us-chicago-1",
        eval_compartment_id="ocid1.compartment.oc1..example",
        eval_project_id="ocid1.generativeaiproject.oc1..example",
        eval_model_id="eval-model",
        openai_api_key="key",
        dry_run=dry_run,
    )


def test_discover_pdf_objects_filters_and_orders_eligible_pdfs() -> None:
    """Eligible PDF objects are filtered, prefixed, and ordered."""

    client = FakeObjectStorageClient(
        [
            SimpleNamespace(name="docs/z.txt", size=10, etag="txt"),
            SimpleNamespace(name="docs/b.PDF", size=20, etag="b"),
            SimpleNamespace(name="other/a.pdf", size=30, etag="other"),
            SimpleNamespace(name="docs/empty.pdf", size=0, etag="empty"),
            SimpleNamespace(name="docs/unknown-size.pdf", size=None, etag="unknown"),
            SimpleNamespace(name="docs/a.pdf", size=10, etag="a"),
        ]
    )

    discovered = discover_pdf_objects(client, "ns", "bucket", "docs/")

    assert [item.name for item in discovered] == [
        "docs/a.pdf",
        "docs/b.PDF",
        "docs/unknown-size.pdf",
    ]
    assert discovered[0].etag == "a"


def test_score_page_penalizes_boilerplate_and_selects_useful_pages() -> None:
    """Significant page selection prefers explanatory natural language."""

    useful_text = (
        "Retrieval augmented generation combines search results with model "
        "generation. The retrieval stage supplies grounded context. The answer "
        "stage should cite or rely on that context. This design reduces "
        "unsupported claims and helps operators inspect why an answer was "
        "produced. The workflow is especially useful when documentation changes "
        "often and the model should not memorize all operational details."
    )
    pages = [
        PdfPageText(1, "Table of Contents\n1 Intro\n2 Install\n3 Usage"),
        PdfPageText(2, useful_text),
        PdfPageText(3, "Index\nA 1\nB 2\nC 3"),
    ]

    assert score_page(pages[1]) > score_page(pages[0])
    selected = select_significant_pages(pages, max_pages=1)

    assert [page.page.page_number for page in selected] == [2]


def test_record_id_and_jsonl_roundtrip(tmp_path: Path) -> None:
    """Golden records can be written atomically and loaded from JSONL."""

    page_hash = hash_text("Some extracted page text")
    record = GoldenRecord(
        id=build_record_id("ns", "bucket", "doc.pdf", 7, page_hash),
        namespace="ns",
        bucket="bucket",
        source_object_name="doc.pdf",
        source_pdf_name="doc.pdf",
        page_number=7,
        question="What does the page explain?",
        expected_answer="It explains a concept.",
        page_content_hash=page_hash,
    )
    output = tmp_path / "golden.jsonl"

    write_jsonl_records_atomic(output, [record])
    loaded = load_jsonl_records(output)

    assert loaded == [record]
    assert json.loads(output.read_text(encoding="utf-8").splitlines()[0])["id"]


def test_merge_records_appends_without_duplicates() -> None:
    """Default merge behavior keeps existing records and appends only new IDs."""

    existing = GoldenRecord(
        id="id-1",
        namespace="ns",
        bucket="bucket",
        source_object_name="doc.pdf",
        source_pdf_name="doc.pdf",
        page_number=1,
        question="Question?",
        expected_answer="Answer.",
    )
    new_record = GoldenRecord(
        id="id-2",
        namespace="ns",
        bucket="bucket",
        source_object_name="doc.pdf",
        source_pdf_name="doc.pdf",
        page_number=2,
        question="Second question?",
        expected_answer="Second answer.",
    )

    merged, kept, added, replaced = merge_records(
        [existing],
        [existing, new_record],
    )

    assert merged == [existing, new_record]
    assert (kept, added, replaced) == (1, 1, 0)


def test_merge_records_overwrites_by_source_key() -> None:
    """Overwrite merge replaces records with the same source key."""

    existing = GoldenRecord(
        id="old-id",
        namespace="ns",
        bucket="bucket",
        source_object_name="doc.pdf",
        source_pdf_name="doc.pdf",
        page_number=1,
        question="Old?",
        expected_answer="Old.",
    )
    replacement = GoldenRecord(
        id="new-id",
        namespace="ns",
        bucket="bucket",
        source_object_name="doc.pdf",
        source_pdf_name="doc.pdf",
        page_number=1,
        question="New?",
        expected_answer="New.",
    )

    merged, kept, added, replaced = merge_records(
        [existing],
        [replacement],
        overwrite=True,
    )

    assert merged == [replacement]
    assert (kept, added, replaced) == (0, 0, 1)


def test_generated_payload_validation_rejects_source_location_references() -> None:
    """Generated questions must not refer to page, document, file, or section."""

    with pytest.raises(ValueError, match="forbidden reference"):
        validate_question("What does this page say about retrieval?")

    with pytest.raises(ValueError, match="forbidden reference"):
        parse_generated_payload(
            json.dumps(
                {
                    "question": "What is explained in this document?",
                    "expected_answer": "A concept is explained.",
                }
            )
        )


def test_generate_question_answer_retries_invalid_output() -> None:
    """Invalid LLM output is retried before returning a valid example."""

    client = FakeLlmClient(
        [
            "not-json",
            json.dumps(
                {
                    "question": "How does retrieval grounding help answers?",
                    "expected_answer": "It ties answers to retrieved context.",
                }
            ),
        ]
    )

    generated = generate_question_answer(client, "model", "page text")

    assert generated.question == "How does retrieval grounding help answers?"
    assert client.chat.completions.calls == 2


def test_parse_args_uses_eval_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """CLI parsing uses evaluation-specific environment variables."""

    monkeypatch.setenv("EVAL_SOURCE_NAMESPACE", "ns")
    monkeypatch.setenv("EVAL_SOURCE_BUCKET", "bucket")
    monkeypatch.setenv("EVAL_GOLDEN_DATASET_PATH", "evals/datasets/golden.jsonl")
    monkeypatch.setenv("EVAL_OCI_REGION", "region")
    monkeypatch.setenv("EVAL_OCI_COMPARTMENT_ID", "compartment")
    monkeypatch.setenv("EVAL_OCI_PROJECT_ID", "project")
    monkeypatch.setenv("EVAL_OCI_MODEL_ID", "eval-model")
    monkeypatch.setenv("OPENAI_API_KEY", "key")

    config = parse_args([])

    assert config.eval_model_id == "eval-model"
    assert config.output == Path("evals/datasets/golden.jsonl")


def test_parse_args_supports_no_progress(monkeypatch: pytest.MonkeyPatch) -> None:
    """The CLI can disable interactive progress output."""

    monkeypatch.setenv("EVAL_SOURCE_NAMESPACE", "ns")
    monkeypatch.setenv("EVAL_SOURCE_BUCKET", "bucket")
    monkeypatch.setenv("EVAL_GOLDEN_DATASET_PATH", "evals/datasets/golden.jsonl")
    monkeypatch.setenv("EVAL_OCI_REGION", "region")
    monkeypatch.setenv("EVAL_OCI_COMPARTMENT_ID", "compartment")
    monkeypatch.setenv("EVAL_OCI_PROJECT_ID", "project")
    monkeypatch.setenv("EVAL_OCI_MODEL_ID", "eval-model")
    monkeypatch.setenv("OPENAI_API_KEY", "key")

    config = parse_args(["--no-progress"])

    assert not config.progress


def test_progress_wrapper_returns_plain_objects_when_disabled() -> None:
    """Progress wrapping is bypassed when explicitly disabled."""

    source_objects = [SourcePdfObject(name="doc.pdf", size=1)]

    wrapped = _with_progress(source_objects, enabled=False, description="Test")

    assert wrapped is source_objects


def test_validate_config_requires_eval_model_not_runtime_model(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Evaluation model configuration cannot fall back to OCI_MODEL_ID."""

    monkeypatch.setenv("OCI_MODEL_ID", "runtime-model")
    config = make_config(tmp_path / "golden.jsonl")
    config = GoldenDatasetConfig(
        **{
            **config.__dict__,
            "eval_model_id": "",
        }
    )

    with pytest.raises(ValueError, match="EVAL_OCI_MODEL_ID"):
        validate_config(config)


def test_generate_dataset_dry_run_selects_pages_without_llm_or_write(
    tmp_path: Path,
) -> None:
    """Dry-run mode discovers and selects pages without writing JSONL."""

    config = make_config(tmp_path / "golden.jsonl", dry_run=True)
    client = FakeObjectStorageClient(
        [SimpleNamespace(name="docs/source.pdf", size=20, etag="etag")]
    )
    pages = [
        PdfPageText(
            1,
            (
                "A vector store stores embeddings for retrieval. The retrieval "
                "tool searches the store for relevant chunks. The response uses "
                "those chunks as context. This helps keep answers aligned with "
                "the available knowledge base and reduces unsupported details."
            ),
        )
    ]

    summary = generate_dataset(
        config,
        client,
        llm_client=None,
        page_extractor=lambda _path: pages,
    )

    assert summary.pdfs_discovered == 1
    assert summary.pages_selected == 1
    assert not config.output.exists()
