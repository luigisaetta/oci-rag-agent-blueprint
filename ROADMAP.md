# Possible Future Improvements

This document lists possible improvements for future versions of the OCI RAG
Agent Blueprint. Each item is intentionally written as a proposal, not as an
approved implementation specification.

## 1. Replace API Key Authentication With OCI Resource Principal

Status: partially implemented.

The current implementation uses an OpenAI-compatible API key to call the OCI
Enterprise AI Responses API. This is aligned with the authentication model used
by OpenAI API clients for the Responses API and keeps the first version simple
and portable.

The main disadvantage in this blueprint is operational security: the API key is
entered in the Agent Factory UI and then passed to the deployed container as a
runtime secret. The code avoids logging the key and the generated ready-to-run
script avoids embedding it, but the deployment workflow still requires handling
a plaintext key value during configuration.

OCI offers a stronger cloud-native alternative: use OCI Resource Principal so
the hosted runtime can authenticate through its OCI workload identity instead of
through a long-lived API key. With this model, the deployment would not need an
OpenAI-compatible API key value at all.

The agent runtime now supports this approach through `OCI_AUTH_MODE`.

Completed runtime work:

- `OCI_AUTH_MODE=openai_api_key` preserves the original API-key behavior.
- `OCI_AUTH_MODE=resource_principal` builds the Responses API client with an
  OCI-signed HTTP client from `oci-genai-auth`.
- `OCI_AUTH_MODE=config_file` supports local OCI config-file authentication.
- `OPENAI_API_KEY` is required only for `openai_api_key` mode.

Remaining deployment work:

1. Create an OCI Dynamic Group that matches the Hosted Applications and Hosted
   Deployments allowed to run this agent.
2. Create an IAM policy that allows that Dynamic Group to use OCI Generative AI
   resources in the target compartment.
3. Validate `OCI_AUTH_MODE=resource_principal` end to end on a Hosted
   Application in the target tenancy and region.
4. Update Agent Factory deployment flows so hosted deployments can choose
   Resource Principal mode without requiring `OPENAI_API_KEY`.

Example policy:

```text
allow dynamic-group hosted-agent-runtime-dg to use generative-ai-family in compartment AIApplications
```

The exact Dynamic Group matching rule must be validated against the current OCI
resource types exposed for OCI Generative AI Hosted Applications and Hosted
Deployments. Conceptually, the rule should include the hosted application and
hosted deployment runtime resources that are allowed to call OCI Generative AI.

This change would reduce secret handling, align the hosted agent with OCI IAM
least-privilege controls, and make access auditable through workload identity
rather than through an API key.
