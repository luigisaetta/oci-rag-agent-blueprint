# Troubleshooting FAQ

This document collects recurring operational issues and the fastest known ways
to diagnose and resolve them.

## Agent Factory

### Hosted Application `/health` validation returns 404 after enabling IDCS auth

**Symptom**

Agent Factory creates the Hosted Application and deployment, but the final
`Validate deployed health endpoint` step fails with:

```text
urllib.error.HTTPError: HTTP Error 404: Not Found
```

This can happen when the deployment uses `IDCS_AUTH_CONFIG`.

**Cause**

The Hosted Application invoke gateway may return `404` when the IDCS inbound
authentication configuration does not match a valid Identity Domain. A common
cause is an incorrect Identity Domain URL or name in the authentication
settings.

**Fix**

Check the authentication fields submitted through Agent Factory:

- Confirm the Identity Domain name is correct.
- If you provide a full Identity Domain URL, confirm it is the exact reachable
  domain URL.
- If you provide only the Identity Domain name, Agent Factory builds the URL as
  `https://<identity-domain-name>.identity.oraclecloud.com`.
- Confirm the scope and audience match the confidential application
  configuration.

After correcting the IDCS values, rerun the deployment or update the Hosted
Application authentication configuration and validate `/health` again.

### Factory API URL points to `localhost` when Agent Factory runs on a remote server

**Symptom**

The Agent Factory UI opens in the browser, but dry runs, deployment starts, or
OCIR credential checks fail because the UI cannot reach the backend API.

**Cause**

The `Factory API endpoint` field in the upper-left sidebar is evaluated by the
browser, not by the remote server. If Agent Factory is running on a remote host,
`localhost` means the user's local workstation, not the remote server.

**Fix**

When Agent Factory runs on a remote server, the `Factory API endpoint` field
must use the remote host IP address or DNS name instead of `localhost`.

For example, use:

```text
http://<remote-host-ip>:8081/factory/deployments
```

or:

```text
http://<remote-host-domain>:8081/factory/deployments
```

Do not use:

```text
http://localhost:8081/factory/deployments
```

unless the browser is running on the same machine as the Agent Factory API.

**Checks**

- Confirm the Agent Factory API is running on the remote server.
- Confirm port `8081` is reachable from the workstation running the browser.
- Confirm the UI field includes `/factory/deployments` at the end of the URL.
- If the remote server is behind a firewall or cloud security list, allow
  inbound access to port `8081` from the client network.
