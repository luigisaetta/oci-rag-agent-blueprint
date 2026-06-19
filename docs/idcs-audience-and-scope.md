# OCI IAM IDCS Audience And Scope

This note explains one of the most important authentication details for OCI
Enterprise AI Hosted Applications protected with `IDCS_AUTH_CONFIG`.

The short version is:

- Hosted Application auth config must keep audience and scope separate.
- OAuth token requests to OCI IAM Identity Domains must combine audience and
  scope in the requested `scope` parameter.

Getting this wrong usually produces a token successfully, but the Hosted
Application rejects the request with `HTTP 403 insufficient_scope`.

## Two Different Places Use Similar Words

There are two different authentication steps:

1. Configure the Hosted Application gateway.
2. Ask OCI IAM Identity Domains for a client credentials access token.

Both steps talk about "scope", but they do not use the same representation.

## Hosted Application Configuration

The Hosted Application inbound auth config describes the JWT claims that the
gateway must accept.

For example, if the protected resource uses:

```text
Primary audience: hello_world
Scope: invoke
```

the Hosted Application inbound auth config must contain separate values:

```json
{
  "inboundAuthConfigType": "IDCS_AUTH_CONFIG",
  "idcsConfig": {
    "domainUrl": "https://idcs-example.identity.oraclecloud.com",
    "audience": "hello_world",
    "scope": "invoke"
  }
}
```

The Hosted Application must not use the concatenated value
`hello_worldinvoke` as `idcsConfig.scope`.

Why: the Hosted Application gateway validates the decoded JWT claims. The token
issued by OCI IAM contains separate claim values:

```json
{
  "aud": "hello_world",
  "scope": "invoke"
}
```

Therefore the Hosted Application must expect `audience=hello_world` and
`scope=invoke`.

## OAuth Token Request

When a client requests a token from OCI IAM Identity Domains with the client
credentials flow, the request uses the OAuth `scope` form parameter.

For the same example, the token request must use the concatenated value:

```text
scope=hello_worldinvoke
```

The request shape is:

```http
POST <IDENTITY_DOMAIN_URL>/oauth2/v1/token
Authorization: Basic base64(CONFIDENTIAL_APPLICATION_ID:CONFIDENTIAL_APPLICATION_SECRET)
Content-Type: application/x-www-form-urlencoded

grant_type=client_credentials&scope=hello_worldinvoke
```

OCI IAM interprets this requested OAuth scope as "resource audience
`hello_world`, permission scope `invoke`". The access token it returns then
contains the values as separate JWT claims:

```json
{
  "aud": "hello_world",
  "scope": "invoke"
}
```

This means the client `.env` should contain the concatenated value:

```text
IDENTITY_DOMAIN_URL=https://idcs-example.identity.oraclecloud.com
CONFIDENTIAL_APPLICATION_ID=<confidential-application-client-id>
CONFIDENTIAL_APPLICATION_SECRET=<confidential-application-secret>
IDCS_SCOPE=hello_worldinvoke
```

## Practical Rule

Use this mapping:

| Place | Audience Value | Scope Value |
| --- | --- | --- |
| Hosted Application `idcsConfig` | `hello_world` | `invoke` |
| Client `.env` token request | Not a separate field | `hello_worldinvoke` |
| Decoded JWT token | `aud=hello_world` | `scope=invoke` |

So the rule is:

```text
Hosted Application:
  audience = primary audience
  scope    = scope claim

Client token request:
  IDCS_SCOPE = primary audience + scope claim
```

There is no separator in the client token request value unless the audience or
scope values themselves contain one.

## Why This Is Easy To Confuse

The token request parameter is also named `scope`, but OCI IAM uses it to encode
both the target resource and the requested permission. After OCI IAM validates
the request, it emits a JWT where those concepts are split back into separate
claims.

The Hosted Application does not validate the raw OAuth request parameter. It
validates the JWT claims after the token has been issued.

That is why the concatenated value belongs in the client token request, not in
the Hosted Application `idcsConfig.scope`.

## Troubleshooting

If the client obtains a token but the Hosted Application returns:

```text
HTTP 403: insufficient_scope
```

check the required scope in the error message. For example:

```text
insufficient_scope: required scope="hello_worldinvoke"
```

This usually means the Hosted Application was configured with the concatenated
token-request scope. In that case, update the Hosted Application auth config so
that:

```text
audience = hello_world
scope    = invoke
```

Keep the client `.env` as:

```text
IDCS_SCOPE=hello_worldinvoke
```

Then request a new token and retry the Hosted Application call.

## How To Inspect The Token

Protected Hosted Application testing requires an OCI IAM Identity Domains
confidential application configured before using Agent Factory, the Python CLI,
or the reference UI. The confidential application must allow the OAuth
`Client credentials` grant and provide the Client ID and Client secret used by
the token request. Oracle documents the setup in
[Adding a Confidential Application](https://docs.oracle.com/en-us/iaas/Content/Identity/applications/add-confidential-application.htm).

In Agent Factory, enable authentication, fill in the Identity Domain URL,
audience claim, scope claim, confidential application client ID, and
confidential application secret, then select `Validate token`. The check requests
an access token, decodes the JWT, and verifies that:

```text
JWT aud   = Hosted Application audience claim
JWT scope = Hosted Application scope claim
```

The UI shows the computed token request scope, decoded audience, decoded scope,
and expiration timestamp. It never displays the access token or confidential
application secret.

Use the standalone token client:

```bash
python -m clients.idcs_token_client
```

It prints the raw token and decodes the JWT header and payload. In a correct
configuration, verify that the payload contains the expected separate claims:

```json
{
  "aud": "hello_world",
  "scope": "invoke"
}
```

Do not copy the concatenated `IDCS_SCOPE` value into the Hosted Application
`scope` field unless the decoded JWT really contains that exact value as the
`scope` claim.
