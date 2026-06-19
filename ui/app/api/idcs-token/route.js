import {
  buildTokenEndpointUrl,
  buildTokenRequestBody,
  normalizeTokenResponse,
  validateTokenRequestPayload
} from "../../idcs-token.mjs";

export async function POST(request) {
  let payload;

  try {
    payload = await request.json();
  } catch {
    return Response.json({ error: "Request body must be valid JSON." }, { status: 400 });
  }

  const fieldErrors = validateTokenRequestPayload(payload);
  if (Object.keys(fieldErrors).length > 0) {
    return Response.json(
      { error: "Missing or invalid IDCS token configuration.", field_errors: fieldErrors },
      { status: 400 }
    );
  }

  const credentials = Buffer.from(
    `${payload.client_id.trim()}:${payload.client_secret.trim()}`,
    "utf8"
  ).toString("base64");

  let tokenResponse;

  try {
    tokenResponse = await fetch(buildTokenEndpointUrl(payload.identity_domain_url), {
      method: "POST",
      headers: {
        Authorization: `Basic ${credentials}`,
        "Content-Type": "application/x-www-form-urlencoded",
        Accept: "application/json"
      },
      body: buildTokenRequestBody(payload.scope)
    });
  } catch (error) {
    return Response.json(
      { error: `Unable to reach IDCS token endpoint: ${error.message}` },
      { status: 502 }
    );
  }

  const responseText = await tokenResponse.text();
  let responsePayload;

  try {
    responsePayload = responseText ? JSON.parse(responseText) : {};
  } catch {
    return Response.json(
      { error: "IDCS token endpoint returned a non-JSON response." },
      { status: 502 }
    );
  }

  if (!tokenResponse.ok) {
    return Response.json(
      {
        error:
          responsePayload.error_description ||
          responsePayload.error ||
          `IDCS token request failed with HTTP ${tokenResponse.status}.`
      },
      { status: tokenResponse.status }
    );
  }

  try {
    return Response.json(normalizeTokenResponse(responsePayload));
  } catch (error) {
    return Response.json({ error: error.message }, { status: 502 });
  }
}
