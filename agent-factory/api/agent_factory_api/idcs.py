"""
Author: L. Saetta
Date last modified: 2026-06-18
License: MIT
Description: IDCS token validation helpers for Agent Factory authentication checks.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Any
from urllib import error, parse, request


@dataclass(frozen=True)
class IdcsTokenValidationInput:
    """Input required to request and validate an IDCS access token.

    Attributes:
        identity_domain_url: Exact OCI IAM Identity Domain URL.
        confidential_application_id: Confidential application client identifier.
        confidential_application_secret: Confidential application client secret.
        audience_claim: Expected JWT audience claim.
        scope_claim: Expected JWT scope claim.
    """

    identity_domain_url: str
    confidential_application_id: str
    confidential_application_secret: str
    audience_claim: str
    scope_claim: str


class IdcsTokenValidationError(RuntimeError):
    """Raised when an IDCS token cannot be requested or validated."""


def validate_idcs_token(config: IdcsTokenValidationInput) -> dict[str, Any]:
    """Request and validate an IDCS access token for Hosted Application auth.

    Args:
        config: Token request and expected claim values.

    Returns:
        dict[str, Any]: Non-secret validation diagnostics.

    Raises:
        IdcsTokenValidationError: If token acquisition, decoding, or claim
            validation fails.
    """

    token_request_scope = build_token_request_scope(config)
    token = fetch_idcs_access_token(config, token_request_scope)
    _header, payload = decode_jwt(token)
    decoded_audience = payload.get("aud")
    decoded_scope = payload.get("scope")

    if not _audience_matches(decoded_audience, config.audience_claim):
        raise IdcsTokenValidationError(
            "Token audience claim does not match the expected Hosted "
            "Application audience."
        )
    if not _scope_matches(decoded_scope, config.scope_claim):
        raise IdcsTokenValidationError(
            "Token scope claim does not include the expected Hosted "
            "Application scope."
        )

    return {
        "status": "succeeded",
        "message": "IDCS token validation succeeded.",
        "token_request_scope": token_request_scope,
        "jwt_audience": decoded_audience,
        "jwt_scope": decoded_scope,
        "jwt_expires_at": payload.get("exp"),
    }


def build_token_request_scope(config: IdcsTokenValidationInput) -> str:
    """Build the OCI IAM OAuth token request scope.

    Args:
        config: Token validation input.

    Returns:
        str: Audience claim concatenated with scope claim without separators.
    """

    return f"{config.audience_claim}{config.scope_claim}"


def fetch_idcs_access_token(
    config: IdcsTokenValidationInput,
    token_request_scope: str,
) -> str:
    """Request an IDCS access token with client credentials.

    Args:
        config: Token validation input.
        token_request_scope: Concatenated OCI IAM token request scope.

    Returns:
        str: Access token returned by OCI IAM Identity Domains.

    Raises:
        IdcsTokenValidationError: If the token request fails or returns no
            access token.
    """

    credentials = (
        f"{config.confidential_application_id}:"
        f"{config.confidential_application_secret}"
    ).encode("utf-8")
    auth_header = base64.b64encode(credentials).decode("ascii")
    form_body = parse.urlencode(
        {
            "grant_type": "client_credentials",
            "scope": token_request_scope,
        }
    ).encode("utf-8")
    token_request = request.Request(
        build_token_endpoint_url(config.identity_domain_url),
        data=form_body,
        headers={
            "Authorization": f"Basic {auth_header}",
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
        method="POST",
    )

    try:
        with request.urlopen(token_request, timeout=60) as response:
            token_payload = json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        message = exc.read().decode("utf-8")
        raise IdcsTokenValidationError(
            f"IDCS token request failed with HTTP {exc.code}: {message}"
        ) from exc
    except error.URLError as exc:
        raise IdcsTokenValidationError(
            f"Unable to reach IDCS token endpoint: {exc.reason}"
        ) from exc

    access_token = token_payload.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise IdcsTokenValidationError(
            "IDCS token response did not include access_token."
        )
    return access_token


def build_token_endpoint_url(identity_domain_url: str) -> str:
    """Build the OCI IAM Identity Domains token endpoint URL.

    Args:
        identity_domain_url: Exact Identity Domain URL.

    Returns:
        str: OAuth token endpoint URL.
    """

    return f"{identity_domain_url.rstrip('/')}/oauth2/v1/token"


def decode_jwt(token: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Decode a JWT header and payload without verifying its signature.

    Args:
        token: JWT access token.

    Returns:
        tuple[dict[str, Any], dict[str, Any]]: Decoded header and payload.

    Raises:
        IdcsTokenValidationError: If the token is not a decodable JWT.
    """

    token_parts = token.split(".")
    if len(token_parts) != 3:
        raise IdcsTokenValidationError("Token is not a three-part JWT.")
    return decode_jwt_section(token_parts[0]), decode_jwt_section(token_parts[1])


def decode_jwt_section(encoded_section: str) -> dict[str, Any]:
    """Decode one base64url-encoded JWT JSON section.

    Args:
        encoded_section: Encoded JWT header or payload section.

    Returns:
        dict[str, Any]: Decoded JSON object.

    Raises:
        IdcsTokenValidationError: If the section cannot be decoded.
    """

    padding = "=" * (-len(encoded_section) % 4)
    try:
        raw_json = base64.urlsafe_b64decode(
            f"{encoded_section}{padding}".encode("ascii")
        )
        decoded = json.loads(raw_json.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise IdcsTokenValidationError(
            "JWT section is not valid base64url JSON."
        ) from exc

    if not isinstance(decoded, dict):
        raise IdcsTokenValidationError("JWT section must decode to a JSON object.")
    return decoded


def _audience_matches(decoded_audience: object, expected_audience: str) -> bool:
    """Return whether a decoded JWT audience matches the expected value."""

    if isinstance(decoded_audience, str):
        return decoded_audience == expected_audience
    if isinstance(decoded_audience, list):
        return expected_audience in decoded_audience
    return False


def _scope_matches(decoded_scope: object, expected_scope: str) -> bool:
    """Return whether a decoded JWT scope contains the expected value."""

    if isinstance(decoded_scope, str):
        return expected_scope in decoded_scope.split()
    if isinstance(decoded_scope, list):
        return expected_scope in decoded_scope
    return False
