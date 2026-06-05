# OCI Enterprise AI Deployment Guide

## Purpose

This document describes the first deployment procedure for running the OCI RAG Agent Blueprint as a Hosted Application in OCI Enterprise AI.

The guide is intentionally practical: it lists prerequisites, required OCI policies, and the main steps required to build the container image, store it in OCI Container Registry, and create a Hosted Deployment.

## Prerequisites

You need:

- An OCI tenancy with access to OCI Enterprise AI / OCI Generative AI.
- A target OCI compartment for the project resources.
- A selected OCI region.
- Docker installed locally.
- OCI CLI configured for the target tenancy and region.
- Permission to create and manage OCI Generative AI resources.
- Permission to create and manage the Object Storage bucket used for knowledge base file uploads.
- Permission to push container images to OCI Container Registry.

The OCI Generative AI documentation states that access to Generative AI resources is controlled through OCI IAM policies and that the aggregate `generative-ai-family` resource type can be used for broad access to Generative AI resources in a compartment or tenancy [[1]](https://docs.oracle.com/en-us/iaas/Content/generative-ai/iam-policies.htm).

For production deployments, prefer least-privilege policies over broad sandbox policies.

## Required IAM Policies

Replace:

- `<group-name>` with the OCI IAM group used by administrators or deployers.
- `<dynamic-group-name>` with the dynamic group for hosted applications and deployments.
- `<compartment-name>` with the target compartment name.
- `<compartment-ocid>` with the target compartment OCID.

### Broad Sandbox Policy

For a sandbox or proof-of-concept environment, the broad Generative AI family policy is the simplest option:

```text
allow group <group-name> to manage generative-ai-family in compartment <compartment-name>
```

This grants access to the family of OCI Generative AI resources. Oracle recommends broad family permissions only for administrators or sandbox groups [[1]](https://docs.oracle.com/en-us/iaas/Content/generative-ai/iam-policies.htm).

The `generative-ai-family` resource type includes, among others, projects, API keys, vector stores, hosted applications, hosted deployments, and containers [[1]](https://docs.oracle.com/en-us/iaas/Content/generative-ai/iam-policies.htm).

### Least-Privilege User Policies

For a tighter setup, grant only the resource types needed by this deployment flow:

```text
allow group <group-name> to manage generative-ai-project in compartment <compartment-name>
allow group <group-name> to manage generative-ai-apikey in compartment <compartment-name>
allow group <group-name> to manage generative-ai-vectorstore in compartment <compartment-name>
allow group <group-name> to manage generative-ai-vectorstore-file in compartment <compartment-name>
allow group <group-name> to manage generative-ai-vectorstore-connector in compartment <compartment-name>
allow group <group-name> to manage generative-ai-hosted-application in compartment <compartment-name>
allow group <group-name> to manage generative-ai-hosted-deployment in compartment <compartment-name>
allow group <group-name> to manage generative-ai-container in compartment <compartment-name>
```

Oracle documents separate resource types and API-level permissions for projects, vector stores, applications, deployments, and containers [[2]](https://docs.oracle.com/en-us/iaas/Content/generative-ai/project-permissions.htm) [[3]](https://docs.oracle.com/en-us/iaas/Content/generative-ai/vector-store-permissions.htm) [[4]](https://docs.oracle.com/en-us/iaas/Content/generative-ai/application-permissions.htm) [[5]](https://docs.oracle.com/en-us/iaas/Content/generative-ai/deployment-permissions.htm) [[6]](https://docs.oracle.com/en-us/iaas/Content/generative-ai/container-permissions.htm).

### API Key Permission

OCI Generative AI API keys are service-specific credential tokens used to authenticate requests to OCI Generative AI [[7]](https://docs.oracle.com/iaas/Content/generative-ai/api-keys.htm).

After creating an API key, OCI requires adding API key permissions [[8]](https://docs.oracle.com/en-us/iaas/Content/generative-ai/create-api-key.htm).

A broad API key authorization policy can be:

```text
allow any-user to use generative-ai-family in compartment <compartment-name>
where request.principal.type = 'generativeaiapikey'
```

Use a more restrictive policy when needed, for example by limiting access to a specific group, compartment, key, or model. Oracle documents that API key permissions can be customized by scope, granularity, model restrictions, and operation types [[9]](https://docs.oracle.com/en-us/iaas/Content/generative-ai/add-api-permission.htm).

### OCIR Push Policy For Users

The deploying user or group must be able to create and update OCI Container Registry repositories.

Example:

```text
allow group <group-name> to manage repos in compartment <compartment-name>
```

OCI Container Registry policies control repository access, including read and manage access for groups [[10]](https://docs.public.content.oci.oraclecloud.com/iaas/Content/Registry/Concepts/registrypolicyrepoaccess.htm).

### Object Storage Policy For Knowledge Base Uploads

The deploying user or group must be able to create and manage the Object Storage bucket used as the staging area for knowledge base documents.

Example:

```text
allow group <group-name> to manage object-family in compartment <compartment-name>
```

Use a narrower Object Storage policy for production deployments when the target bucket and operational model are known.

### Hosted Application Pull Policy

Hosted deployments use a Docker image artifact stored in OCIR. OCI documentation states that deployments select a container image and tag, and that deployments require IAM policies and dynamic groups for image access [[11]](https://docs.oracle.com/en-us/iaas/Content/generative-ai/deployments.htm).

Create a dynamic group for hosted applications and deployments. A broad matching rule is:

```text
any {
  resource.type = 'generativeaihostedapplication',
  resource.type = 'generativeaihosteddeployment'
}
```

For a compartment-scoped dynamic group, use compartment-specific matching rules:

```text
any {
  all {
    resource.type = 'generativeaihostedapplication',
    resource.compartment.id = '<compartment-ocid>'
  },
  all {
    resource.type = 'generativeaihosteddeployment',
    resource.compartment.id = '<compartment-ocid>'
  }
}
```

Grant the dynamic group permission to read the OCIR repository:

```text
allow dynamic-group <dynamic-group-name> to read repos in compartment <compartment-name>
```

Oracle documents that hosted applications and deployments need dynamic group permissions to read OCIR repositories and read vulnerability scan results before deployment [[12]](https://docs.oracle.com/en-us/iaas/Content/generative-ai/deploy-permissions.htm).

Grant access to vulnerability scan results:

```text
allow dynamic-group <dynamic-group-name> to read vulnerability-scanning-family in compartment <compartment-name>
```

If the hosted agent must access other OCI resources directly, add the corresponding policies. For example, if it needs Object Storage access:

```text
allow dynamic-group <dynamic-group-name> to read object-family in compartment <compartment-name>
```

## Region Consistency

The OCI Generative AI project, API key, vector store, Object Storage bucket, model endpoint, and hosted deployment must be created in the same OCI region.

This project builds the OpenAI-compatible OCI endpoint from `OCI_REGION`:

```text
https://inference.generativeai.<region>.oci.oraclecloud.com/openai/v1
```

The following runtime values must therefore refer to resources in the same region:

- `OCI_REGION`
- `OCI_PROJECT_ID`
- `OCI_MODEL_ID`
- `OCI_VECTOR_STORE_ID`
- `OPENAI_API_KEY`

## Deployment Steps

### 1. Create A Project In OCI Generative AI

Create an OCI Generative AI project in the selected compartment and region.

Record the project OCID. It will be used as:

```text
OCI_PROJECT_ID
```

### 2. Create An API Key

Create an OCI Generative AI API key in the same region and compartment used by the project.

After creating the key, add the required API key permission policy.

Store one of the generated key secrets securely. The hosted application will receive it as:

```text
OPENAI_API_KEY
```

Do not commit this value to source control.

### 3. Create A Vector Store

Create a vector store in the same region and compartment.

For a practical introduction to vector stores in OCI Enterprise AI, see [Fiest Steps with Vector Stores](https://luigi-saetta.medium.com/oci-enterprise-ai-first-steps-with-vector-stores-df074cb398cb).

Record the vector store identifier. It will be used as:

```text
OCI_VECTOR_STORE_ID
```

The project, API key, vector store, and Object Storage bucket are region-scoped and must belong to the same region used by the deployment.

### 4. Create An Object Storage Bucket

Create an Object Storage bucket in the same region and compartment.

This bucket is the staging location for the documents that must be loaded into the vector store.

Upload the knowledge base files to this bucket.

The file formats supported by this first guide are:

- PDF files (`.pdf`)
- Plain text files (`.txt`)
- Markdown files (`.md`)

### 5. Create A Data Sync Connector In The Vector Store

Create a Data Sync Connector in the vector store.

The connector links the Object Storage bucket to the vector store and enables synchronization between uploaded documentation files and the vector store knowledge base.

After uploading one or more files to the bucket, start a synchronization job.

The synchronization job can be started from the OCI Cloud Console or through an automation script.

### 6. Create The Docker Container

Build the backend container image from the repository root:

```bash
docker build -t oci-rag-agent-blueprint-agent:latest .
```

The container must satisfy these runtime constraints:

- It exposes HTTP on port `8080`.
- It starts the FastAPI app with `uvicorn`.
- It serves `GET /health`.
- It serves `POST /responses`.
- It supports Server-Sent Events for streaming responses.
- It receives all runtime configuration through environment variables.

Required environment variables:

| Variable | Description |
| --- | --- |
| `OCI_REGION` | OCI region used to build the OpenAI-compatible endpoint. |
| `OCI_COMPARTMENT_ID` | Target compartment OCID. |
| `OCI_PROJECT_ID` | OCI Generative AI project OCID. |
| `OCI_MODEL_ID` | Model identifier selected from the supported model catalog. |
| `OCI_VECTOR_STORE_ID` | Vector store identifier used by file search. |
| `OPENAI_API_KEY` | OCI Generative AI OpenAI-compatible API key secret. |

### 7. Store The Image In OCI Container Registry

Tag the image for OCIR.

Example:

```bash
docker tag oci-rag-agent-blueprint-agent:latest <region-key>.ocir.io/<tenancy-namespace>/<repo-name>:<tag>
```

Log in to OCIR and push the image:

```bash
docker login <region-key>.ocir.io
docker push <region-key>.ocir.io/<tenancy-namespace>/<repo-name>:<tag>
```

Use a non-floating tag for customer deployments, for example:

```text
0.1.0
```

### 8. Create And Configure The Hosted Application

Create a Hosted Application in OCI Enterprise AI / OCI Generative AI.

Applications define how a hosted Generative AI workload runs and how it is accessed. Oracle documents that application settings include scaling, managed storage and runtime variables, networking, and authentication settings [[13]](https://docs.oracle.com/en-us/iaas/Content/generative-ai/applications.htm).

Configure at least:

- Name and compartment.
- Scaling settings.
- Network access mode.
- Endpoint access mode.
- Authentication settings.
- Runtime environment variables.

Set the runtime variables listed in step 6.

For a public demo endpoint, use the platform public endpoint option. For an enterprise deployment, evaluate private endpoint and customer networking mode.

### 9. Create A Deployment In The Hosted Application

Create a deployment inside the hosted application and link it to the OCIR image.

Hosted deployments are versioned releases of an application. A deployment selects a container image and tag; activating it makes it the running version for the application [[11]](https://docs.oracle.com/en-us/iaas/Content/generative-ai/deployments.htm).

Use the image pushed in step 7:

```text
<region-key>.ocir.io/<tenancy-namespace>/<repo-name>:<tag>
```

Activate the deployment after creation.

Validate:

- The deployment reaches an active/running state.
- The application endpoint is available.
- `GET /health` returns success.
- `POST /responses` returns a JSON response.
- `POST /responses` with `stream=true` streams events.

## Open Topics

- Exact console screenshots and navigation paths.
- OCI CLI automation commands.
- Authentication setup using an identity domain.
- Private endpoint and customer networking mode.
- Runtime logs and observability.
