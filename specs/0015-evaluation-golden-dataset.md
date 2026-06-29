# Evaluation Golden Dataset

## Purpose

This specification defines the first evaluation feature for the OCI RAG Agent
Blueprint: generation and incremental maintenance of a golden dataset used by
future end-to-end RAG evaluations.

The golden dataset is a JSON Lines file containing questions and expected
answers grounded in specific PDF pages from the configured knowledge base source
bucket.

## Scope

This specification covers:

- Reading PDF documents from an OCI Object Storage bucket.
- Selecting up to ten significant pages from each PDF.
- Generating one grounded question and one plausible expected answer per
  selected page by using the LLM configured through the existing environment.
- Writing and incrementally updating a JSONL golden dataset.
- Recording enough source metadata to later evaluate retrieval and answer
  grounding.
- Configuration, authentication, error handling, and unit test expectations for
  the dataset generation workflow.

This specification does not yet define:

- Running the RAG agent against the golden dataset.
- Scoring retrieval quality.
- Scoring generated answer faithfulness or correctness.
- Human review workflows for accepting or rejecting generated examples.
- Hosted scheduling for evaluation jobs.
- UI support for inspecting evaluation datasets or reports.

## Related Specifications

- [Architecture Guidelines](0001-architecture-guidelines.md)
- [Document Loading](0008-document-loading.md)
- [Agent Implementation](0003-agent-implementation.md)
- [Security](0007-security.md)
- [Agent Runtime Tuning](0009-agent-runtime-tuning.md)

## Design Overview

The golden dataset generator is an offline management command. It is not part
of the FastAPI serving path and must not affect normal agent request latency.

The command reads source PDFs from an Object Storage bucket, extracts page text,
selects pages that contain useful conceptual content, and asks the configured
LLM to produce grounded question-answer pairs.

The generated dataset is stored as JSONL. Each line is one evaluation example.
The JSONL format is append-friendly, easy to diff, and can be consumed by future
evaluation runners without requiring a database.

## Repository Layout

Evaluation code and generated evaluation artifacts must be kept separate.

Python code for offline evaluation utilities must live under:

```text
management/evals/
```

Generated datasets, reports, and operator-facing evaluation notes must live
under:

```text
evals/
```

Expected initial layout:

```text
evals/
  README.md
  datasets/
    .gitkeep
  reports/
    .gitkeep

management/
  evals/
    __init__.py
    generate_golden_dataset.py
    dataset_io.py
    pdf_pages.py
    page_selection.py
    question_generation.py
```

The `evals/` directory is for artifacts and documentation, not runtime server
code. The `management/evals/` package is for offline implementation code that
can be imported by tests and invoked from the command line.

Real golden datasets may contain customer-derived questions, answers, and
source metadata. They must not be committed unless they are explicitly
sanitized sample datasets. The implementation must update `.gitignore` before
writing generated JSONL files under `evals/datasets/`.

## Command-Line Interface

A new command-line module must be added under `management/evals`.

Proposed module:

```bash
python -m management.evals.generate_golden_dataset
```

Required inputs may be provided either through command-line arguments or through
environment variables loaded from the project `.env` file.

Required configuration:

- Object Storage namespace containing source PDFs.
- Object Storage bucket containing source PDFs.
- Output JSONL path.
- Evaluation OCI region.
- Evaluation OCI compartment OCID.
- Evaluation OCI project OCID.
- Evaluation OCI model identifier.
- OCI authentication mode and credentials compatible with existing project
  configuration.

Optional configuration:

- Object Storage prefix used to restrict source PDF discovery.
- Existing JSONL path to update in place.
- Maximum selected pages per PDF. Default: `10`.
- Maximum generated examples per PDF. Default: same as selected page limit.
- Maximum PDF count for a single run.
- Dry-run mode.
- Overwrite mode for replacing existing examples from changed source pages.
- LLM temperature for dataset generation. Default: low and deterministic.
- Random seed for deterministic tie-breaking when page scores are equal.

The implementation must support these command-line arguments:

- `--namespace`: Object Storage namespace.
- `--bucket`: Object Storage bucket name.
- `--prefix`: optional Object Storage object name prefix.
- `--output`: target JSONL file path.
- `--max-pages-per-pdf`: number of significant pages to select per PDF.
- `--max-pdfs`: optional limit for local development and smoke testing.
- `--overwrite`: replace examples for source pages that already exist in the
  output file.
- `--dry-run`: discover PDFs and selected pages without calling the LLM or
  writing the output file.
- `--no-progress`: disable the interactive progress bar.
- `--profile`: OCI configuration profile when config-file authentication is
  used.
- `--config-file`: OCI configuration file path when config-file authentication
  is used.

Environment variable fallbacks must be documented before implementation.
Proposed names:

- `EVAL_SOURCE_NAMESPACE`
- `EVAL_SOURCE_BUCKET`
- `EVAL_SOURCE_PREFIX`
- `EVAL_GOLDEN_DATASET_PATH`
- `EVAL_OCI_REGION`
- `EVAL_OCI_COMPARTMENT_ID`
- `EVAL_OCI_PROJECT_ID`
- `EVAL_OCI_MODEL_ID`
- `EVAL_MAX_PAGES_PER_PDF`
- `EVAL_GENERATION_TEMPERATURE`

The generator must use the evaluation-specific model settings:

- `EVAL_OCI_REGION`
- `EVAL_OCI_COMPARTMENT_ID`
- `EVAL_OCI_PROJECT_ID`
- `EVAL_OCI_MODEL_ID`

The evaluation model configuration is intentionally separate from the runtime
agent model configuration. This allows dataset generation to use a different
model, project, compartment, or region from the deployed RAG agent.

The generator may share the existing authentication settings:

- `OCI_AUTH_MODE`
- `OPENAI_API_KEY`, when API-key mode is used.
- `OCI_CONFIG_FILE`, when config-file mode is used.
- `OCI_PROFILE`, when config-file mode is used.

## Source PDF Discovery

The command must list objects in the configured Object Storage bucket.

Only objects whose names end with `.pdf`, case-insensitively, are eligible.
Directory marker objects and zero-byte objects must be ignored.

When `--prefix` or `EVAL_SOURCE_PREFIX` is provided, discovery must be limited
to that prefix.

The command must process PDFs in deterministic object-name order unless a future
option explicitly enables randomized sampling.

## PDF Text Extraction

The command must download each selected PDF to a temporary local file or stream
it through a parser that can extract text page by page.

The implementation should use a maintained Python PDF text extraction library.
The selected library must be added to project dependencies only when
implementation begins.

Extraction behavior:

- Page numbers recorded in the dataset must be one-based.
- Pages with no extracted text must be skipped.
- Pages with very little text must be skipped unless no better pages are
  available.
- Extraction failures for one PDF must be reported and must not abort the entire
  run unless strict mode is added in a future version.

## Significant Page Selection

For each PDF, the generator must select up to ten significant pages.

A significant page is a page that contains enough standalone conceptual content
to support a useful question and answer without relying on the PDF name, page
number, table of contents location, or section title alone.

The first implementation should use deterministic local heuristics before
calling the LLM:

- Prefer pages with sufficient natural-language text.
- Prefer pages with a mix of domain terms and explanatory sentences.
- Penalize table-of-contents pages, indexes, copyright pages, blank pages,
  revision history pages, and pages dominated by headers, footers, or isolated
  lists.
- Penalize pages where extracted text is mostly numeric tables without enough
  surrounding explanation.
- Avoid selecting adjacent pages only because they have repeated boilerplate.

The heuristic must be unit-testable without calling OCI services.

If more than ten pages remain after filtering, the command must choose the top
scoring pages and keep the final output ordered by source page number.

## Question And Answer Generation

For each selected page, the generator must call the configured LLM and request:

- One question that can be answered using only the content of that page.
- One plausible expected answer grounded only in that page.

The generated question must not mention:

- The PDF file name.
- The Object Storage object name.
- The page number.
- Phrases such as "in this document", "on this page", or "in this section".
- Section numbers or headings as the only basis for the question.

The generated answer must:

- Be directly supported by the selected page text.
- Avoid unsupported facts from the model's prior knowledge.
- Be concise enough for future automated evaluation.
- Preserve important terminology from the source page when useful.

The LLM prompt must require structured JSON output with at least:

```json
{
  "question": "string",
  "expected_answer": "string"
}
```

The implementation must validate the model output. Invalid JSON, empty
questions, empty answers, or questions that violate the forbidden-reference
rules must be retried a limited number of times and then reported as skipped.

## JSONL Schema

Each JSONL record must contain these required fields:

```json
{
  "id": "string",
  "source_object_name": "string",
  "source_pdf_name": "string",
  "page_number": 1,
  "question": "string",
  "expected_answer": "string"
}
```

Field definitions:

- `id`: deterministic identifier derived from namespace, bucket, object name,
  page number, and a source page content hash.
- `source_object_name`: full Object Storage object name of the PDF.
- `source_pdf_name`: PDF file name derived from the object name.
- `page_number`: one-based PDF page number.
- `question`: generated conceptual question.
- `expected_answer`: generated grounded answer.

The implementation should also include these metadata fields when available:

```json
{
  "namespace": "string",
  "bucket": "string",
  "source_etag": "string",
  "source_size_bytes": 123,
  "page_content_hash": "string",
  "generation_model": "string",
  "generated_at": "2026-06-29T00:00:00Z"
}
```

The JSONL file must use UTF-8 encoding. Each line must be valid JSON and must
not contain trailing commas.

The dataset must not store full page text by default, because the source PDFs
remain the system of record and page text may be large or sensitive. A future
debug mode may store short evidence snippets if needed for evaluation analysis.

## Incremental Update Behavior

The generator must support repeated runs against the same output JSONL file.

Before generating new examples, the command must load existing records and build
an index by deterministic `id`.

Default behavior:

- Keep existing records unchanged.
- Add records for newly discovered source pages.
- Skip records whose deterministic `id` already exists.
- Preserve valid existing records even if the source PDF is no longer present.

When `--overwrite` is provided:

- Regenerate examples for selected source pages.
- Replace existing records with the same logical source key.
- Keep records from unrelated PDFs unchanged.

The logical source key for overwrite matching must include namespace, bucket,
object name, and page number. The content hash is intentionally excluded from
the overwrite key so changed page content can replace an older generated
example.

The command must write updates atomically by writing a temporary file in the
same directory and then replacing the target JSONL file.

## Authentication And IAM

The command must use OCI SDK configuration compatible with the rest of the
project.

Supported authentication modes:

- `openai_api_key` for calling the OpenAI-compatible LLM endpoint, plus OCI
  config-file authentication for Object Storage access in local management
  usage.
- `config_file` for Object Storage access and, when supported by the existing
  client helper, LLM access.
- `resource_principal` for future hosted or OCI-native execution.

The generator must not silently fall back from `EVAL_OCI_MODEL_ID` to
`OCI_MODEL_ID`. If evaluation model configuration is missing, the command must
fail with an explicit configuration error. The only allowed fallback from the
runtime configuration is authentication, as described above.

Required IAM permissions:

- List objects in the configured Object Storage bucket.
- Read objects from the configured Object Storage bucket.
- Call the configured OCI Enterprise AI / OpenAI-compatible model endpoint.

The command must not log secrets, API keys, signer internals, or full
environment configuration.

## Error Handling

The command must fail fast before processing when required configuration is
missing or invalid.

Per-PDF failures must be summarized with:

- Object name.
- Failure phase: download, parse, page selection, generation, validation, or
  write.
- Actionable error message without secrets.

The process exit code must be:

- `0` when all eligible PDFs are processed and the output file is updated.
- `0` in dry-run mode when discovery and page selection complete.
- Non-zero when required configuration is missing, the output cannot be written,
  or all eligible PDFs fail.
- Non-zero when one or more PDFs fail and a future strict mode is enabled.

The command must print a final summary containing:

- PDFs discovered.
- PDFs processed.
- PDFs skipped.
- Pages extracted.
- Pages selected.
- Examples generated.
- Existing examples kept.
- Examples replaced.
- Examples skipped because generation or validation failed.
- Output JSONL path.

During interactive execution, the command should display a `tqdm` progress bar
showing processed PDFs out of the discovered total. Progress output must be
disabled automatically when stdout is not a terminal and must also be disabled
when `--no-progress` is provided.

## Test Expectations

Unit tests must cover:

- Object filtering for eligible PDFs.
- Prefix handling.
- Deterministic processing order.
- Page text extraction boundaries through mocked parser output.
- Significant page scoring and filtering.
- Skipping blank, table-of-contents, index, and boilerplate pages.
- Deterministic record ID generation.
- JSONL read and write behavior.
- Incremental append behavior.
- Overwrite behavior using the logical source key.
- LLM structured output parsing.
- Rejection of generated questions that reference file name, page number, page,
  document, or section.
- Retry behavior for invalid model output.
- Dry-run behavior.
- CLI validation errors.

Tests must mock OCI SDK clients and LLM calls. Unit tests must not require live
OCI resources, real PDFs from Object Storage, or real model calls.

## Acceptance Criteria

- A specification exists before implementation.
- The generator can discover PDF objects from a configured Object Storage bucket.
- The generator can select up to ten significant pages per PDF.
- The generator can create one grounded question and expected answer per
  selected page.
- The generator writes a UTF-8 JSONL file with deterministic IDs and source
  metadata.
- Re-running the generator appends new examples without duplicating existing
  records.
- `--overwrite` can replace examples for changed source pages.
- Dry-run mode reports discovered PDFs and selected pages without writing the
  dataset or calling the LLM.
- Unit tests cover selection, schema, incremental update, and generation
  validation behavior using mocks.
- Evaluation Python code lives under `management/evals/`.
- Generated datasets and reports live under `evals/`.
- The generator shows a progress bar for interactive runs and supports
  `--no-progress` for scripted runs.
