"""
Author: L. Saetta
Date last modified: 2026-06-18
License: MIT
Description: Unit tests for the standalone OCI IAM IDCS token client.
"""

from __future__ import annotations

import base64
import json
from typing import Any

from clients import idcs_token_client


def _encode_jwt_section(payload: dict[str, Any]) -> str:
    """Encode a fake JWT JSON section for tests."""

    raw_payload = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw_payload).decode("ascii").rstrip("=")


def _fake_jwt() -> str:
    """Build a fake unsigned JWT-shaped token for rendering tests."""

    header = _encode_jwt_section({"alg": "RS256", "typ": "JWT"})
    payload = _encode_jwt_section(
        {
            "iss": "https://idcs.example.identity.oraclecloud.com",
            "aud": "rag-agent",
            "scope": "demo-agent/.default",
            "iat": 1_700_000_000,
            "exp": 1_700_003_600,
        }
    )
    return f"{header}.{payload}.signature"


def test_idcs_token_client_prints_token(
    monkeypatch: Any,
    capsys: Any,
) -> None:
    """Test the standalone token client prints the acquired token."""

    monkeypatch.setattr(
        idcs_token_client,
        "build_client_environment",
        lambda _env_file: {
            "IDENTITY_DOMAIN_URL": "https://idcs.example.identity.oraclecloud.com",
            "CONFIDENTIAL_APPLICATION_ID": "client-id",
            "CONFIDENTIAL_APPLICATION_SECRET": "client-secret",
            "IDCS_SCOPE": "demo-agent/.default",
        },
    )
    monkeypatch.setattr(
        idcs_token_client,
        "fetch_idcs_access_token",
        lambda _config: _fake_jwt(),
    )

    exit_code = idcs_token_client.main([])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "IDCS access token" in output
    assert "JWT header" in output
    assert "JWT payload" in output
    assert "JWT time claims" in output
    assert '"alg": "RS256"' in output
    assert '"aud": "rag-agent"' in output
    assert "JWT signature" not in output


def test_idcs_token_client_warns_when_token_is_not_jwt(
    monkeypatch: Any,
    capsys: Any,
) -> None:
    """Test non-JWT access tokens still print with a readable warning."""

    monkeypatch.setattr(
        idcs_token_client,
        "build_client_environment",
        lambda _env_file: {
            "IDENTITY_DOMAIN_URL": "https://idcs.example.identity.oraclecloud.com",
            "CONFIDENTIAL_APPLICATION_ID": "client-id",
            "CONFIDENTIAL_APPLICATION_SECRET": "client-secret",
            "IDCS_SCOPE": "demo-agent/.default",
        },
    )
    monkeypatch.setattr(
        idcs_token_client,
        "fetch_idcs_access_token",
        lambda _config: "opaque-token",
    )

    exit_code = idcs_token_client.main([])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "opaque-token" in output
    assert "JWT details could not be decoded" in output


def test_idcs_token_client_reports_missing_config(
    monkeypatch: Any,
    capsys: Any,
) -> None:
    """Test missing IDCS environment values are reported clearly."""

    monkeypatch.setattr(idcs_token_client, "build_client_environment", lambda _path: {})

    exit_code = idcs_token_client.main([])

    assert exit_code == 1
    error_output = capsys.readouterr().err
    assert "Missing IDCS token configuration" in error_output
    assert "IDENTITY_DOMAIN_URL" in error_output
    assert "CONFIDENTIAL_APPLICATION_ID" in error_output
    assert "CONFIDENTIAL_APPLICATION_SECRET" in error_output
    assert "IDCS_SCOPE" in error_output


def test_idcs_token_client_reports_token_request_failure(
    monkeypatch: Any,
    capsys: Any,
) -> None:
    """Test token request failures are reported without a traceback."""

    monkeypatch.setattr(
        idcs_token_client,
        "build_client_environment",
        lambda _env_file: {
            "IDENTITY_DOMAIN_URL": "https://idcs.example.identity.oraclecloud.com",
            "CONFIDENTIAL_APPLICATION_ID": "client-id",
            "CONFIDENTIAL_APPLICATION_SECRET": "client-secret",
            "IDCS_SCOPE": "demo-agent/.default",
        },
    )

    def fake_fetch_token(_config: Any) -> str:
        """Raise a fake token request failure."""

        raise RuntimeError("IDCS token request failed")

    monkeypatch.setattr(idcs_token_client, "fetch_idcs_access_token", fake_fetch_token)

    exit_code = idcs_token_client.main([])

    assert exit_code == 1
    assert "IDCS token request failed" in capsys.readouterr().err
