"use client";

import { useEffect, useMemo, useState } from "react";

const CONFIGURED_BACKEND_URL = process.env.NEXT_PUBLIC_FACTORY_API_URL?.trim();
const DEFAULT_BACKEND_URL = CONFIGURED_BACKEND_URL || "http://localhost:8081/factory/deployments";
const LOCAL_BACKEND_URL = "http://localhost:8081/factory/deployments";
const OCIR_CREDENTIALS_STORAGE_KEY = "agentFactory.ocirCredentials.v1";

const INITIAL_FORM = {
  compartment: "",
  region: "eu-frankfurt-1",
  bucket_mode: "create",
  bucket_name: "",
  vector_store_mode: "create",
  vector_store_name: "",
  connector_mode: "create",
  connector_name: "",
  hosted_application_name: "",
  deployment_name: "",
  jwt_protection_enabled: false,
  identity_domain_compartment: "",
  identity_domain_url: "",
  auth_scope: "",
  auth_audience: "",
  confidential_application_id: "",
  confidential_application_secret: "",
  endpoint_visibility: "public",
  network_mode: "oracle_managed",
  genai_project: "",
  model_id: "openai.gpt-5.4",
  openai_api_key: "",
  file_search_max_num_results: 10,
  responses_timeout_seconds: 60,
  stream_finalization_mode: "never",
  langfuse_enabled: false,
  langfuse_base_url: "",
  langfuse_public_key: "",
  langfuse_secret_key: "",
  container_repository_name: "oci-rag-agent-blueprint-agent",
  container_image_tag: "",
  ocir_username: "",
  ocir_password: "",
  dry_run: true
};

const REGION_OPTIONS = [
  { value: "eu-frankfurt-1", label: "eu-frankfurt-1" },
  { value: "us-chicago-1", label: "us-chicago-1" }
];

const MODEL_OPTIONS = [
  { value: "openai.gpt-5.4", label: "GPT-5.4" },
  { value: "openai.gpt-5.5", label: "GPT-5.5" },
  { value: "google.gemini-2.5-pro", label: "Gemini 2.5 Pro" },
  { value: "openai.gpt-oss-120b", label: "OpenAI gpt-oss-120b" }
];

const REQUIRED_FIELDS = [
  "compartment",
  "region",
  "bucket_name",
  "vector_store_name",
  "hosted_application_name",
  "deployment_name",
  "genai_project",
  "model_id",
  "openai_api_key",
  "ocir_username",
  "ocir_password",
  "container_repository_name",
  "container_image_tag"
];

const AUTH_REQUIRED_FIELDS = [
  "identity_domain_compartment",
  "identity_domain_url",
  "auth_scope",
  "auth_audience"
];

const LANGFUSE_REQUIRED_FIELDS = [
  "langfuse_base_url",
  "langfuse_public_key",
  "langfuse_secret_key"
];

const ACTIVE_RUN_STATUSES = new Set(["running"]);

function Field({
  label,
  name,
  value,
  onChange,
  type = "text",
  error = "",
  disabled = false,
  min,
  max,
  autoComplete
}) {
  return (
    <label className="field">
      <span>{label}</span>
      <input
        name={name}
        value={value}
        type={type}
        disabled={disabled}
        min={min}
        max={max}
        autoComplete={autoComplete}
        onChange={onChange}
        aria-invalid={Boolean(error)}
      />
      {error ? <small>{error}</small> : null}
    </label>
  );
}

function SelectField({
  label,
  name,
  value,
  onChange,
  children,
  disabled = false,
  error = ""
}) {
  return (
    <label className="field">
      <span>{label}</span>
      <select
        name={name}
        value={value}
        disabled={disabled}
        onChange={onChange}
        aria-invalid={Boolean(error)}
      >
        {children}
      </select>
      {error ? <small>{error}</small> : null}
    </label>
  );
}

function SegmentedField({
  label,
  value,
  options,
  onChange,
  disabled = false,
  notice = ""
}) {
  return (
    <div className="segmentedField">
      <span>{label}</span>
      <div
        className="segmentedControl"
        role="group"
        aria-label={label}
        style={{ "--segment-count": options.length }}
      >
        {options.map((option) => (
          <button
            key={option.value}
            type="button"
            className={option.value === value ? "segmentButton active" : "segmentButton"}
            disabled={disabled || option.disabled}
            onClick={() => onChange(option.value)}
          >
            {option.label}
          </button>
        ))}
      </div>
      {notice ? <small>{notice}</small> : null}
    </div>
  );
}

function StepList({ steps }) {
  if (!steps?.length) {
    return (
      <div className="emptyPanel">
        <strong>No run yet</strong>
        <span>Submit a dry run or deployment to see the sequence.</span>
      </div>
    );
  }

  return (
    <ol className="stepList">
      {steps.map((step) => (
        <li key={step.step_id} className={`step ${step.status}`}>
          <div>
            <strong>{step.display_name}</strong>
            {step.command ? <code>{step.command.join(" ")}</code> : null}
            {step.error ? <span className="errorText">{step.error}</span> : null}
          </div>
          <span>{step.status}</span>
        </li>
      ))}
    </ol>
  );
}

function initialBackendUrl() {
  if (
    typeof window === "undefined" ||
    CONFIGURED_BACKEND_URL ||
    DEFAULT_BACKEND_URL !== LOCAL_BACKEND_URL
  ) {
    return DEFAULT_BACKEND_URL;
  }

  if (["localhost", "127.0.0.1"].includes(window.location.hostname)) {
    return DEFAULT_BACKEND_URL;
  }

  return `${window.location.protocol}//${window.location.hostname}:8081/factory/deployments`;
}

export default function Home() {
  const [backendUrl, setBackendUrl] = useState(initialBackendUrl);
  const [form, setForm] = useState(INITIAL_FORM);
  const [fieldErrors, setFieldErrors] = useState({});
  const [run, setRun] = useState(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isExportingDeploymentScript, setIsExportingDeploymentScript] = useState(false);
  const [isCheckingOcirLogin, setIsCheckingOcirLogin] = useState(false);
  const [isCheckingIdcsToken, setIsCheckingIdcsToken] = useState(false);
  const [ocirLoginCheck, setOcirLoginCheck] = useState(null);
  const [idcsTokenCheck, setIdcsTokenCheck] = useState(null);
  const [ocirCredentialStorage, setOcirCredentialStorage] = useState(null);
  const [errorMessage, setErrorMessage] = useState("");
  const isRunActive = ACTIVE_RUN_STATUSES.has(run?.status);

  const missingRequiredFields = useMemo(
    () => {
      let requiredFields = form.jwt_protection_enabled
        ? [...REQUIRED_FIELDS, ...AUTH_REQUIRED_FIELDS]
        : REQUIRED_FIELDS;
      if (form.langfuse_enabled) {
        requiredFields = [...requiredFields, ...LANGFUSE_REQUIRED_FIELDS];
      }

      return requiredFields.filter((fieldName) => {
        const value = form[fieldName];
        return typeof value !== "string" || value.trim().length === 0;
      });
    },
    [form]
  );

  const canSubmit =
    missingRequiredFields.length === 0 &&
    !isSubmitting &&
    !isRunActive;
  const canExportDeploymentScript =
    Boolean(run?.dry_run) &&
    run?.status === "succeeded" &&
    missingRequiredFields.length === 0 &&
    !isExportingDeploymentScript;
  const canCheckOcirLogin =
    Boolean(form.region?.trim()) &&
    Boolean(form.ocir_username?.trim()) &&
    Boolean(form.ocir_password?.trim()) &&
    !isCheckingOcirLogin;
  const canSaveOcirCredentials =
    Boolean(form.ocir_username?.trim()) && Boolean(form.ocir_password?.trim());
  const canValidateIdcsToken =
    form.jwt_protection_enabled &&
    Boolean(form.identity_domain_url?.trim()) &&
    Boolean(form.auth_scope?.trim()) &&
    Boolean(form.auth_audience?.trim()) &&
    Boolean(form.confidential_application_id?.trim()) &&
    Boolean(form.confidential_application_secret?.trim()) &&
    !isCheckingIdcsToken;

  useEffect(() => {
    if (!run?.deployment_run_id || !isRunActive) {
      return undefined;
    }

    let isCancelled = false;

    async function refreshRun() {
      try {
        const response = await fetch(deploymentStatusUrl(backendUrl, run.deployment_run_id));
        const payload = await response.json();

        if (!response.ok) {
          throw new Error(payload.detail ?? `Backend returned HTTP ${response.status}`);
        }

        if (!isCancelled) {
          setRun(payload);
          setErrorMessage("");
        }
      } catch (error) {
        if (!isCancelled) {
          setErrorMessage(error.message || "Unable to refresh Agent Factory run.");
        }
      }
    }

    refreshRun();
    const intervalId = window.setInterval(refreshRun, 1500);

    return () => {
      isCancelled = true;
      window.clearInterval(intervalId);
    };
  }, [backendUrl, isRunActive, run?.deployment_run_id]);

  function saveOcirCredentials() {
    if (!canSaveOcirCredentials) {
      return;
    }

    try {
      window.localStorage.setItem(
        OCIR_CREDENTIALS_STORAGE_KEY,
        JSON.stringify({
          ocir_username: form.ocir_username,
          ocir_password: form.ocir_password
        })
      );
      setOcirCredentialStorage({
        status: "succeeded",
        message: "OCIR credentials saved locally in this browser."
      });
    } catch (error) {
      setOcirCredentialStorage({
        status: "failed",
        message: error.message || "Unable to save OCIR credentials locally."
      });
    }
  }

  function loadOcirCredentials() {
    try {
      const storedCredentials = window.localStorage.getItem(OCIR_CREDENTIALS_STORAGE_KEY);
      if (!storedCredentials) {
        setOcirCredentialStorage({
          status: "failed",
          message: "No saved OCIR credentials were found in this browser."
        });
        return;
      }

      const parsedCredentials = JSON.parse(storedCredentials);
      setForm((currentForm) => ({
        ...currentForm,
        ocir_username: String(parsedCredentials.ocir_username ?? ""),
        ocir_password: String(parsedCredentials.ocir_password ?? "")
      }));
      setFieldErrors((currentErrors) => ({
        ...currentErrors,
        ocir_username: "",
        ocir_password: ""
      }));
      setOcirLoginCheck(null);
      setOcirCredentialStorage({
        status: "succeeded",
        message: "Saved OCIR credentials loaded."
      });
    } catch (error) {
      setOcirCredentialStorage({
        status: "failed",
        message: error.message || "Unable to load saved OCIR credentials."
      });
    }
  }

  function forgetOcirCredentials() {
    try {
      window.localStorage.removeItem(OCIR_CREDENTIALS_STORAGE_KEY);
      setOcirCredentialStorage({
        status: "succeeded",
        message: "Saved OCIR credentials removed from this browser."
      });
    } catch (error) {
      setOcirCredentialStorage({
        status: "failed",
        message: error.message || "Unable to remove saved OCIR credentials."
      });
    }
  }

  function updateField(event) {
    const { name, value, type, checked } = event.target;
    setForm((currentForm) => ({
      ...currentForm,
      [name]: type === "checkbox" ? checked : normalizeValue(name, value)
    }));
    setFieldErrors((currentErrors) => ({ ...currentErrors, [name]: "" }));
    if (["region", "ocir_username", "ocir_password"].includes(name)) {
      setOcirLoginCheck(null);
    }
    if (
      [
        "identity_domain_url",
        "auth_scope",
        "auth_audience",
        "confidential_application_id",
        "confidential_application_secret"
      ].includes(name)
    ) {
      setIdcsTokenCheck(null);
    }
  }

  function updateAuthenticationMode(mode) {
    setForm((currentForm) => ({
      ...currentForm,
      jwt_protection_enabled: mode === "auth"
    }));
    setFieldErrors((currentErrors) => ({
      ...currentErrors,
      jwt_protection_enabled: ""
    }));
    setIdcsTokenCheck(null);
  }

  function updateModeField(name, value) {
    setForm((currentForm) => ({
      ...currentForm,
      [name]: value
    }));
    setFieldErrors((currentErrors) => ({ ...currentErrors, [name]: "" }));
  }

  async function checkOcirLogin() {
    if (!canCheckOcirLogin) {
      return;
    }

    setIsCheckingOcirLogin(true);
    setOcirLoginCheck(null);

    try {
      const response = await fetch(ocirLoginCheckUrl(backendUrl), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          region: form.region,
          ocir_username: form.ocir_username,
          ocir_password: form.ocir_password
        })
      });
      const payload = await response.json();

      if (!response.ok) {
        setOcirLoginCheck({
          status: "failed",
          message: payload.error ?? `Backend returned HTTP ${response.status}`
        });
        return;
      }

      setOcirLoginCheck({
        status: "succeeded",
        message: payload.message ?? "OCIR Docker login succeeded."
      });
    } catch (error) {
      setOcirLoginCheck({
        status: "failed",
        message: withBackendEndpointHint(
          error.message || "Unable to check OCIR Docker login.",
          backendUrl
        )
      });
    } finally {
      setIsCheckingOcirLogin(false);
    }
  }

  async function checkIdcsToken() {
    if (!canValidateIdcsToken) {
      return;
    }

    setIsCheckingIdcsToken(true);
    setIdcsTokenCheck(null);

    try {
      const response = await fetch(idcsTokenCheckUrl(backendUrl), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          identity_domain_url: form.identity_domain_url,
          auth_scope: form.auth_scope,
          auth_audience: form.auth_audience,
          confidential_application_id: form.confidential_application_id,
          confidential_application_secret: form.confidential_application_secret
        })
      });
      const payload = await response.json();

      if (!response.ok) {
        setFieldErrors(payload.field_errors ?? {});
        setIdcsTokenCheck({
          status: "failed",
          message: payload.error ?? `Backend returned HTTP ${response.status}`
        });
        return;
      }

      setIdcsTokenCheck({
        status: "succeeded",
        message: payload.message ?? "IDCS token validation succeeded.",
        tokenRequestScope: payload.token_request_scope,
        jwtAudience: payload.jwt_audience,
        jwtScope: payload.jwt_scope,
        jwtExpiresAt: payload.jwt_expires_at
      });
    } catch (error) {
      setIdcsTokenCheck({
        status: "failed",
        message: withBackendEndpointHint(
          error.message || "Unable to validate IDCS token.",
          backendUrl
        )
      });
    } finally {
      setIsCheckingIdcsToken(false);
    }
  }

  async function submitFactoryRun(event) {
    event.preventDefault();

    if (!canSubmit) {
      return;
    }

    setIsSubmitting(true);
    setErrorMessage("");
    setFieldErrors({});

    try {
      const response = await fetch(backendUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(buildDeploymentPayload(form))
      });
      const payload = await response.json();

      if (!response.ok) {
        setFieldErrors(payload.field_errors ?? {});
        throw new Error(payload.error ?? `Backend returned HTTP ${response.status}`);
      }

      setRun(payload);
    } catch (error) {
      setErrorMessage(
        withBackendEndpointHint(
          error.message || "Unable to start Agent Factory run.",
          backendUrl
        )
      );
    } finally {
      setIsSubmitting(false);
    }
  }

  function saveCommands() {
    if (!run?.commands_text) {
      return;
    }

    const blob = new Blob([run.commands_text], { type: "text/x-shellscript" });
    const objectUrl = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = objectUrl;
    link.download = `agent-factory-${run.deployment_run_id}.sh`;
    link.click();
    URL.revokeObjectURL(objectUrl);
  }

  async function saveDeploymentScript() {
    if (!canExportDeploymentScript) {
      return;
    }

    setIsExportingDeploymentScript(true);
    setErrorMessage("");
    setFieldErrors({});

    try {
      const response = await fetch(deploymentScriptUrl(backendUrl), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(buildDeploymentPayload(form))
      });

      if (!response.ok) {
        const payload = await response.json();
        setFieldErrors(payload.field_errors ?? {});
        throw new Error(payload.error ?? `Backend returned HTTP ${response.status}`);
      }

      const scriptText = await response.text();
      const blob = new Blob([scriptText], { type: "text/x-shellscript" });
      const objectUrl = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = objectUrl;
      link.download = "agent-factory-ready-deploy.sh";
      link.click();
      URL.revokeObjectURL(objectUrl);
    } catch (error) {
      setErrorMessage(
        withBackendEndpointHint(
          error.message || "Unable to export deployment script.",
          backendUrl
        )
      );
    } finally {
      setIsExportingDeploymentScript(false);
    }
  }

  return (
    <main className="factoryShell">
      <aside className="sidebar">
        <div className="brand">
          <div className="mark">AF</div>
          <div>
            <h1>Agent Factory</h1>
            <p>OCI Enterprise AI deployment console</p>
          </div>
        </div>

        <label className="field">
          <span>Factory API endpoint</span>
          <input value={backendUrl} onChange={(event) => setBackendUrl(event.target.value)} />
        </label>

        <div className="modePanel">
          <span>Run mode</span>
          <label>
            <input
              name="dry_run"
              type="checkbox"
              checked={form.dry_run}
              onChange={updateField}
            />
            Dry run
          </label>
          <p>
            Dry run returns validation commands and writes nothing to OCI.
          </p>
        </div>

        <div className="modePanel">
          <span>OCIR login</span>
          <Field
            label="Username"
            name="ocir_username"
            value={form.ocir_username}
            onChange={updateField}
            error={fieldErrors.ocir_username}
          />
          <Field
            label="Password"
            name="ocir_password"
            type="password"
            value={form.ocir_password}
            onChange={updateField}
            error={fieldErrors.ocir_password}
            autoComplete="new-password"
          />
          <button
            className="secondaryAction"
            disabled={!canCheckOcirLogin}
            onClick={checkOcirLogin}
            type="button"
          >
            {isCheckingOcirLogin ? "Checking..." : "Check credentials"}
          </button>
          {ocirLoginCheck ? (
            <p className={`checkStatus ${ocirLoginCheck.status}`}>
              {ocirLoginCheck.message}
            </p>
          ) : null}
          <div className="actionRow">
            <button
              className="secondaryAction"
              disabled={!canSaveOcirCredentials}
              onClick={saveOcirCredentials}
              type="button"
            >
              Save locally
            </button>
            <button
              className="secondaryAction"
              onClick={loadOcirCredentials}
              type="button"
            >
              Load saved
            </button>
            <button
              className="secondaryAction"
              onClick={forgetOcirCredentials}
              type="button"
            >
              Forget
            </button>
          </div>
          {ocirCredentialStorage ? (
            <p className={`checkStatus ${ocirCredentialStorage.status}`}>
              {ocirCredentialStorage.message}
            </p>
          ) : null}
        </div>

        <div className="summaryPanel">
          <span>Readiness</span>
          <strong>
            {canSubmit ? "Ready" : "Missing inputs"}
          </strong>
          <p>
            {canSubmit
              ? "The request can be submitted."
              : `${missingRequiredFields.length} required fields are empty.`}
          </p>
        </div>
      </aside>

      <section className="workspace">
        <header className="topBar">
          <div>
            <p>Guided deployment</p>
            <h2>Create a RAG agent deployment</h2>
          </div>
          <button className="primaryAction" disabled={!canSubmit} onClick={submitFactoryRun}>
            {isSubmitting || isRunActive
              ? "Running"
              : form.dry_run
                ? "Run dry check"
                : "Start deployment"}
          </button>
        </header>

        {errorMessage ? <div className="errorBanner">{errorMessage}</div> : null}

        <div className="contentGrid">
          <form className="deploymentForm" onSubmit={submitFactoryRun}>
            <section className="formSection">
              <h3>OCI Target</h3>
              <div className="fieldGrid">
                <Field
                  label="Compartment name or OCID"
                  name="compartment"
                  value={form.compartment}
                  onChange={updateField}
                  error={fieldErrors.compartment}
                />
                <SelectField
                  label="Region"
                  name="region"
                  value={form.region}
                  onChange={updateField}
                  error={fieldErrors.region}
                >
                  {REGION_OPTIONS.map((region) => (
                    <option key={region.value} value={region.value}>
                      {region.label}
                    </option>
                  ))}
                </SelectField>
                <Field
                  label="GenAI project name or OCID"
                  name="genai_project"
                  value={form.genai_project}
                  onChange={updateField}
                  error={fieldErrors.genai_project}
                />
                <SelectField
                  label="Model"
                  name="model_id"
                  value={form.model_id}
                  onChange={updateField}
                  error={fieldErrors.model_id}
                >
                  {MODEL_OPTIONS.map((model) => (
                    <option key={model.value} value={model.value}>
                      {model.label}
                    </option>
                  ))}
                </SelectField>
              </div>
            </section>

            <section className="formSection">
              <h3>Knowledge Base</h3>
              <div className="fieldGrid">
                <SegmentedField
                  label="Bucket mode"
                  value={form.bucket_mode}
                  onChange={(value) => updateModeField("bucket_mode", value)}
                  options={[
                    { value: "create", label: "Create" },
                    { value: "reuse", label: "Reuse" }
                  ]}
                />
                <Field
                  label="Bucket name"
                  name="bucket_name"
                  value={form.bucket_name}
                  onChange={updateField}
                  error={fieldErrors.bucket_name}
                />
                <SegmentedField
                  label="Vector Store mode"
                  value={form.vector_store_mode}
                  onChange={(value) => updateModeField("vector_store_mode", value)}
                  options={[
                    { value: "create", label: "Create" },
                    { value: "reuse", label: "Reuse" }
                  ]}
                />
                <Field
                  label="Vector Store name or OCID"
                  name="vector_store_name"
                  value={form.vector_store_name}
                  onChange={updateField}
                  error={fieldErrors.vector_store_name}
                />
                <SegmentedField
                  label="Connector mode"
                  value={form.connector_mode}
                  onChange={(value) => updateModeField("connector_mode", value)}
                  options={[
                    { value: "create", label: "Create" },
                    { value: "reuse", label: "Reuse" },
                    { value: "skip", label: "Skip" }
                  ]}
                />
                <Field
                  label="Connector name"
                  name="connector_name"
                  value={form.connector_name}
                  onChange={updateField}
                  error={fieldErrors.connector_name}
                  disabled={form.connector_mode === "skip"}
                />
              </div>
            </section>

            <section className="formSection">
              <h3>Hosted Application</h3>
              <div className="fieldGrid">
                <Field
                  label="Hosted Application name"
                  name="hosted_application_name"
                  value={form.hosted_application_name}
                  onChange={updateField}
                  error={fieldErrors.hosted_application_name}
                />
                <Field
                  label="Deployment name"
                  name="deployment_name"
                  value={form.deployment_name}
                  onChange={updateField}
                  error={fieldErrors.deployment_name}
                />
                <SegmentedField
                  label="Authentication"
                  value={form.jwt_protection_enabled ? "auth" : "none"}
                  onChange={updateAuthenticationMode}
                  options={[
                    { value: "none", label: "No auth" },
                    { value: "auth", label: "Auth" }
                  ]}
                  notice={
                    form.jwt_protection_enabled
                      ? "Identity Domain settings will protect the Hosted Application."
                      : ""
                  }
                />
                <SegmentedField
                  label="Endpoint"
                  value={form.endpoint_visibility}
                  onChange={() => {}}
                  disabled
                  options={[
                    { value: "public", label: "Public" },
                    { value: "private", label: "Private" }
                  ]}
                />
                <SegmentedField
                  label="Network"
                  value={form.network_mode}
                  onChange={() => {}}
                  disabled
                  options={[
                    { value: "oracle_managed", label: "Oracle managed" },
                    { value: "custom", label: "Custom" }
                  ]}
                />
              </div>
              {form.jwt_protection_enabled ? (
                <div className="conditionalPanel">
                  <div>
                    <strong>Confidential application authentication</strong>
                    <p>
                      These values will link the Hosted Application to an
                      Identity Domain confidential application in the backend
                      implementation.
                    </p>
                  </div>
                  <div className="fieldGrid">
                    <Field
                      label="Identity Domain compartment name or OCID"
                      name="identity_domain_compartment"
                      value={form.identity_domain_compartment}
                      onChange={updateField}
                      error={fieldErrors.identity_domain_compartment}
                    />
                    <Field
                      label="Identity Domain URL"
                      name="identity_domain_url"
                      value={form.identity_domain_url}
                      onChange={updateField}
                      error={fieldErrors.identity_domain_url}
                    />
                    <Field
                      label="Scope claim"
                      name="auth_scope"
                      value={form.auth_scope}
                      onChange={updateField}
                      error={fieldErrors.auth_scope}
                    />
                    <Field
                      label="Audience claim"
                      name="auth_audience"
                      value={form.auth_audience}
                      onChange={updateField}
                      error={fieldErrors.auth_audience}
                    />
                    <Field
                      label="Confidential application client ID"
                      name="confidential_application_id"
                      value={form.confidential_application_id}
                      onChange={updateField}
                      error={fieldErrors.confidential_application_id}
                    />
                    <Field
                      label="Confidential application secret"
                      name="confidential_application_secret"
                      type="password"
                      value={form.confidential_application_secret}
                      onChange={updateField}
                      error={fieldErrors.confidential_application_secret}
                      autoComplete="new-password"
                    />
                  </div>
                  <button
                    className="secondaryAction"
                    disabled={!canValidateIdcsToken}
                    onClick={checkIdcsToken}
                    type="button"
                  >
                    {isCheckingIdcsToken ? "Validating..." : "Validate token"}
                  </button>
                  {idcsTokenCheck ? (
                    <div className={`checkStatus ${idcsTokenCheck.status}`}>
                      <p>{idcsTokenCheck.message}</p>
                      {idcsTokenCheck.status === "succeeded" ? (
                        <dl>
                          <dt>Token request scope</dt>
                          <dd>{idcsTokenCheck.tokenRequestScope}</dd>
                          <dt>JWT audience</dt>
                          <dd>{String(idcsTokenCheck.jwtAudience ?? "n/a")}</dd>
                          <dt>JWT scope</dt>
                          <dd>{String(idcsTokenCheck.jwtScope ?? "n/a")}</dd>
                          <dt>Expires at</dt>
                          <dd>{String(idcsTokenCheck.jwtExpiresAt ?? "n/a")}</dd>
                        </dl>
                      ) : null}
                    </div>
                  ) : null}
                  <p className="inlineNotice">
                    The Hosted Application auth config keeps audience and scope
                    as separate JWT claim expectations. The client token request
                    uses a concatenated IDCS_SCOPE value.
                  </p>
                </div>
              ) : null}
            </section>

            <section className="formSection">
              <h3>Runtime And Image</h3>
              <div className="fieldGrid">
                <Field
                  label="OpenAI-compatible API key"
                  name="openai_api_key"
                  value={form.openai_api_key}
                  type="password"
                  onChange={updateField}
                  error={fieldErrors.openai_api_key}
                  autoComplete="new-password"
                />
                <Field
                  label="Container repository"
                  name="container_repository_name"
                  value={form.container_repository_name}
                  onChange={updateField}
                  error={fieldErrors.container_repository_name}
                />
                <Field
                  label="Image tag"
                  name="container_image_tag"
                  value={form.container_image_tag}
                  onChange={updateField}
                  error={fieldErrors.container_image_tag}
                />
                <SelectField
                  label="Stream finalization"
                  name="stream_finalization_mode"
                  value={form.stream_finalization_mode}
                  onChange={updateField}
                >
                  <option value="never">Never</option>
                  <option value="auto">Auto</option>
                  <option value="always">Always</option>
                </SelectField>
                <Field
                  label="File search max results"
                  name="file_search_max_num_results"
                  value={form.file_search_max_num_results}
                  type="number"
                  min="1"
                  max="50"
                  onChange={updateField}
                  error={fieldErrors.file_search_max_num_results}
                />
                <Field
                  label="Responses timeout seconds"
                  name="responses_timeout_seconds"
                  value={form.responses_timeout_seconds}
                  type="number"
                  min="1"
                  max="300"
                  onChange={updateField}
                  error={fieldErrors.responses_timeout_seconds}
                />
              </div>
              <label className="toggleRow">
                <input
                  name="langfuse_enabled"
                  type="checkbox"
                  checked={form.langfuse_enabled}
                  onChange={updateField}
                />
                <span>Enable Langfuse observability</span>
              </label>
              {form.langfuse_enabled ? (
                <div className="fieldGrid">
                  <Field
                    label="Langfuse base URL"
                    name="langfuse_base_url"
                    value={form.langfuse_base_url}
                    onChange={updateField}
                    error={fieldErrors.langfuse_base_url}
                  />
                  <Field
                    label="Langfuse public key"
                    name="langfuse_public_key"
                    value={form.langfuse_public_key}
                    onChange={updateField}
                    error={fieldErrors.langfuse_public_key}
                    autoComplete="off"
                  />
                  <Field
                    label="Langfuse secret key"
                    name="langfuse_secret_key"
                    type="password"
                    value={form.langfuse_secret_key}
                    onChange={updateField}
                    error={fieldErrors.langfuse_secret_key}
                    autoComplete="new-password"
                  />
                </div>
              ) : null}
            </section>
          </form>

          <aside className="runPanel">
            <div className="panelHeader">
              <div>
                <span>Execution</span>
                <h3>{run ? run.status : "Not started"}</h3>
              </div>
              <div className="panelActions">
                <button
                  className="secondaryAction"
                  disabled={!run?.commands_text}
                  onClick={saveCommands}
                >
                  Save commands
                </button>
                <button
                  className="secondaryAction"
                  disabled={!canExportDeploymentScript}
                  onClick={saveDeploymentScript}
                >
                  {isExportingDeploymentScript ? "Exporting" : "Save deploy script"}
                </button>
              </div>
            </div>

            {run?.error ? <div className="errorBanner">{run.error}</div> : null}

            <StepList steps={run?.steps} />

            {run ? (
              <div className="outputPanel">
                <h3>Outputs</h3>
                <dl>
                  <dt>Run ID</dt>
                  <dd>{run.deployment_run_id}</dd>
                  <dt>Image</dt>
                  <dd>{run.outputs?.image_reference ?? "n/a"}</dd>
                  <dt>Endpoint</dt>
                  <dd>{run.outputs?.endpoint_url ?? "Pending real deployment"}</dd>
                  <dt>Hosted Application ID</dt>
                  <dd>{run.outputs?.hosted_application_id ?? "Pending real deployment"}</dd>
                  <dt>Hosted Deployment ID</dt>
                  <dd>{run.outputs?.hosted_deployment_id ?? "Pending real deployment"}</dd>
                  <dt>Invoke base URL</dt>
                  <dd>
                    {run.outputs?.hosted_application_invoke_url ??
                      "Pending real deployment"}
                  </dd>
                  <dt>Health URL</dt>
                  <dd>
                    {run.outputs?.hosted_application_health_url ??
                      "Pending real deployment"}
                  </dd>
                  <dt>Responses URL</dt>
                  <dd>
                    {run.outputs?.hosted_application_responses_url ??
                      "Pending real deployment"}
                  </dd>
                  <dt>Compartment ID</dt>
                  <dd>{run.outputs?.resolved_identifiers?.compartment_id ?? "n/a"}</dd>
                  <dt>GenAI Project ID</dt>
                  <dd>{run.outputs?.resolved_identifiers?.genai_project_id ?? "n/a"}</dd>
                  <dt>Vector Store ID</dt>
                  <dd>{run.outputs?.resolved_identifiers?.vector_store_id ?? "n/a"}</dd>
                </dl>
                <h3>Command script</h3>
                <textarea readOnly value={run.commands_text ?? ""} />
                {run.dry_run && run.status === "succeeded" ? (
                  <p className="inlineNotice">
                    The deploy script is separate from this dry-run plan and
                    creates OCI resources when executed.
                  </p>
                ) : null}
                {run.outputs?.runtime_environment ? (
                  <>
                    <h3>Runtime environment</h3>
                    <dl>
                      {Object.entries(run.outputs.runtime_environment).map(([name, value]) => (
                        <div key={name}>
                          <dt>{name}</dt>
                          <dd>{value}</dd>
                        </div>
                      ))}
                    </dl>
                  </>
                ) : null}
                {run.outputs?.dry_run_artifacts ? (
                  <>
                    <h3>Generated JSON artifacts</h3>
                    {Object.entries(run.outputs.dry_run_artifacts).map(
                      ([filename, artifact]) => (
                        <div className="artifactBlock" key={filename}>
                          <strong>{filename}</strong>
                          <pre>{JSON.stringify(artifact, null, 2)}</pre>
                        </div>
                      )
                    )}
                  </>
                ) : null}
              </div>
            ) : null}
          </aside>
        </div>
      </section>
    </main>
  );
}

function normalizeValue(name, value) {
  if (
    name === "file_search_max_num_results" ||
    name === "responses_timeout_seconds"
  ) {
    return Number.parseInt(value, 10);
  }

  return value;
}

function buildDeploymentPayload(form) {
  const deploymentPayload = { ...form };
  delete deploymentPayload.confidential_application_id;
  delete deploymentPayload.confidential_application_secret;

  return deploymentPayload;
}

function withBackendEndpointHint(message, backendUrl) {
  const hint =
    "Check the Factory API endpoint: it still looks like a local/default URL. " +
    "If the backend runs on another host, set this field to the reachable " +
    "backend IP address or hostname.";

  if (!usesLocalBackendEndpoint(backendUrl) || message.includes(hint)) {
    return message;
  }

  return `${message.replace(/[.。]*$/, "")}. ${hint}`;
}

function usesLocalBackendEndpoint(backendUrl) {
  try {
    const parsedUrl = new URL(backendUrl);
    return ["localhost", "127.0.0.1"].includes(parsedUrl.hostname);
  } catch {
    return backendUrl === DEFAULT_BACKEND_URL || backendUrl === LOCAL_BACKEND_URL;
  }
}

function deploymentStatusUrl(baseUrl, deploymentRunId) {
  return `${baseUrl.replace(/\/$/, "")}/${deploymentRunId}`;
}

function deploymentScriptUrl(baseUrl) {
  return `${baseUrl.replace(/\/factory\/deployments\/?$/, "")}/factory/deployment-script`;
}

function ocirLoginCheckUrl(baseUrl) {
  return `${baseUrl.replace(/\/factory\/deployments\/?$/, "")}/factory/ocir-login/check`;
}

function idcsTokenCheckUrl(baseUrl) {
  return `${baseUrl.replace(/\/factory\/deployments\/?$/, "")}/factory/idcs-token/check`;
}
