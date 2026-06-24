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
