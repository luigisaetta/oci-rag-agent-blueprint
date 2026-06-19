export function buildTokenEndpointUrl(identityDomainUrl) {
  return `${identityDomainUrl.trim().replace(/\/$/u, "")}/oauth2/v1/token`;
}

export function validateTokenRequestPayload(payload) {
  const fieldErrors = {};

  for (const fieldName of [
    "identity_domain_url",
    "client_id",
    "client_secret",
    "scope"
  ]) {
    if (typeof payload?.[fieldName] !== "string" || !payload[fieldName].trim()) {
      fieldErrors[fieldName] = "This field is required.";
    }
  }

  if (
    typeof payload?.identity_domain_url === "string" &&
    payload.identity_domain_url.trim() &&
    !payload.identity_domain_url.trim().startsWith("https://")
  ) {
    fieldErrors.identity_domain_url = "Use an https:// Identity Domain URL.";
  }

  return fieldErrors;
}

export function buildTokenRequestBody(scope) {
  return new URLSearchParams({
    grant_type: "client_credentials",
    scope: scope.trim()
  });
}

export function normalizeTokenResponse(payload) {
  const accessToken = payload?.access_token;

  if (typeof accessToken !== "string" || !accessToken) {
    throw new Error("IDCS token response did not include access_token.");
  }

  return {
    access_token: accessToken,
    expires_in:
      typeof payload.expires_in === "number" && payload.expires_in > 0
        ? payload.expires_in
        : 3600,
    token_type:
      typeof payload.token_type === "string" && payload.token_type
        ? payload.token_type
        : "Bearer"
  };
}
