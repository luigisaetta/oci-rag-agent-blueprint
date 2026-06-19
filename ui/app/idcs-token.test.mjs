import assert from "node:assert/strict";
import test from "node:test";

import {
  buildTokenEndpointUrl,
  buildTokenRequestBody,
  normalizeTokenResponse,
  validateTokenRequestPayload
} from "./idcs-token.mjs";

test("buildTokenEndpointUrl builds OCI IAM OAuth token endpoint", () => {
  assert.equal(
    buildTokenEndpointUrl("https://idcs.example.com/"),
    "https://idcs.example.com/oauth2/v1/token"
  );
});

test("validateTokenRequestPayload returns field errors for missing values", () => {
  assert.deepEqual(validateTokenRequestPayload({}), {
    identity_domain_url: "This field is required.",
    client_id: "This field is required.",
    client_secret: "This field is required.",
    scope: "This field is required."
  });
});

test("validateTokenRequestPayload requires https Identity Domain URL", () => {
  assert.deepEqual(
    validateTokenRequestPayload({
      identity_domain_url: "http://idcs.example.com",
      client_id: "client",
      client_secret: "secret",
      scope: "audiencescope"
    }),
    {
      identity_domain_url: "Use an https:// Identity Domain URL."
    }
  );
});

test("buildTokenRequestBody encodes client credentials grant body", () => {
  assert.equal(
    buildTokenRequestBody(" audience/scope ").toString(),
    "grant_type=client_credentials&scope=audience%2Fscope"
  );
});

test("normalizeTokenResponse requires an access token and preserves expiry", () => {
  assert.deepEqual(
    normalizeTokenResponse({
      access_token: "token",
      expires_in: 120,
      token_type: "Bearer"
    }),
    {
      access_token: "token",
      expires_in: 120,
      token_type: "Bearer"
    }
  );
  assert.throws(
    () => normalizeTokenResponse({ expires_in: 120 }),
    /did not include access_token/u
  );
});
