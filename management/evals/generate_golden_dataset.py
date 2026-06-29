"""
Author: L. Saetta
Date last modified: 2026-06-29
License: MIT
Description: Generate and incrementally update RAG evaluation golden datasets.
"""

from __future__ import annotations

# pylint: disable=too-many-instance-attributes

import argparse
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol

from agent.config import OCI_AUTH_MODE_DEFAULT, OCI_AUTH_MODES
from management.load_documents import DEFAULT_OCI_PROFILE, load_oci_config
from management.evals.dataset_io import (
    GoldenRecord,
    build_record_id,
    hash_text,
    load_jsonl_records,
    merge_records,
    write_jsonl_records_atomic,
)
from management.evals.page_selection import (
    PdfPageText,
    select_significant_pages,
)
from management.evals.pdf_pages import download_pdf_to_tempfile, extract_pdf_pages
from management.evals.question_generation import generate_question_answer

DEFAULT_MAX_PAGES_PER_PDF = 10
DEFAULT_EVAL_TEMPERATURE = 0.0


class ObjectStorageClientProtocol(Protocol):
    """Protocol for Object Storage methods used by golden dataset generation."""

    def list_objects(
        self,
        namespace_name: str,
        bucket_name: str,
        prefix: str | None = None,
        start: str | None = None,
    ) -> Any:
        """List Object Storage objects."""

    def get_object(
        self,
        namespace_name: str,
        bucket_name: str,
        object_name: str,
    ) -> Any:
        """Read an Object Storage object."""


@dataclass(frozen=True)
class SourcePdfObject:
    """A source PDF object discovered in Object Storage.

    Attributes:
        name: Object name.
        size: Object size in bytes.
        etag: Object etag, when available.
    """

    name: str
    size: int = 0
    etag: str = ""


@dataclass(frozen=True)
class EvalSettings:
    """OpenAI-compatible settings for the evaluation generation model.

    Attributes mirror the fields required by `agent.openai_client`.
    """

    oci_region: str
    oci_compartment_id: str
    oci_project_id: str
    oci_model_id: str
    openai_api_key: str = ""
    oci_auth_mode: str = OCI_AUTH_MODE_DEFAULT
    langfuse_enabled: bool = False
    langfuse_base_url: str = ""
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""

    @property
    def base_url(self) -> str:
        """Build the OpenAI-compatible OCI Enterprise AI base URL.

        Returns:
            str: Base URL for the configured evaluation region.
        """

        return (
            f"https://inference.generativeai.{self.oci_region}.oci.oraclecloud.com"
            "/openai/v1"
        )


@dataclass(frozen=True)
class GoldenDatasetConfig:
    """Configuration for one golden dataset generation run.

    Attributes:
        namespace: Source Object Storage namespace.
        bucket: Source Object Storage bucket.
        output: Target JSONL file path.
        eval_region: Evaluation model region.
        eval_compartment_id: Evaluation model compartment OCID.
        eval_project_id: Evaluation project OCID.
        eval_model_id: Evaluation model identifier.
        prefix: Optional source object prefix.
        max_pages_per_pdf: Maximum significant pages selected per PDF.
        max_pdfs: Optional maximum number of PDFs to process.
        overwrite: Whether to replace existing records by source key.
        dry_run: Whether to avoid LLM calls and output writes.
        profile: OCI config profile.
        config_file: Optional OCI config path.
        oci_auth_mode: OCI auth mode for LLM access.
        openai_api_key: OpenAI-compatible API key for API-key mode.
        generation_temperature: LLM generation temperature.
        progress: Whether to show a progress bar when processing PDFs.
    """

    namespace: str
    bucket: str
    output: Path
    eval_region: str
    eval_compartment_id: str
    eval_project_id: str
    eval_model_id: str
    prefix: str = ""
    max_pages_per_pdf: int = DEFAULT_MAX_PAGES_PER_PDF
    max_pdfs: int | None = None
    overwrite: bool = False
    dry_run: bool = False
    profile: str = DEFAULT_OCI_PROFILE
    config_file: str | None = None
    oci_auth_mode: str = OCI_AUTH_MODE_DEFAULT
    openai_api_key: str = ""
    generation_temperature: float = DEFAULT_EVAL_TEMPERATURE
    progress: bool = True


@dataclass
class GoldenDatasetSummary:
    """Counters and errors from one golden dataset generation run."""

    pdfs_discovered: int = 0
    pdfs_processed: int = 0
    pdfs_skipped: int = 0
    pages_extracted: int = 0
    pages_selected: int = 0
    examples_generated: int = 0
    existing_examples_kept: int = 0
    examples_added: int = 0
    examples_replaced: int = 0
    examples_failed: int = 0
    output_path: str = ""
    errors: list[str] = field(default_factory=list)


def build_parser() -> argparse.ArgumentParser:
    """Build the golden dataset command-line parser.

    Returns:
        argparse.ArgumentParser: Configured parser.
    """

    parser = argparse.ArgumentParser(
        description="Generate a RAG evaluation golden dataset from Object Storage PDFs."
    )
    parser.add_argument("--namespace", default=os.environ.get("EVAL_SOURCE_NAMESPACE"))
    parser.add_argument("--bucket", default=os.environ.get("EVAL_SOURCE_BUCKET"))
    parser.add_argument("--prefix", default=os.environ.get("EVAL_SOURCE_PREFIX", ""))
    parser.add_argument("--output", default=os.environ.get("EVAL_GOLDEN_DATASET_PATH"))
    parser.add_argument("--eval-region", default=os.environ.get("EVAL_OCI_REGION"))
    parser.add_argument(
        "--eval-compartment-id",
        default=os.environ.get("EVAL_OCI_COMPARTMENT_ID"),
    )
    parser.add_argument(
        "--eval-project-id", default=os.environ.get("EVAL_OCI_PROJECT_ID")
    )
    parser.add_argument("--eval-model-id", default=os.environ.get("EVAL_OCI_MODEL_ID"))
    parser.add_argument(
        "--max-pages-per-pdf",
        type=int,
        default=_optional_int_env(
            "EVAL_MAX_PAGES_PER_PDF",
            DEFAULT_MAX_PAGES_PER_PDF,
        ),
    )
    parser.add_argument("--max-pdfs", type=int)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--no-progress",
        action="store_true",
        help="Disable the interactive progress bar.",
    )
    parser.add_argument(
        "--generation-temperature",
        type=float,
        default=_optional_float_env(
            "EVAL_GENERATION_TEMPERATURE",
            DEFAULT_EVAL_TEMPERATURE,
        ),
    )
    parser.add_argument(
        "--profile",
        default=os.environ.get("OCI_PROFILE", DEFAULT_OCI_PROFILE),
    )
    parser.add_argument("--config-file", default=os.environ.get("OCI_CONFIG_FILE"))
    return parser


def parse_args(argv: list[str] | None = None) -> GoldenDatasetConfig:
    """Parse command-line arguments into golden dataset configuration.

    Args:
        argv: Optional argument list. Uses process arguments when omitted.

    Returns:
        GoldenDatasetConfig: Parsed configuration.
    """

    args = build_parser().parse_args(argv)
    return GoldenDatasetConfig(
        namespace=args.namespace or "",
        bucket=args.bucket or "",
        prefix=args.prefix or "",
        output=Path(args.output or ""),
        eval_region=args.eval_region or "",
        eval_compartment_id=args.eval_compartment_id or "",
        eval_project_id=args.eval_project_id or "",
        eval_model_id=args.eval_model_id or "",
        max_pages_per_pdf=args.max_pages_per_pdf,
        max_pdfs=args.max_pdfs,
        overwrite=args.overwrite,
        dry_run=args.dry_run,
        profile=args.profile,
        config_file=args.config_file,
        oci_auth_mode=os.environ.get("OCI_AUTH_MODE", OCI_AUTH_MODE_DEFAULT),
        openai_api_key=os.environ.get("OPENAI_API_KEY", ""),
        generation_temperature=args.generation_temperature,
        progress=not args.no_progress,
    )


def validate_config(config: GoldenDatasetConfig) -> None:
    """Validate golden dataset configuration.

    Args:
        config: Configuration to validate.

    Raises:
        ValueError: If one or more settings are invalid.
    """

    required_values = {
        "EVAL_SOURCE_NAMESPACE": config.namespace,
        "EVAL_SOURCE_BUCKET": config.bucket,
        "EVAL_GOLDEN_DATASET_PATH": str(config.output),
        "EVAL_OCI_REGION": config.eval_region,
        "EVAL_OCI_COMPARTMENT_ID": config.eval_compartment_id,
        "EVAL_OCI_PROJECT_ID": config.eval_project_id,
        "EVAL_OCI_MODEL_ID": config.eval_model_id,
    }
    missing = [name for name, value in required_values.items() if not value.strip()]
    if missing:
        raise ValueError(
            "Missing required evaluation configuration: " + ", ".join(missing)
        )
    if config.oci_auth_mode not in OCI_AUTH_MODES:
        raise ValueError(f"Unsupported OCI_AUTH_MODE: {config.oci_auth_mode}")
    if config.oci_auth_mode == "openai_api_key" and not config.openai_api_key:
        raise ValueError(
            "OPENAI_API_KEY is required when OCI_AUTH_MODE=openai_api_key."
        )
    if config.max_pages_per_pdf < 1:
        raise ValueError("EVAL_MAX_PAGES_PER_PDF must be greater than zero.")
    if config.max_pdfs is not None and config.max_pdfs < 1:
        raise ValueError("--max-pdfs must be greater than zero.")
    if config.prefix.startswith("/"):
        raise ValueError("EVAL_SOURCE_PREFIX must not start with '/'.")


def discover_pdf_objects(
    object_storage_client: ObjectStorageClientProtocol,
    namespace: str,
    bucket: str,
    prefix: str = "",
) -> list[SourcePdfObject]:
    """Discover eligible PDF objects in Object Storage.

    Args:
        object_storage_client: OCI Object Storage client.
        namespace: Object Storage namespace.
        bucket: Object Storage bucket.
        prefix: Optional object prefix.

    Returns:
        list[SourcePdfObject]: Eligible PDF objects in deterministic order.
    """

    objects: list[SourcePdfObject] = []
    start: str | None = None
    while True:
        response = object_storage_client.list_objects(
            namespace_name=namespace,
            bucket_name=bucket,
            prefix=prefix or None,
            start=start,
        )
        list_response = response.data
        for item in getattr(list_response, "objects", []):
            name = getattr(item, "name", "")
            raw_size = getattr(item, "size", None)
            size = int(raw_size or 0)
            if name.lower().endswith(".pdf") and raw_size != 0:
                objects.append(
                    SourcePdfObject(
                        name=name,
                        size=size,
                        etag=str(getattr(item, "etag", "") or ""),
                    )
                )
        start = getattr(list_response, "next_start_with", None)
        if not start:
            break

    return sorted(objects, key=lambda source_object: source_object.name)


def generate_dataset(
    config: GoldenDatasetConfig,
    object_storage_client: ObjectStorageClientProtocol,
    llm_client: Any,
    page_extractor: Callable[[Path], list[PdfPageText]] = extract_pdf_pages,
) -> GoldenDatasetSummary:
    # pylint: disable=too-many-locals
    """Generate or update a golden dataset.

    Args:
        config: Generation configuration.
        object_storage_client: OCI Object Storage client.
        llm_client: OpenAI-compatible LLM client.
        page_extractor: Local PDF page extraction function.

    Returns:
        GoldenDatasetSummary: Run summary.
    """

    validate_config(config)
    summary = GoldenDatasetSummary(output_path=str(config.output))
    source_objects = discover_pdf_objects(
        object_storage_client,
        config.namespace,
        config.bucket,
        config.prefix,
    )
    if config.max_pdfs is not None:
        source_objects = source_objects[: config.max_pdfs]

    summary.pdfs_discovered = len(source_objects)
    generated_records: list[GoldenRecord] = []

    for source_object in _with_progress(
        source_objects,
        enabled=config.progress,
        description="Generating golden dataset",
    ):
        try:
            temp_path = download_pdf_to_tempfile(
                object_storage_client,
                config.namespace,
                config.bucket,
                source_object.name,
            )
            try:
                pages = page_extractor(temp_path)
            finally:
                temp_path.unlink(missing_ok=True)
            selected_pages = select_significant_pages(pages, config.max_pages_per_pdf)
            summary.pdfs_processed += 1
            summary.pages_extracted += len(pages)
            summary.pages_selected += len(selected_pages)

            if config.dry_run:
                continue

            for scored_page in selected_pages:
                try:
                    generated = generate_question_answer(
                        llm_client,
                        config.eval_model_id,
                        scored_page.page.text,
                        config.generation_temperature,
                    )
                    page_hash = hash_text(scored_page.page.text)
                    generated_records.append(
                        GoldenRecord(
                            id=build_record_id(
                                config.namespace,
                                config.bucket,
                                source_object.name,
                                scored_page.page.page_number,
                                page_hash,
                            ),
                            namespace=config.namespace,
                            bucket=config.bucket,
                            source_object_name=source_object.name,
                            source_pdf_name=Path(source_object.name).name,
                            page_number=scored_page.page.page_number,
                            question=generated.question,
                            expected_answer=generated.expected_answer,
                            source_etag=source_object.etag,
                            source_size_bytes=source_object.size,
                            page_content_hash=page_hash,
                            generation_model=config.eval_model_id,
                            generated_at=datetime.now(timezone.utc).isoformat(),
                        )
                    )
                    summary.examples_generated += 1
                except ValueError as exc:
                    summary.examples_failed += 1
                    summary.errors.append(
                        f"{source_object.name} page "
                        f"{scored_page.page.page_number}: validation failed: {exc}"
                    )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            summary.pdfs_skipped += 1
            summary.errors.append(f"{source_object.name}: {exc}")

    if config.dry_run:
        return summary

    existing_records = load_jsonl_records(config.output)
    merged_records, kept, added, replaced = merge_records(
        existing_records,
        generated_records,
        overwrite=config.overwrite,
    )
    write_jsonl_records_atomic(config.output, merged_records)
    summary.existing_examples_kept = kept
    summary.examples_added = added
    summary.examples_replaced = replaced
    return summary


def build_eval_settings(config: GoldenDatasetConfig) -> EvalSettings:
    """Build evaluation model settings for the OpenAI-compatible client.

    Args:
        config: Golden dataset configuration.

    Returns:
        EvalSettings: Client settings.
    """

    return EvalSettings(
        oci_region=config.eval_region,
        oci_compartment_id=config.eval_compartment_id,
        oci_project_id=config.eval_project_id,
        oci_model_id=config.eval_model_id,
        openai_api_key=config.openai_api_key,
        oci_auth_mode=config.oci_auth_mode,
    )


def build_object_storage_client(config: GoldenDatasetConfig) -> Any:
    """Build an OCI Object Storage client.

    Args:
        config: Golden dataset configuration.

    Returns:
        Any: OCI Object Storage client.

    Raises:
        RuntimeError: If the OCI SDK is unavailable or misconfigured.
    """

    try:
        import oci  # pylint: disable=import-outside-toplevel
    except ImportError as exc:
        raise RuntimeError(
            "The oci package is required for golden dataset generation."
        ) from exc

    oci_config = load_oci_config(config.config_file, config.profile)
    return oci.object_storage.ObjectStorageClient(oci_config)


def print_summary(summary: GoldenDatasetSummary) -> None:
    """Print a golden dataset generation summary.

    Args:
        summary: Run summary.
    """

    print("Golden dataset generation summary")
    print("---------------------------------")
    print(f"PDFs discovered    : {summary.pdfs_discovered}")
    print(f"PDFs processed     : {summary.pdfs_processed}")
    print(f"PDFs skipped       : {summary.pdfs_skipped}")
    print(f"Pages extracted    : {summary.pages_extracted}")
    print(f"Pages selected     : {summary.pages_selected}")
    print(f"Examples generated : {summary.examples_generated}")
    print(f"Examples kept      : {summary.existing_examples_kept}")
    print(f"Examples added     : {summary.examples_added}")
    print(f"Examples replaced  : {summary.examples_replaced}")
    print(f"Examples failed    : {summary.examples_failed}")
    print(f"Output             : {summary.output_path}")
    if summary.errors:
        print("")
        print("Errors")
        print("------")
        for error in summary.errors:
            print(f"- {error}")


def _with_progress(
    source_objects: list[SourcePdfObject],
    enabled: bool,
    description: str,
) -> list[SourcePdfObject] | Any:
    """Wrap source objects in a tqdm progress bar when appropriate.

    Args:
        source_objects: Source PDF objects to process.
        enabled: Whether progress reporting is allowed.
        description: Progress bar description.

    Returns:
        list[SourcePdfObject] | Any: Plain source objects or a tqdm iterator.
    """

    if not enabled or not sys.stdout.isatty():
        return source_objects

    try:
        from tqdm import tqdm  # pylint: disable=import-outside-toplevel
    except ImportError:
        return source_objects

    return tqdm(
        source_objects,
        total=len(source_objects),
        desc=description,
        unit="pdf",
    )


def main(argv: list[str] | None = None) -> int:
    """Run the golden dataset generator command-line program.

    Args:
        argv: Optional argument list. Uses process arguments when omitted.

    Returns:
        int: Process exit code.
    """

    try:
        config = parse_args(argv)
        validate_config(config)
        object_storage_client = build_object_storage_client(config)
        llm_client = None if config.dry_run else _create_eval_openai_client(config)
        summary = generate_dataset(config, object_storage_client, llm_client)
        print_summary(summary)
        if summary.pdfs_discovered and summary.pdfs_processed:
            return 0
        return 1 if not summary.pdfs_discovered or summary.pdfs_skipped else 0
    except (RuntimeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


def _create_eval_openai_client(config: GoldenDatasetConfig) -> Any:
    """Create the OpenAI-compatible client for eval generation.

    Args:
        config: Golden dataset configuration.

    Returns:
        Any: OpenAI-compatible client.
    """

    from agent.openai_client import (  # pylint: disable=import-outside-toplevel
        create_openai_client,
    )

    return create_openai_client(build_eval_settings(config))


def _optional_int_env(env_name: str, default_value: int) -> int:
    """Load an optional integer environment variable.

    Args:
        env_name: Environment variable name.
        default_value: Value used when missing.

    Returns:
        int: Parsed value.
    """

    raw_value = os.environ.get(env_name)
    if raw_value is None or not raw_value.strip():
        return default_value
    return int(raw_value)


def _optional_float_env(env_name: str, default_value: float) -> float:
    """Load an optional float environment variable.

    Args:
        env_name: Environment variable name.
        default_value: Value used when missing.

    Returns:
        float: Parsed value.
    """

    raw_value = os.environ.get(env_name)
    if raw_value is None or not raw_value.strip():
        return default_value
    return float(raw_value)


if __name__ == "__main__":
    sys.exit(main())
