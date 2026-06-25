# Agent-Managed Connector Ingestion

## Purpose

This specification defines server-side document ingestion orchestration for the
RAG agent while preserving the Vector Store Data Sync Connector as the only
component responsible for loading documents into the Vector Store.

The goal is to let clients submit documents to the agent, have the agent upload
those documents to the configured Object Storage bucket, and then start an
asynchronous connector file sync job. The agent must also expose a separate
status endpoint for reading the connector job state.

## Scope

This specification covers:

- A server-side document ingestion submission endpoint.
- A server-side connector ingestion status endpoint.
- Synchronous document upload to OCI Object Storage.
- Asynchronous Vector Store Data Sync Connector file sync triggering.
- Runtime configuration required by the agent.
- Request and response behavior.
- Validation, security, logging, and error handling expectations.
- Unit test expectations.

This specification does not cover:

- Creating Object Storage buckets.
- Creating Vector Stores.
- Creating Vector Store Data Sync Connectors.
- Implementing custom parsing, chunking, embedding, or Vector Store writes in
  the agent.
- Replacing the existing local management document loader.
- Client UI design for document upload and job status display.
- Advanced job history persistence beyond returning connector job identifiers.

## Related Specifications

- [Architecture Guidelines](0001-architecture-guidelines.md)
- [Agent Implementation](0003-agent-implementation.md)
- [Deployment](0004-deployment.md)
- [Security](0007-security.md)
- [Document Loading](0008-document-loading.md)
- [Agent Factory](0010-agent-factory.md)

## Design Principle

The agent must orchestrate ingestion, not duplicate ingestion logic.

The agent must not parse documents for knowledge extraction, split documents
into chunks, generate embeddings, or write vectors directly to the Vector Store.
Those responsibilities remain owned by the OCI Vector Store Data Sync Connector.

The agent-managed flow must reuse the same platform ingestion model defined in
[Document Loading](0008-document-loading.md):

1. Store documents in an OCI Object Storage bucket.
2. Trigger a Vector Store Data Sync Connector file sync job.
3. Let the connector asynchronously load the documents into the Vector Store.

## HTTP Endpoints

The agent must expose two additional endpoints.

### Submit Connector Ingestion

```http
POST /documents/ingestions
```

The endpoint must accept one or more uploaded documents, upload supported files
to the configured Object Storage bucket, and start a connector file sync job
after all required uploads succeed.

The endpoint must return only the submission result. It must not wait for the
connector job to finish loading documents into the Vector Store.

### Read Connector Ingestion Status

```http
GET /documents/ingestions/{job_id}
```

The endpoint must read the current state of the connector file sync job
identified by `job_id`.

The endpoint must not infer completion from uploaded objects or Vector Store
query behavior. The source of truth for job status is the OCI connector file
sync resource.

## Submission Request

The first implementation must use `multipart/form-data` because clients need to
send document files to the agent.

Required form fields:

- `files`: one or more document files.

Optional form fields:

- `prefix`: Object Storage object name prefix for the uploaded documents.
- `sync_display_name`: display name for the connector file sync job.
- `overwrite`: boolean flag that allows replacing existing Object Storage
  objects. The default must be `false`.

The supported document formats must match the local document loading
specification:

- PDF files (`.pdf`)
- Plain text files (`.txt`)
- Markdown files (`.md`)

Unsupported files must be rejected before any connector file sync job is
created. The implementation may either reject the whole request when any file is
unsupported or skip unsupported files only when an explicit future request flag
allows that behavior. The initial endpoint must reject the whole request to keep
the API predictable.

## Submission Behavior

For each accepted uploaded file, the agent must:

1. Validate the original filename.
2. Validate the supported extension.
3. Compute a stable Object Storage object name.
4. Prepend `prefix` when provided.
5. Normalize object name path separators to `/`.
6. Upload the file to the configured Object Storage bucket.

After all uploads complete successfully, the agent must trigger a manual Vector
Store connector file sync by calling:

```python
client.create_vector_store_connector_file_sync(details)
```

The request details must use
`oci.generative_ai.models.CreateVectorStoreConnectorFileSyncDetails` with:

- `vector_store_connector_id` set to the configured connector OCID.
- `display_name` set to `sync_display_name` when provided, otherwise to a
  generated readable name.

The endpoint must not create a connector job if one or more required uploads
fail.

The endpoint must return a non-2xx response if upload succeeds but connector
job creation fails. The response must include the uploaded object names so an
operator can decide whether to retry job creation or remove staged objects.

## Object Name Rules

Object names must be deterministic and safe for Object Storage.

The implementation must:

- Use the uploaded filename as the default relative path.
- Remove leading path separators.
- Normalize path separators to `/`.
- Reject filenames that are empty after normalization.
- Reject filenames that contain path traversal segments such as `..`.
- Reject `prefix` values that start with `/`.
- Normalize `prefix` so that a non-empty prefix ends with exactly one `/`.

If multiple files in the same request map to the same object name, the request
must fail before uploads begin.

When `overwrite=false`, the agent must not replace an existing Object Storage
object. Existing objects must be reported as skipped or rejected before the
connector job is created. The initial endpoint must reject the request when any
target object already exists, because connector jobs should correspond to a
clear upload set.

When `overwrite=true`, the agent may replace existing objects.

## Submission Response

A successful submission must return a JSON response.

Example:

```json
{
  "status": "submitted",
  "job_id": "ocid1.generativeaivectorconnectorfilesync.oc1.eu-frankfurt-1.example",
  "connector_id": "ocid1.generativeaivectorconnector.oc1.eu-frankfurt-1.example",
  "bucket": "rag-documents",
  "namespace": "frpj5kvxryk1",
  "uploaded_objects": [
    "product-docs/guide.pdf",
    "product-docs/faq.md"
  ],
  "job_lifecycle_state": "ACCEPTED"
}
```

The response must include:

- `status`: `submitted`.
- `job_id`: connector file sync job OCID.
- `connector_id`: configured connector OCID.
- `namespace`: Object Storage namespace.
- `bucket`: Object Storage bucket name.
- `uploaded_objects`: uploaded Object Storage object names.
- `job_lifecycle_state`: lifecycle state returned by OCI when available.

The response may include additional OCI connector job fields when they are safe
and useful, such as trigger type, display name, time created, or lifecycle
details.

## Status Response

A successful status request must return a JSON response.

Example:

```json
{
  "job_id": "ocid1.generativeaivectorconnectorfilesync.oc1.eu-frankfurt-1.example",
  "connector_id": "ocid1.generativeaivectorconnector.oc1.eu-frankfurt-1.example",
  "lifecycle_state": "SUCCEEDED",
  "display_name": "Manual document ingestion 2026-06-25 14:30:00",
  "time_created": "2026-06-25T12:30:00Z",
  "time_updated": "2026-06-25T12:35:00Z",
  "lifecycle_details": null
}
```

The implementation must preserve OCI lifecycle state values instead of mapping
them to project-specific state names. Clients may map those values for display.

The status endpoint must return `404` when the job cannot be found and must
return a non-2xx operational error when OCI status retrieval fails for another
reason.

## Runtime Configuration

The feature must be configured only through agent runtime environment variables.

Required variables when the endpoints are enabled:

| Variable | Description |
| --- | --- |
| `OCI_DOCUMENT_NAMESPACE` | Object Storage namespace used for staged document uploads. |
| `OCI_DOCUMENT_BUCKET` | Object Storage bucket used by the Vector Store Data Sync Connector. |
| `OCI_VECTOR_STORE_CONNECTOR_ID` | Vector Store Data Sync Connector OCID used for manual file sync jobs. |

Optional variables:

| Variable | Default | Description |
| --- | --- | --- |
| `DOCUMENT_INGESTION_ENABLED` | `false` | Enables the agent-managed connector ingestion endpoints. |
| `DOCUMENT_INGESTION_DEFAULT_PREFIX` | Empty | Default object name prefix applied when the request does not provide `prefix`. |
| `DOCUMENT_INGESTION_MAX_FILES` | `10` | Maximum files accepted in one submission request. |
| `DOCUMENT_INGESTION_MAX_FILE_SIZE_MB` | `25` | Maximum accepted size for each uploaded file. |
| `OCI_AUTH_MODE` | `openai_api_key` | General OCI authentication mode used by the agent. Document ingestion requires `resource_principal` or `config_file`. |
| `OCI_CONFIG_FILE` | SDK default | OCI config file path used only when `OCI_AUTH_MODE=config_file`. |
| `OCI_PROFILE` | `DEFAULT` | OCI config profile used only when `OCI_AUTH_MODE=config_file`. |

The endpoints must be disabled by default. When
`DOCUMENT_INGESTION_ENABLED=false`, the agent must return `404` for these
endpoints or avoid registering them.

When `DOCUMENT_INGESTION_ENABLED=true`, missing required variables must fail
configuration loading before uploads or connector calls are attempted.

## Authentication And Authorization

When the deployed agent is protected by platform-level JWT authentication, both
document ingestion endpoints must be protected in the same way as `/responses`
and `/config/environment`.

The endpoints must not accept OCI credentials in request payloads, query
parameters, or headers. OCI authentication must come from the configured agent
runtime environment and deployment identity.

The implementation must use the general `OCI_AUTH_MODE` runtime setting rather
than a document-specific authentication switch.

The accepted values are:

- `openai_api_key`: authenticates Responses API calls with the
  OpenAI-compatible API key. This mode cannot authenticate Object Storage uploads
  or connector control-plane calls.
- `resource_principal`: authenticates Responses API calls, Object Storage
  uploads, and connector control-plane calls with OCI Resource Principal
  identity.
- `config_file`: authenticates Responses API calls, Object Storage uploads, and
  connector control-plane calls from local OCI configuration.

Document ingestion must fail fast when `DOCUMENT_INGESTION_ENABLED=true` and
`OCI_AUTH_MODE=openai_api_key`, because the OpenAI-compatible API key does not
authorize Object Storage or connector file sync operations.

The first implementation must support two OCI authentication modes for Object
Storage uploads and Vector Store Data Sync Connector control-plane calls:

- `resource_principal`: the default mode for OCI Enterprise AI Hosted
  Applications and other OCI runtimes that expose a Resource Principal signer.
- `config_file`: a local development mode that loads OCI SDK configuration from
  `OCI_CONFIG_FILE` and `OCI_PROFILE`, or from the SDK defaults when
  `OCI_CONFIG_FILE` is omitted.

When `OCI_AUTH_MODE=resource_principal`, the implementation must build
OCI SDK clients with `oci.auth.signers.get_resource_principals_signer()` and
must not read user OCI private keys from `~/.oci/config`.

When `OCI_AUTH_MODE=config_file`, the implementation may use the same
OCI SDK configuration approach as the existing management loader for local
development.

Hosted deployments must use `resource_principal` unless there is an explicit,
reviewed reason to use another supported authentication mode.

The runtime identity used by Resource Principal authentication must have IAM
permissions to:

- Put and inspect objects in the configured Object Storage bucket.
- Create Vector Store Data Sync Connector file sync jobs for the configured
  connector.
- Read Vector Store Data Sync Connector file sync job status.

## Logging And Secret Handling

Logs may include:

- Request correlation identifiers.
- Uploaded object names.
- File counts.
- Connector OCIDs.
- Connector file sync job OCIDs.
- OCI lifecycle states.

Logs must not include:

- File contents.
- Authorization headers.
- OCI configuration file contents.
- API keys, tokens, passwords, private keys, or client secrets.

Error responses must be actionable but must not expose secrets or complete
stack traces.

## Error Handling

The submission endpoint must validate request inputs before modifying OCI
resources.

Validation errors must return `400`.

Examples include:

- No files provided.
- Too many files.
- Empty filename.
- Unsupported file extension.
- Path traversal in filename.
- Invalid prefix.
- Duplicate object names in the same request.
- File larger than the configured maximum size.

Existing target objects with `overwrite=false` must return `409`.

Upload failures must return a non-2xx response that identifies the failed file
and target object name.

Connector job creation failures must return a non-2xx response that identifies
the connector id and any object names already uploaded by the request.

The status endpoint must validate `job_id` before calling OCI. Empty or clearly
invalid values must return `400`.

## Relationship To Local Management Loader

The server-side implementation should reuse extraction-free helper logic from
the existing local loader where practical, especially:

- Supported extension checks.
- Prefix normalization.
- Object name construction.
- Connector file sync request construction.

Shared logic should live in a small module that can be used by both the
management command and the agent endpoints without making the management command
depend on FastAPI.

The local loader must remain available for operator-driven bulk loading from a
local directory.

## Unit Tests

Unit tests must cover:

- Feature-disabled endpoint behavior.
- Runtime configuration validation.
- Multipart request validation.
- Supported and unsupported file handling.
- Filename and prefix normalization.
- Duplicate object name rejection.
- Existing object rejection when `overwrite=false`.
- Existing object replacement when `overwrite=true`.
- Successful Object Storage upload request construction.
- No connector job creation when upload fails.
- Successful connector file sync job creation.
- Submission response construction.
- Status request validation.
- Successful status response construction.
- OCI not-found handling for job status.
- Secret redaction in errors and logs where applicable.

Tests must mock OCI SDK clients and must not require live OCI resources.
