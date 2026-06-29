# Evaluations

This directory contains evaluation artifacts and operator-facing notes.

Generated golden datasets should be written under `evals/datasets/`.
Generated reports should be written under `evals/reports/`.

Real golden datasets may contain customer-derived questions, answers, and source
metadata. Do not commit generated JSONL files unless they are sanitized samples.

## Golden Dataset Generation

The golden dataset generator builds a JSONL file from PDF documents stored in an
OCI Object Storage bucket.

For each source PDF, the generator:

1. Lists eligible PDF objects from the configured bucket.
2. Extracts page text.
3. Selects up to `EVAL_MAX_PAGES_PER_PDF` significant pages.
4. Calls the configured evaluation model through the OpenAI-compatible
   Responses API.
5. Writes one question-answer example per selected page.

The generator is an offline management command. It is not part of the FastAPI
agent runtime.

## Required Environment

Activate the project environment before running the command:

```bash
conda activate oci-rag-agent-blueprint
```

Load the local `.env` file:

```bash
set -a
source .env
set +a
```

The generator requires these evaluation-specific variables:

```env
EVAL_SOURCE_NAMESPACE=replace-with-object-storage-namespace
EVAL_SOURCE_BUCKET=replace-with-object-storage-bucket
EVAL_SOURCE_PREFIX=
EVAL_GOLDEN_DATASET_PATH=evals/datasets/golden_dataset.jsonl
EVAL_OCI_REGION=us-chicago-1
EVAL_OCI_COMPARTMENT_ID=ocid1.compartment.oc1..example
EVAL_OCI_PROJECT_ID=ocid1.generativeaiproject.oc1..example
EVAL_OCI_MODEL_ID=example-eval-model-id
EVAL_MAX_PAGES_PER_PDF=10
EVAL_GENERATION_TEMPERATURE=0
```

The evaluation model settings are intentionally separate from the runtime agent
settings. The generator does not fall back from `EVAL_OCI_MODEL_ID` to
`OCI_MODEL_ID`.

For local execution with OCI config-file authentication, also configure:

```env
OCI_AUTH_MODE=config_file
OCI_CONFIG_FILE=/Users/your-user/.oci/config
OCI_PROFILE=DEFAULT
```

## Commands

Run a dry-run first. This lists and parses PDFs, selects pages, and prints a
summary without calling the LLM or writing the dataset:

```bash
python -m management.evals.generate_golden_dataset --dry-run
```

Limit a smoke test to one PDF:

```bash
python -m management.evals.generate_golden_dataset --dry-run --max-pdfs 1
```

Generate or incrementally update the dataset:

```bash
python -m management.evals.generate_golden_dataset
```

Regenerate examples for already-known source PDF pages:

```bash
python -m management.evals.generate_golden_dataset --overwrite
```

Disable the interactive progress bar for scripts or CI logs:

```bash
python -m management.evals.generate_golden_dataset --no-progress
```

## JSONL Schema

Each JSONL line is one golden example.

The field order is intentionally optimized for human review:

```json
{
  "id": "golden_...",
  "question": "Question text",
  "answer": "Expected answer text",
  "source_pdf_name": "source.pdf",
  "page_number": 1
}
```

Generated records do not store Object Storage namespace, bucket, object etag,
object size, page text, page text hash, generation model, or generation
timestamp.

## Language Behavior

Generated questions and answers use the same language as the source material.
If a page mixes languages, the generator asks the model to use the dominant
language of the substantive content.

## Troubleshooting

If the summary shows `PDFs discovered: 0`, check:

- `EVAL_SOURCE_NAMESPACE`
- `EVAL_SOURCE_BUCKET`
- `EVAL_SOURCE_PREFIX`
- Whether source object names end with `.pdf`
- Whether the OCI principal can list objects in the bucket

If the command fails with `Compartment ID must be provided`, verify
`EVAL_OCI_COMPARTMENT_ID` and make sure the current code is using the Responses
API based generator.

If the command fails with `Unsupported parameter: 'temperature'`, keep
`EVAL_GENERATION_TEMPERATURE=0`. With this value, the generator omits the
Responses API `temperature` parameter for model compatibility.

If `python -m management.evals.generate_golden_dataset` fails with missing
packages such as `httpx`, `oci`, `openai`, `pypdf`, or `tqdm`, activate the
project Conda environment first.

## RAG Evaluation Runner

After generating a golden dataset, start the RAG agent and run an end-to-end
evaluation against its `/responses` endpoint.

Example against a local unsecured agent:

```bash
python -m management.evals.run_rag_evaluation \
  --endpoint http://localhost:8080/responses \
  --dataset evals/datasets/golden_dataset.jsonl
```

Smoke test with a small subset:

```bash
python -m management.evals.run_rag_evaluation \
  --endpoint http://localhost:8080/responses \
  --dataset evals/datasets/golden_dataset.jsonl \
  --max-records 3 \
  --no-progress
```

The runner writes:

```text
evals/reports/rag_eval_results.jsonl
evals/reports/rag_eval_summary.json
```

It also prints a concise totals table to stdout with total, completed, pass,
review, fail, error, agent error, and judge error counts.

The runner uses the evaluation model configured by `EVAL_*` as an LLM judge. It
does not use the runtime agent model. The first implementation targets unsecured
agent endpoints; JWT support is intentionally out of scope.
