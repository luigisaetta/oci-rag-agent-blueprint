const TOKEN_REFRESH_SKEW_MILLISECONDS = 60_000;

export function buildHealthUrl(backendUrl) {
  return buildSiblingBackendUrl(backendUrl, "health");
}

export function buildEnvironmentUrl(backendUrl) {
  return buildSiblingBackendUrl(backendUrl, "config/environment");
}

function buildSiblingBackendUrl(backendUrl, siblingPath) {
  const trimmedUrl = backendUrl.trim();

  if (!trimmedUrl) {
    return `/${siblingPath}`;
  }

  if (/\/responses\/?$/u.test(trimmedUrl)) {
    return trimmedUrl.replace(/\/responses\/?$/u, `/${siblingPath}`);
  }

  return `${trimmedUrl.replace(/\/$/u, "")}/${siblingPath}`;
}

export function isAccessTokenUsable(tokenState, nowMilliseconds = Date.now()) {
  if (!tokenState?.accessToken) {
    return false;
  }

  if (!Number.isFinite(tokenState.expiresAtMilliseconds)) {
    return false;
  }

  return (
    tokenState.expiresAtMilliseconds - TOKEN_REFRESH_SKEW_MILLISECONDS >
    nowMilliseconds
  );
}

export function buildTokenState(tokenPayload, nowMilliseconds = Date.now()) {
  const expiresInSeconds = Number.isFinite(tokenPayload?.expires_in)
    ? tokenPayload.expires_in
    : 3600;

  return {
    accessToken: tokenPayload.access_token,
    expiresAtMilliseconds: nowMilliseconds + expiresInSeconds * 1000
  };
}
