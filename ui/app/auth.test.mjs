import assert from "node:assert/strict";
import test from "node:test";

import {
  buildEnvironmentUrl,
  buildHealthUrl,
  buildTokenState,
  isAccessTokenUsable
} from "./auth.mjs";

test("buildHealthUrl derives health endpoint from responses endpoint", () => {
  assert.equal(
    buildHealthUrl("https://example.com/invoke/responses"),
    "https://example.com/invoke/health"
  );
  assert.equal(
    buildHealthUrl("https://example.com/invoke/responses/"),
    "https://example.com/invoke/health"
  );
});

test("buildHealthUrl appends health when backend URL is a base URL", () => {
  assert.equal(buildHealthUrl("https://example.com/invoke"), "https://example.com/invoke/health");
});

test("buildEnvironmentUrl derives environment endpoint from responses endpoint", () => {
  assert.equal(
    buildEnvironmentUrl("https://example.com/invoke/responses"),
    "https://example.com/invoke/config/environment"
  );
  assert.equal(
    buildEnvironmentUrl("https://example.com/invoke/responses/"),
    "https://example.com/invoke/config/environment"
  );
});

test("buildEnvironmentUrl appends config path when backend URL is a base URL", () => {
  assert.equal(
    buildEnvironmentUrl("https://example.com/invoke"),
    "https://example.com/invoke/config/environment"
  );
});

test("isAccessTokenUsable rejects missing and nearly expired tokens", () => {
  assert.equal(isAccessTokenUsable(null, 1000), false);
  assert.equal(
    isAccessTokenUsable(
      {
        accessToken: "token",
        expiresAtMilliseconds: 30_000
      },
      1000
    ),
    false
  );
});

test("buildTokenState creates reusable token state from token payload", () => {
  const tokenState = buildTokenState(
    {
      access_token: "token",
      expires_in: 120
    },
    10_000
  );

  assert.deepEqual(tokenState, {
    accessToken: "token",
    expiresAtMilliseconds: 130_000
  });
  assert.equal(isAccessTokenUsable(tokenState, 20_000), true);
});
