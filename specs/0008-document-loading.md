# Document Loading

## Purpose

This specification defines the initial document loading approach for the OCI RAG Agent Blueprint knowledge base.

The goal is to load and update knowledge base documents by using OCI-native services, without adding custom ingestion code to the RAG agent.

## Scope

This document covers:

- Object Storage bucket creation for knowledge base documents.
- Vector Store Data Sync Connector creation.
- IAM policy requirements.
- Knowledge base update flow.
- Sync job execution options.

This document does not yet define:

- Automation scripts for creating buckets, connectors, or sync jobs.
- Detailed file lifecycle rules.
- Document chunking strategy.
- Multi-vector-store routing.
- Failure handling for sync jobs.
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

Automation scripts are planned for a future release and are currently TBD.

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
- After synchronization, the Vector Store can be used by the RAG agent through Responses API file search.
- No custom document loading code is required in the RAG agent.

## Open Topics

- Scripted creation of the Object Storage bucket.
- Scripted creation of the Data Sync Connector.
- Scripted execution of sync jobs.
- Document deletion and re-synchronization behavior.
- Sync job monitoring and failure diagnostics.
- Additional supported file formats.
