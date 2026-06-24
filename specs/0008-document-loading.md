# Document Loading

## Purpose

This specification defines the initial document loading approach for the OCI RAG Agent Blueprint knowledge base.

The goal is to load and update knowledge base documents by using OCI-native services, without adding custom ingestion code to the RAG agent.

## Scope

This document covers:

- Object Storage bucket creation for knowledge base documents.
- Vector Store Data Sync Connector creation.
- Scripted upload of local documents to the configured Object Storage bucket.
- Scripted triggering of Vector Store Data Sync Connector file sync jobs.
- IAM policy requirements.
- Knowledge base update flow.
- Sync job execution options.

This document does not yet define:

- Automation scripts for creating buckets, connectors, or sync jobs.
- Detailed file lifecycle rules.
- Document chunking strategy.
- Multi-vector-store routing.
- Advanced failure handling for sync jobs.
- Observability for ingestion.

## Related Specifications

- [Architecture Guidelines](0001-architecture-guidelines.md)
- [Deployment](0004-deployment.md)
- [Security](0007-security.md)

## Loading Approach

The supported document loading approach for the first version is based on an OCI Object Storage bucket and a Vector Store Data Sync Connector.

The approach requires:

- A dedicated Object Storage bucket.
- A Data Sync Connector created inside the target Vector Store.
- The required IAM policies for Object Storage and OCI Enterprise AI / OCI Generative AI resources.

This approach is intentionally platform-based and does not require custom ingestion code in the project.

## Object Storage Bucket

A dedicated Object Storage bucket must be created for knowledge base document uploads.

The bucket is the staging area for documents that must be synchronized into the Vector Store.

Documents are added, updated, or removed by changing the files stored in this bucket.

The supported file formats for the initial version are:

- PDF files (`.pdf`)
- Plain text files (`.txt`)
- Markdown files (`.md`)

## Vector Store Data Sync Connector

A Data Sync Connector must be created inside the target Vector Store.

The connector links the Object Storage bucket to the Vector Store and enables synchronization between the bucket content and the Vector Store knowledge base.

The connector configuration must point to the dedicated Object Storage bucket used for document uploads.

## IAM Policies

The deployment must include the IAM policies required to:

- Create and manage the Object Storage bucket.
- Upload, update, and delete objects in the bucket.
- Create and manage the Vector Store.
- Create and manage the Vector Store Data Sync Connector.
- Run synchronization jobs when required.

Policy examples are documented in the OCI Enterprise AI deployment guide.

## Knowledge Base Update Flow

Knowledge base loading and updates must follow this flow:

1. Upload or update files in the dedicated Object Storage bucket.
2. Start a synchronization job for the Vector Store Data Sync Connector.
3. Wait for the synchronization job to complete.
4. Validate that the RAG agent can retrieve information from the updated Vector Store.

The synchronization job can be started from:

- The OCI Cloud Console, inside the Vector Store.
- A script or automation tool.

## Local Document Loader Script

A new Python command-line script must support loading additional knowledge base
documents from a local directory.

The script must:

- Read files recursively from a user-provided local directory.
- Include only supported document formats: `.pdf`, `.txt`, and `.md`.
- Ignore unsupported files by default and report how many files were ignored.
- Upload supported files to the already-created Object Storage bucket associated
  with the Vector Store Data Sync Connector.
- Preserve stable object names derived from paths relative to the input
  directory.
- Optionally support an object name prefix so multiple document collections can
  share the same bucket without name collisions.
- Trigger a manual Vector Store connector file sync after successful uploads.
- Print a clear summary containing uploaded, skipped, ignored, and failed file
  counts, the connector OCID, and the created file sync OCID.
- Return a non-zero exit code when uploads fail or the sync job cannot be
  created.

The script must not create the Object Storage bucket, Vector Store, or Data Sync
Connector. Those resources remain deployment prerequisites created manually,
through the Agent Factory, or through future provisioning automation.

### Command-Line Interface

The script must expose explicit command-line arguments instead of hard-coded
resource identifiers.

Required arguments:

- `--directory`: local directory containing documents to upload.
- `--namespace`: Object Storage namespace.
- `--bucket`: Object Storage bucket name.
- `--connector-id`: Vector Store Data Sync Connector OCID.

Optional arguments:

- `--prefix`: Object Storage object name prefix.
- `--profile`: OCI CLI configuration profile.
- `--config-file`: OCI configuration file path.
- `--sync-display-name`: display name for the manual sync job.
- `--dry-run`: print planned uploads and sync request without modifying OCI
  resources.
- `--overwrite`: upload files even when an object with the same name already
  exists.

Example:

```bash
python -m management.load_documents \
  --directory ./knowledge-base \
  --namespace frpj5kvxryk1 \
  --bucket rag-documents \
  --connector-id ocid1.generativeaivectorconnector.oc1.eu-frankfurt-1.example \
  --prefix product-docs/
```

### Upload Behavior

The script must use the OCI Python SDK Object Storage client to upload files.

For each supported file:

1. Compute the object name from the path relative to `--directory`.
2. Prepend `--prefix` when provided.
3. Normalize path separators to `/`.
4. Upload the file to Object Storage.

By default, if an object already exists with the same name, the script should
skip it and report it as skipped. When `--overwrite` is provided, the script
must replace the existing object.

The script must avoid loading entire large files into memory when a streaming or
file-handle upload is available from the OCI SDK.

### Sync Job Trigger

After all uploads complete successfully, the script must trigger a manual Vector
Store connector file sync by calling:

```python
client.create_vector_store_connector_file_sync(details)
```

The request details must use
`oci.generative_ai.models.CreateVectorStoreConnectorFileSyncDetails` with:

- `vector_store_connector_id` set to `--connector-id`.
- `display_name` set to `--sync-display-name` when provided, otherwise to a
  generated readable name.

The implementation should follow the approach demonstrated in
`agent_hub/connectors/trigger_file_sync.py`, where a
`CreateVectorStoreConnectorFileSyncDetails` object is submitted through the OCI
Generative AI client.

The script must print the returned file sync identifier, lifecycle state, and
trigger type when those fields are present in the OCI response.

### Configuration And Authentication

The script must use OCI SDK configuration compatible with the rest of this
project.

The first implementation may use user-based OCI configuration through
`~/.oci/config`, `--profile`, and `--config-file`.

The script must not require or read `OPENAI_API_KEY`, because document loading
uses OCI Object Storage and OCI Generative AI control-plane APIs, not the
OpenAI-compatible Responses API.

Future implementations may add Resource Principal authentication for running the
loader inside OCI.

### Error Handling

The script must validate inputs before modifying OCI resources:

- `--directory` must exist and must be a directory.
- The directory must contain at least one supported file unless `--dry-run` is
  used for inspection.
- `--namespace`, `--bucket`, and `--connector-id` must be non-empty strings.
- `--prefix`, when provided, must not start with `/`.

Upload errors must be reported with the local path and target object name.

The script must not trigger a sync job if one or more uploads fail.

If the sync job creation fails, the script must report the OCI error in an
actionable way and return a non-zero exit code.

### Unit Tests

Unit tests must cover:

- Supported and unsupported file discovery.
- Relative path to object name mapping.
- Prefix normalization.
- Dry-run behavior.
- Existing object skip behavior.
- Overwrite behavior.
- Successful sync trigger request construction.
- No sync trigger when uploads fail.
- CLI validation errors.

Tests must mock OCI SDK clients and must not require live OCI resources.

## Agent Responsibilities

The RAG agent does not load documents directly.

The RAG agent must use the configured Vector Store through the Responses API `file_search` tool.

Document ingestion, synchronization, and indexing are handled by OCI services through the Object Storage bucket and Data Sync Connector.

## Acceptance Criteria

- A dedicated Object Storage bucket exists for knowledge base document uploads.
- The target Vector Store has a Data Sync Connector linked to the bucket.
- IAM policies allow the required bucket, connector, and sync job operations.
- Documents can be uploaded or updated in the bucket.
- A sync job can be started manually from the OCI Cloud Console.
- Documents can be loaded from a local directory by using the scripted loader.
- The scripted loader uploads supported files to Object Storage and triggers a
  manual Vector Store connector file sync.
- The scripted loader supports dry-run mode and unit-tested OCI client mocking.
- After synchronization, the Vector Store can be used by the RAG agent through Responses API file search.
- No custom document loading code is required in the RAG agent.

## Open Topics

- Scripted creation of the Object Storage bucket.
- Scripted creation of the Data Sync Connector.
- Document deletion and re-synchronization behavior.
- Sync job monitoring and failure diagnostics.
- Additional supported file formats.
- Resource Principal authentication for the document loader.
