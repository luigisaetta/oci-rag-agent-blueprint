# Agent Factory Ready-To-Run Deployment Script

## Purpose

This specification defines a separate Agent Factory export feature that produces
a ready-to-run deployment script for users who want to execute the deployment
outside the web UI.

The feature must preserve the existing dry-run behavior. Dry runs remain
read-only preflight checks and may still show placeholders for identifiers that
cannot exist before resource creation.

## Scope

The ready-to-run script export must:

- Generate a Bash script intended primarily for Linux.
- Keep best-effort compatibility with macOS Bash.
- Use the same deployment inputs collected by Agent Factory.
- Embed non-secret deployment values in the generated script.
- Avoid embedding API keys, OCIR passwords, or confidential application secrets.
- Prompt for required secret values at execution time when environment variables
  are not already set.
- Make the Docker commands visible in the generated script.
- Make the OCI CLI commands visible in the generated script.
- Make the OCI CLI JSON artifact files visible in the generated script.
- Reuse existing Python logic for SDK-based foundation provisioning, OCI
  identifier extraction, endpoint derivation, and Hosted Application lookup.

The feature must not:

- Change the semantics of dry run.
- Reimplement OCI response parsing in Bash.
- Store or return plaintext secret values in API responses.
- Replace the existing live deployment workflow in the Agent Factory UI.

## Backend Requirements

The Agent Factory backend must expose an endpoint that accepts a normal
deployment payload and returns a shell script as `text/x-shellscript`.

The endpoint must validate the payload using the same validation rules as a
deployment run. The generated script must force `dry_run=false` before invoking
the live workflow.

The generated script must include:

- A Linux-first `#!/usr/bin/env bash` shebang.
- `set -euo pipefail`.
- A repository-root discovery mechanism based on `AGENT_FACTORY_REPO_ROOT` or
  the script location.
- A Python interpreter discovery mechanism that prefers `python3` and falls back
  to `python`.
- Temporary payload file creation using `mktemp`.
- Cleanup of temporary files on exit.
- Runtime secret collection through `OPENAI_API_KEY` and `OCIR_PASSWORD`
  environment variables, with interactive prompts when values are missing.
- Explicit Docker commands for image build, OCIR login, and image push.
- Explicit OCI CLI commands for OCIR repository creation or reuse, Hosted
  Application lookup and creation, Hosted Deployment creation, and Hosted
  Deployment readiness polling.
- Explicit JSON here-doc blocks for Hosted Application inbound authentication,
  Hosted Application networking, Hosted Application runtime environment, and
  Hosted Deployment active Docker artifact.
- Invocation of internal Python helper commands only for foundation provisioning,
  metadata extraction, Hosted Application lookup, OCID extraction, lifecycle
  state extraction, and endpoint URL derivation.

The Python helper runner must:

- Load the generated payload file when preparing resolved metadata.
- Replace secret markers with runtime environment values.
- Validate the resolved payload.
- Provision foundation resources through the existing resource managers.
- Build the final deployment metadata after resource provisioning resolves real
  identifiers.
- Extract Hosted Application and Hosted Deployment OCIDs from OCI CLI output
  using the already-tested Python extraction logic.
- Extract Hosted Deployment lifecycle state and endpoint URL from OCI CLI output
  using the existing Python logic.

The Python helper runner must not hide Docker or OCI CLI deployment operations
behind a single opaque command.

## UI Requirements

The Agent Factory UI must expose a separate action for downloading the
ready-to-run deployment script after a successful dry run.

The UI must clearly distinguish:

- The dry-run command plan, which remains a validation and review artifact.
- The ready-to-run deployment script, which creates OCI resources when executed.

The button text must not imply that dry run itself performs deployment.

## Acceptance Criteria

- Dry-run responses remain read-only and keep their current command plan output.
- A new script export action is available after a successful dry run.
- The generated script contains real non-secret deployment values.
- The generated script does not contain plaintext OpenAI API keys or OCIR
  passwords.
- The generated script displays the Docker commands used for deployment.
- The generated script displays the OCI CLI commands used for deployment.
- The generated script displays the JSON artifact files passed to OCI CLI.
- The generated script invokes Python project code instead of parsing OCI OCIDs
  in Bash.
- Existing OCI identifier extraction and placeholder replacement tests continue
  to cover the live execution path.
