# Document Loading

Use the management loader to upload local PDF, text, and Markdown documents to
the Object Storage bucket already associated with a Vector Store Data Sync
Connector, then trigger a manual connector file sync.

Example:

```bash
python -m management.load_documents \
  --directory ./knowledge-base \
  --namespace <object-storage-namespace> \
  --bucket <bucket-name> \
  --connector-id <vector-store-connector-ocid> \
  --prefix product-docs/
```

Use `--dry-run` to inspect the files and target object names before modifying
OCI resources. By default, existing objects are skipped; use `--overwrite` to
replace them.

The script uses the OCI SDK configuration from `~/.oci/config` by default. Use
`--profile` and `--config-file` when a non-default OCI profile or config file is
required.

## Agent-Managed Remote Ingestion

When the agent is deployed with `DOCUMENT_INGESTION_ENABLED=true`, clients can
submit documents through the agent instead of running the management loader on
an operator workstation.

The remote flow is:

1. The CLI uploads one or more files to `POST /documents/ingestions`.
2. The agent stores the files in the configured Object Storage bucket.
3. The agent starts one Vector Store Data Sync Connector file sync job.
4. The connector asynchronously loads the documents into the Vector Store.
5. The CLI can poll `GET /documents/ingestions/{job_id}` until the job reaches a
   terminal lifecycle state.

Example:

```bash
python -m clients.document_ingestion_cli \
  --base-url "http://localhost:8080" \
  submit \
  --file ./knowledge-base/guide.pdf \
  --file ./knowledge-base/faq.md \
  --prefix product-docs \
  --sync-display-name "manual-doc-ingestion" \
  --wait
```

For Hosted Applications, pass the invoke base URL up to `actions/invoke`:

```bash
python -m clients.document_ingestion_cli \
  --base-url "https://inference.generativeai.<region>.oci.oraclecloud.com/20251112/hostedApplications/<hosted-application-ocid>/actions/invoke" \
  submit \
  --file ./knowledge-base/guide.pdf \
  --wait
```

Read an existing job status:

```bash
python -m clients.document_ingestion_cli \
  --base-url "http://localhost:8080" \
  status "<connector-file-sync-job-id>"
```

For protected Hosted Applications, use the same `--auth`, `--env-file`, and
IDCS client environment variables documented for `clients.agent_cli`.
