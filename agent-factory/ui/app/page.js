"use client";

import { useEffect, useMemo, useState } from "react";

const DEFAULT_BACKEND_URL =
  process.env.NEXT_PUBLIC_FACTORY_API_URL ?? "http://localhost:8081/factory/deployments";
const LOCAL_BACKEND_URL = "http://localhost:8081/factory/deployments";

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
  endpoint_visibility: "public",
  network_mode: "oracle_managed",
  genai_project: "",
  model_id: "openai.gpt-5.4",
  openai_api_key: "",
  file_search_max_num_results: 10,
  responses_timeout_seconds: 60,
  stream_finalization_mode: "never",
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
    process.env.NEXT_PUBLIC_FACTORY_API_URL ||
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
  const [errorMessage, setErrorMessage] = useState("");
  const isRunActive = ACTIVE_RUN_STATUSES.has(run?.status);

  const missingRequiredFields = useMemo(
    () =>
      REQUIRED_FIELDS.filter((fieldName) => {
        const value = form[fieldName];
        return typeof value !== "string" || value.trim().length === 0;
      }),
    [form]
  );

  const canSubmit = missingRequiredFields.length === 0 && !isSubmitting && !isRunActive;

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

  function updateField(event) {
    const { name, value, type, checked } = event.target;
    setForm((currentForm) => ({
      ...currentForm,
      [name]: type === "checkbox" ? checked : normalizeValue(name, value)
    }));
    setFieldErrors((currentErrors) => ({ ...currentErrors, [name]: "" }));
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
        body: JSON.stringify(form)
      });
      const payload = await response.json();

      if (!response.ok) {
        setFieldErrors(payload.field_errors ?? {});
        throw new Error(payload.error ?? `Backend returned HTTP ${response.status}`);
      }

      setRun(payload);
    } catch (error) {
      setErrorMessage(error.message || "Unable to start Agent Factory run.");
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
        </div>

        <div className="summaryPanel">
          <span>Readiness</span>
          <strong>{canSubmit ? "Ready" : "Missing inputs"}</strong>
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
                <SelectField
                  label="Bucket mode"
                  name="bucket_mode"
                  value={form.bucket_mode}
                  onChange={updateField}
                >
                  <option value="create">Create</option>
                  <option value="reuse">Reuse</option>
                </SelectField>
                <Field
                  label="Bucket name"
                  name="bucket_name"
                  value={form.bucket_name}
                  onChange={updateField}
                  error={fieldErrors.bucket_name}
                />
                <SelectField
                  label="Vector Store mode"
                  name="vector_store_mode"
                  value={form.vector_store_mode}
                  onChange={updateField}
                >
                  <option value="create">Create</option>
                  <option value="reuse">Reuse</option>
                </SelectField>
                <Field
                  label="Vector Store name or OCID"
                  name="vector_store_name"
                  value={form.vector_store_name}
                  onChange={updateField}
                  error={fieldErrors.vector_store_name}
                />
                <SelectField
                  label="Connector mode"
                  name="connector_mode"
                  value={form.connector_mode}
                  onChange={updateField}
                >
                  <option value="create">Create</option>
                  <option value="reuse">Reuse</option>
                  <option value="skip">Skip</option>
                </SelectField>
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
                <SelectField
                  label="JWT protection"
                  name="jwt_protection_enabled"
                  value="false"
                  onChange={updateField}
                  disabled
                >
                  <option value="false">No</option>
                </SelectField>
                <SelectField
                  label="Endpoint"
                  name="endpoint_visibility"
                  value={form.endpoint_visibility}
                  onChange={updateField}
                  disabled
                >
                  <option value="public">Public</option>
                </SelectField>
                <SelectField
                  label="Network"
                  name="network_mode"
                  value={form.network_mode}
                  onChange={updateField}
                  disabled
                >
                  <option value="oracle_managed">Oracle managed</option>
                </SelectField>
              </div>
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
            </section>
          </form>

          <aside className="runPanel">
            <div className="panelHeader">
              <div>
                <span>Execution</span>
                <h3>{run ? run.status : "Not started"}</h3>
              </div>
              <button
                className="secondaryAction"
                disabled={!run?.commands_text}
                onClick={saveCommands}
              >
                Save commands
              </button>
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
                  <dt>Compartment ID</dt>
                  <dd>{run.outputs?.resolved_identifiers?.compartment_id ?? "n/a"}</dd>
                  <dt>GenAI Project ID</dt>
                  <dd>{run.outputs?.resolved_identifiers?.genai_project_id ?? "n/a"}</dd>
                  <dt>Vector Store ID</dt>
                  <dd>{run.outputs?.resolved_identifiers?.vector_store_id ?? "n/a"}</dd>
                </dl>
                <h3>Command script</h3>
                <textarea readOnly value={run.commands_text ?? ""} />
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

function deploymentStatusUrl(baseUrl, deploymentRunId) {
  return `${baseUrl.replace(/\/$/, "")}/${deploymentRunId}`;
}
