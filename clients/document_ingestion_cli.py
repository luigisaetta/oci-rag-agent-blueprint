"""
Author: L. Saetta
Date last modified: 2026-06-25
License: MIT
Description: Command-line client for submitting document ingestion jobs.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib import error, request
from uuid import uuid4

from clients.agent_cli import build_client_environment, maybe_fetch_idcs_access_token

DEFAULT_BASE_URL = "http://localhost:8080"
TERMINAL_JOB_STATES = frozenset({"SUCCEEDED", "FAILED", "CANCELED", "DELETED"})
DOCUMENT_CONTENT_TYPES = {
    ".md": "text/markdown",
    ".pdf": "application/pdf",
    ".txt": "text/plain",
}


@dataclass(frozen=True)
class UploadFilePart:
    """File part included in a multipart upload request.

    Attributes:
        field_name: Multipart form field name.
        file_path: Local file path.
        filename: Filename sent to the agent.
        content_type: MIME content type.
    """

    field_name: str
    file_path: Path
    filename: str
    content_type: str


@dataclass(frozen=True)
class SubmitIngestionRequest:
    """Request data for one document ingestion submission.

    Attributes:
        endpoint: Full `/documents/ingestions` endpoint.
        file_parts: Files to upload.
        prefix: Optional Object Storage object prefix.
        sync_display_name: Optional connector job display name.
        overwrite: Whether existing Object Storage objects may be replaced.
        access_token: Optional IDCS access token for protected Hosted Apps.
    """

    endpoint: str
    file_parts: list[UploadFilePart]
    prefix: str = ""
    sync_display_name: str = ""
    overwrite: bool = False
    access_token: str | None = None


def build_ingestions_endpoint(base_url: str) -> str:
    """Build the document ingestion endpoint from an agent base URL.

    Args:
        base_url: Agent base URL or full `/documents/ingestions` endpoint.

    Returns:
        str: Full ingestion submission endpoint.
    """

    clean_url = base_url.rstrip("/")
    if clean_url.endswith("/documents/ingestions"):
        return clean_url
    return f"{clean_url}/documents/ingestions"


def build_status_endpoint(base_url: str, job_id: str) -> str:
    """Build the document ingestion status endpoint.

    Args:
        base_url: Agent base URL or full `/documents/ingestions` endpoint.
        job_id: Connector file sync job identifier.

    Returns:
        str: Full ingestion status endpoint.
    """

    return f"{build_ingestions_endpoint(base_url)}/{job_id}"


def build_upload_file_parts(file_paths: Iterable[str]) -> list[UploadFilePart]:
    """Build validated multipart file parts from CLI file arguments.

    Args:
        file_paths: Local file paths provided by the user.

    Returns:
        list[UploadFilePart]: File parts ready for request construction.

    Raises:
        ValueError: If no files are provided or a path is invalid.
    """

    parts: list[UploadFilePart] = []
    for raw_path in file_paths:
        path = Path(raw_path)
        if not path.exists():
            raise ValueError(f"file does not exist: {path}")
        if not path.is_file():
            raise ValueError(f"path is not a file: {path}")
        content_type = (
            DOCUMENT_CONTENT_TYPES.get(path.suffix.lower())
            or mimetypes.guess_type(path.name)[0]
            or "application/octet-stream"
        )
        parts.append(
            UploadFilePart(
                field_name="files",
                file_path=path,
                filename=path.name,
                content_type=content_type,
            )
        )

    if not parts:
        raise ValueError("at least one --file value is required.")
    return parts


def encode_multipart_form(
    fields: dict[str, str],
    file_parts: Iterable[UploadFilePart],
    boundary: str | None = None,
) -> tuple[bytes, str]:
    """Encode multipart form fields and file content.

    Args:
        fields: Text form fields.
        file_parts: File parts to include in the request.
        boundary: Optional multipart boundary for deterministic tests.

    Returns:
        tuple[bytes, str]: Encoded body and content type header value.
    """

    multipart_boundary = boundary or f"----oci-rag-agent-{uuid4().hex}"
    chunks: list[bytes] = []

    for field_name, field_value in fields.items():
        if field_value == "":
            continue
        chunks.extend(
            [
                f"--{multipart_boundary}\r\n".encode("utf-8"),
                (
                    f'Content-Disposition: form-data; name="{field_name}"' "\r\n\r\n"
                ).encode("utf-8"),
                field_value.encode("utf-8"),
                b"\r\n",
            ]
        )

    for file_part in file_parts:
        chunks.extend(
            [
                f"--{multipart_boundary}\r\n".encode("utf-8"),
                (
                    "Content-Disposition: form-data; "
                    f'name="{file_part.field_name}"; '
                    f'filename="{file_part.filename}"\r\n'
                ).encode("utf-8"),
                f"Content-Type: {file_part.content_type}\r\n\r\n".encode("utf-8"),
                file_part.file_path.read_bytes(),
                b"\r\n",
            ]
        )

    chunks.append(f"--{multipart_boundary}--\r\n".encode("utf-8"))
    content_type = f"multipart/form-data; boundary={multipart_boundary}"
    return b"".join(chunks), content_type


def submit_document_ingestion(
    ingestion_request: SubmitIngestionRequest,
) -> dict[str, object]:
    """Submit document ingestion to the agent.

    Args:
        ingestion_request: Submission request data.

    Returns:
        dict[str, object]: Parsed JSON response payload.

    Raises:
        RuntimeError: If the HTTP request fails.
    """

    body, content_type = encode_multipart_form(
        {
            "prefix": ingestion_request.prefix,
            "sync_display_name": ingestion_request.sync_display_name,
            "overwrite": "true" if ingestion_request.overwrite else "false",
        },
        ingestion_request.file_parts,
    )
    headers = {"Content-Type": content_type, "Accept": "application/json"}
    if ingestion_request.access_token:
        headers["Authorization"] = f"Bearer {ingestion_request.access_token}"

    http_request = request.Request(
        ingestion_request.endpoint,
        data=body,
        headers=headers,
        method="POST",
    )
    return _send_json_request(http_request, timeout_seconds=300)


def get_document_ingestion_status(
    endpoint: str,
    access_token: str | None = None,
) -> dict[str, object]:
    """Read document ingestion job status from the agent.

    Args:
        endpoint: Full `/documents/ingestions/{job_id}` endpoint.
        access_token: Optional IDCS access token for protected Hosted Apps.

    Returns:
        dict[str, object]: Parsed JSON response payload.

    Raises:
        RuntimeError: If the HTTP request fails.
    """

    headers = {"Accept": "application/json"}
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"

    http_request = request.Request(endpoint, headers=headers, method="GET")
    return _send_json_request(http_request, timeout_seconds=120)


def wait_for_document_ingestion(
    base_url: str,
    job_id: str,
    access_token: str | None = None,
    interval_seconds: float = 5.0,
    timeout_seconds: float = 600.0,
) -> dict[str, object]:
    """Poll connector ingestion status until terminal state or timeout.

    Args:
        base_url: Agent base URL or full `/documents/ingestions` endpoint.
        job_id: Connector file sync job identifier.
        access_token: Optional IDCS access token for protected Hosted Apps.
        interval_seconds: Delay between status requests.
        timeout_seconds: Maximum wait time.

    Returns:
        dict[str, object]: Last status payload.

    Raises:
        RuntimeError: If polling times out.
    """

    deadline = time.monotonic() + timeout_seconds
    status_endpoint = build_status_endpoint(base_url, job_id)
    while True:
        status_payload = get_document_ingestion_status(status_endpoint, access_token)
        lifecycle_state = str(status_payload.get("lifecycle_state", "")).upper()
        print(f"[status] {job_id}: {lifecycle_state or 'UNKNOWN'}")
        if lifecycle_state in TERMINAL_JOB_STATES:
            return status_payload
        if time.monotonic() >= deadline:
            raise RuntimeError(f"Timed out waiting for ingestion job: {job_id}")
        time.sleep(interval_seconds)


def render_json_payload(payload: dict[str, object]) -> None:
    """Print a JSON payload in a stable readable format.

    Args:
        payload: JSON payload to print.
    """

    print(json.dumps(payload, indent=2, sort_keys=True))


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser.

    Returns:
        argparse.ArgumentParser: Configured parser.
    """

    parser = argparse.ArgumentParser(
        description="Submit and inspect agent-managed connector document ingestion."
    )
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help=(
            "Agent base URL or full /documents/ingestions endpoint. "
            f"Default: {DEFAULT_BASE_URL}"
        ),
    )
    parser.add_argument(
        "--auth",
        choices=("auto", "none", "idcs"),
        default="auto",
        help=(
            "Token acquisition mode. auto fetches an IDCS token when all "
            "required variables are set. Default: auto."
        ),
    )
    parser.add_argument(
        "--env-file",
        default=".env",
        help="Environment file for optional IDCS token settings. Default: .env",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    submit_parser = subparsers.add_parser("submit", help="Upload files and start sync.")
    submit_parser.add_argument(
        "--file",
        action="append",
        default=[],
        help="Document file to upload. Repeat for multiple files.",
    )
    submit_parser.add_argument("--prefix", default="", help="Object Storage prefix.")
    submit_parser.add_argument(
        "--sync-display-name",
        default="",
        help="Connector file sync display name.",
    )
    submit_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace existing Object Storage objects.",
    )
    submit_parser.add_argument(
        "--wait",
        action="store_true",
        help="Poll job status until terminal state.",
    )
    submit_parser.add_argument(
        "--poll-interval",
        type=float,
        default=5.0,
        help="Polling interval in seconds when --wait is used. Default: 5.",
    )
    submit_parser.add_argument(
        "--timeout",
        type=float,
        default=600.0,
        help="Polling timeout in seconds when --wait is used. Default: 600.",
    )

    status_parser = subparsers.add_parser("status", help="Read sync job status.")
    status_parser.add_argument("job_id", help="Connector file sync job identifier.")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the document ingestion command-line client.

    Args:
        argv: Optional command-line argument list for tests.

    Returns:
        int: Process exit code.
    """

    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        access_token = maybe_fetch_idcs_access_token(
            args.auth,
            build_client_environment(args.env_file),
        )
        if args.command == "submit":
            _run_submit_command(args, access_token)
        elif args.command == "status":
            _run_status_command(args, access_token)
        else:
            parser.error(f"Unsupported command: {args.command}")
    except ValueError as exc:
        parser.error(str(exc))
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    return 0


def _run_submit_command(args: argparse.Namespace, access_token: str | None) -> None:
    """Run the submit subcommand."""

    endpoint = build_ingestions_endpoint(args.base_url)
    file_parts = build_upload_file_parts(args.file)
    response_payload = submit_document_ingestion(
        SubmitIngestionRequest(
            endpoint=endpoint,
            file_parts=file_parts,
            prefix=args.prefix,
            sync_display_name=args.sync_display_name,
            overwrite=args.overwrite,
            access_token=access_token,
        )
    )
    render_json_payload(response_payload)

    if args.wait:
        job_id = response_payload.get("job_id")
        if not isinstance(job_id, str) or not job_id:
            raise RuntimeError("Submission response did not include job_id.")
        final_status = wait_for_document_ingestion(
            args.base_url,
            job_id,
            access_token=access_token,
            interval_seconds=args.poll_interval,
            timeout_seconds=args.timeout,
        )
        render_json_payload(final_status)


def _run_status_command(args: argparse.Namespace, access_token: str | None) -> None:
    """Run the status subcommand."""

    endpoint = build_status_endpoint(args.base_url, args.job_id)
    render_json_payload(get_document_ingestion_status(endpoint, access_token))


def _send_json_request(
    http_request: request.Request,
    timeout_seconds: int,
) -> dict[str, object]:
    """Send a request and parse its JSON response.

    Args:
        http_request: Prepared urllib request.
        timeout_seconds: Request timeout.

    Returns:
        dict[str, object]: Parsed JSON response payload.

    Raises:
        RuntimeError: If the request fails or returns invalid JSON.
    """

    try:
        with request.urlopen(http_request, timeout=timeout_seconds) as response:
            response_body = response.read().decode("utf-8")
    except error.HTTPError as exc:
        message = exc.read().decode("utf-8")
        raise RuntimeError(f"HTTP {exc.code}: {message}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"Unable to reach agent endpoint: {exc.reason}") from exc

    try:
        payload = json.loads(response_body)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Agent returned invalid JSON: {response_body}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("Agent returned a JSON value that is not an object.")
    return payload


if __name__ == "__main__":
    raise SystemExit(main())
