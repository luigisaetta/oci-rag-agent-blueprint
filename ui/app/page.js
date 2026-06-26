"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import {
  buildEnvironmentUrl,
  buildHealthUrl,
  buildTokenState,
  isAccessTokenUsable
} from "./auth.mjs";
import {
  buildAudioResponsesUrl,
  formatAudioDuration,
  formatAudioSize,
  selectSupportedAudioType
} from "./audio.mjs";
import { parseSseFrame } from "./sse.mjs";

const DEFAULT_BACKEND_URL = "http://localhost:8080/responses";
const EMPTY_TOKEN_TOTALS = {
  input: 0,
  output: 0
};
const EMPTY_IDCS_CONFIG = {
  identityDomainUrl: "",
  clientId: "",
  clientSecret: "",
  scope: ""
};
const EMPTY_AGENT_RUNTIME = {
  status: "idle",
  message: "Not loaded",
  values: {}
};
const EMPTY_AUDIO_RECORDING = {
  status: "idle",
  blob: null,
  url: "",
  mimeType: "",
  startedAt: 0,
  durationMilliseconds: 0,
  error: ""
};
const EMPTY_AUDIO_REQUEST = {
  status: "idle",
  message: ""
};

function createMessage(role, content, status = "complete") {
  return {
    id: globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random()}`,
    role,
    content,
    status
  };
}

function hasIdcsConfig(config) {
  return (
    Boolean(config.identityDomainUrl.trim()) &&
    Boolean(config.clientId.trim()) &&
    Boolean(config.clientSecret.trim()) &&
    Boolean(config.scope.trim())
  );
}

function AssistantMessageContent({ message }) {
  const isWaitingForFirstToken =
    message.status === "streaming" && message.content.length === 0;

  if (isWaitingForFirstToken) {
    return (
      <div className="waitingIndicator" role="status" aria-live="polite">
        <span className="spinner" aria-hidden="true" />
        <span>Waiting for response</span>
      </div>
    );
  }

  return (
    <div className="markdown">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content}</ReactMarkdown>
    </div>
  );
}

function extractAgentRuntime(environmentPayload) {
  const environment = environmentPayload?.environment ?? {};

  return {
    modelId: environment.OCI_MODEL_ID || "Unavailable",
    fileSearchMaxResults: environment.FILE_SEARCH_MAX_NUM_RESULTS || "10",
    region: environment.OCI_REGION || "",
    streamFinalizationMode: environment.STREAM_FINALIZATION_MODE || ""
  };
}

export default function Home() {
  const [backendUrl, setBackendUrl] = useState(DEFAULT_BACKEND_URL);
  const [conversationId, setConversationId] = useState("");
  const [tokenTotals, setTokenTotals] = useState(EMPTY_TOKEN_TOTALS);
  const [messages, setMessages] = useState([]);
  const [question, setQuestion] = useState("");
  const [isSending, setIsSending] = useState(false);
  const [jwtEnabled, setJwtEnabled] = useState(false);
  const [idcsConfig, setIdcsConfig] = useState(EMPTY_IDCS_CONFIG);
  const [tokenState, setTokenState] = useState(null);
  const [isTestingHealth, setIsTestingHealth] = useState(false);
  const [healthStatus, setHealthStatus] = useState(null);
  const [agentRuntime, setAgentRuntime] = useState(EMPTY_AGENT_RUNTIME);
  const [isLoadingAgentRuntime, setIsLoadingAgentRuntime] = useState(false);
  const [audioRecording, setAudioRecording] = useState(EMPTY_AUDIO_RECORDING);
  const [audioRequest, setAudioRequest] = useState(EMPTY_AUDIO_REQUEST);
  const [theme, setTheme] = useState(() => {
    if (typeof window === "undefined") {
      return "dark";
    }

    const savedTheme = window.localStorage.getItem("rag-ui-theme");
    if (savedTheme === "light" || savedTheme === "dark") {
      return savedTheme;
    }

    return "dark";
  });
  const [errorMessage, setErrorMessage] = useState("");
  const abortControllerRef = useRef(null);
  const chatEndRef = useRef(null);
  const mediaRecorderRef = useRef(null);
  const mediaStreamRef = useRef(null);
  const audioChunksRef = useRef([]);
  const audioTimerRef = useRef(null);

  const hasConversation = Boolean(conversationId);
  const canSend =
    question.trim().length > 0 &&
    !isSending &&
    audioRecording.status !== "recording" &&
    (!jwtEnabled || hasIdcsConfig(idcsConfig));
  const canStartRecording =
    !isSending &&
    audioRecording.status !== "recording" &&
    (!jwtEnabled || hasIdcsConfig(idcsConfig));
  const canStopRecording = audioRecording.status === "recording";
  const hasRecordedAudio = audioRecording.status === "recorded" && audioRecording.blob;
  const canTestHealth = !isTestingHealth && (!jwtEnabled || hasIdcsConfig(idcsConfig));
  const canLoadAgentRuntime =
    !isLoadingAgentRuntime && (!jwtEnabled || hasIdcsConfig(idcsConfig));

  const conversationLabel = useMemo(() => {
    if (!conversationId) {
      return "New conversation";
    }

    return conversationId;
  }, [conversationId]);

  useEffect(() => {
    window.localStorage.setItem("rag-ui-theme", theme);
  }, [theme]);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages]);

  useEffect(
    () => () => {
      stopAudioTracks();
      clearAudioTimer();
      if (audioRecording.url) {
        URL.revokeObjectURL(audioRecording.url);
      }
    },
    [audioRecording.url]
  );

  function resetConversation() {
    abortControllerRef.current?.abort();
    abortControllerRef.current = null;
    setMessages([]);
    setConversationId("");
    setTokenTotals(EMPTY_TOKEN_TOTALS);
    setErrorMessage("");
    setIsSending(false);
    discardRecording();
    setAudioRequest(EMPTY_AUDIO_REQUEST);
  }

  function updateIdcsConfig(fieldName, value) {
    setIdcsConfig((currentConfig) => ({
      ...currentConfig,
      [fieldName]: value
    }));
    setTokenState(null);
    setHealthStatus(null);
  }

  const getBearerToken = useCallback(async () => {
    if (!jwtEnabled) {
      return null;
    }

    if (isAccessTokenUsable(tokenState)) {
      return tokenState.accessToken;
    }

    const response = await fetch("/api/idcs-token", {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        identity_domain_url: idcsConfig.identityDomainUrl,
        client_id: idcsConfig.clientId,
        client_secret: idcsConfig.clientSecret,
        scope: idcsConfig.scope
      })
    });
    const payload = await response.json();

    if (!response.ok) {
      throw new Error(payload.error || `Token request returned HTTP ${response.status}`);
    }

    const nextTokenState = buildTokenState(payload);
    setTokenState(nextTokenState);
    return nextTokenState.accessToken;
  }, [idcsConfig, jwtEnabled, tokenState]);

  const loadAgentRuntime = useCallback(async () => {
    if (jwtEnabled && !hasIdcsConfig(idcsConfig)) {
      setAgentRuntime({
        status: "unavailable",
        message: "JWT settings required",
        values: {}
      });
      return;
    }

    setIsLoadingAgentRuntime(true);
    setAgentRuntime((currentRuntime) => ({
      ...currentRuntime,
      status: "loading",
      message: "Loading"
    }));

    try {
      const bearerToken = await getBearerToken();
      const headers = bearerToken ? { Authorization: `Bearer ${bearerToken}` } : {};
      const response = await fetch(buildEnvironmentUrl(backendUrl), { headers });
      const payload = await response.json();

      if (!response.ok) {
        throw new Error(payload.error || `Runtime metadata returned HTTP ${response.status}`);
      }

      setAgentRuntime({
        status: "succeeded",
        message: "Loaded",
        values: extractAgentRuntime(payload)
      });
    } catch (error) {
      setAgentRuntime({
        status: "unavailable",
        message: error.message || "Unavailable",
        values: {}
      });
    } finally {
      setIsLoadingAgentRuntime(false);
    }
  }, [backendUrl, getBearerToken, idcsConfig, jwtEnabled]);

  useEffect(() => {
    const refreshTimeout = window.setTimeout(() => {
      loadAgentRuntime();
    }, 0);

    return () => window.clearTimeout(refreshTimeout);
  }, [loadAgentRuntime]);

  async function testHealthAccess() {
    if (!canTestHealth) {
      return;
    }

    setIsTestingHealth(true);
    setHealthStatus(null);
    setErrorMessage("");

    try {
      const bearerToken = await getBearerToken();
      const headers = bearerToken ? { Authorization: `Bearer ${bearerToken}` } : {};
      const response = await fetch(buildHealthUrl(backendUrl), { headers });
      const responseText = await response.text();

      if (!response.ok) {
        throw new Error(responseText || `Health check returned HTTP ${response.status}`);
      }

      setHealthStatus({
        status: "succeeded",
        message: responseText || "Health check succeeded."
      });
      await loadAgentRuntime();
    } catch (error) {
      setHealthStatus({
        status: "failed",
        message: error.message || "Health check failed."
      });
    } finally {
      setIsTestingHealth(false);
    }
  }

  function addUsageToTokenTotals(usage) {
    if (!usage || typeof usage !== "object") {
      return;
    }

    const inputTokens = Number.isInteger(usage.input_tokens)
      ? usage.input_tokens
      : 0;
    const outputTokens = Number.isInteger(usage.output_tokens)
      ? usage.output_tokens
      : 0;

    setTokenTotals((currentTotals) => ({
      input: currentTotals.input + inputTokens,
      output: currentTotals.output + outputTokens
    }));
  }

  function appendAssistantToken(messageId, token) {
    setMessages((currentMessages) =>
      currentMessages.map((message) =>
        message.id === messageId
          ? { ...message, content: `${message.content}${token}` }
          : message
      )
    );
  }

  function completeAssistantMessage(messageId) {
    setMessages((currentMessages) =>
      currentMessages.map((message) =>
        message.id === messageId ? { ...message, status: "complete" } : message
      )
    );
  }

  function clearAudioTimer() {
    if (audioTimerRef.current) {
      window.clearInterval(audioTimerRef.current);
      audioTimerRef.current = null;
    }
  }

  function stopAudioTracks() {
    mediaStreamRef.current?.getTracks().forEach((track) => track.stop());
    mediaStreamRef.current = null;
  }

  function discardRecording() {
    clearAudioTimer();
    stopAudioTracks();
    mediaRecorderRef.current = null;
    audioChunksRef.current = [];
    setAudioRecording((currentRecording) => {
      if (currentRecording.url) {
        URL.revokeObjectURL(currentRecording.url);
      }
      return EMPTY_AUDIO_RECORDING;
    });
  }

  async function startRecording() {
    if (!canStartRecording) {
      return;
    }

    if (!navigator.mediaDevices?.getUserMedia || !globalThis.MediaRecorder) {
      setAudioRecording({
        ...EMPTY_AUDIO_RECORDING,
        status: "failed",
        error: "Audio recording is not available in this browser."
      });
      return;
    }

    try {
      discardRecording();
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mimeType = selectSupportedAudioType();
      const recorder = mimeType
        ? new MediaRecorder(stream, { mimeType })
        : new MediaRecorder(stream);
      const startedAt = Date.now();

      mediaStreamRef.current = stream;
      mediaRecorderRef.current = recorder;
      audioChunksRef.current = [];

      recorder.addEventListener("dataavailable", (event) => {
        if (event.data?.size > 0) {
          audioChunksRef.current.push(event.data);
        }
      });

      recorder.addEventListener("stop", () => {
        clearAudioTimer();
        stopAudioTracks();
        const recordedMimeType = recorder.mimeType || mimeType || "audio/webm";
        const blob = new Blob(audioChunksRef.current, { type: recordedMimeType });
        const durationMilliseconds = Date.now() - startedAt;

        if (blob.size === 0) {
          setAudioRecording({
            ...EMPTY_AUDIO_RECORDING,
            status: "failed",
            error: "No audio was captured."
          });
          return;
        }

        setAudioRecording((currentRecording) => {
          if (currentRecording.url) {
            URL.revokeObjectURL(currentRecording.url);
          }

          return {
            status: "recorded",
            blob,
            url: URL.createObjectURL(blob),
            mimeType: recordedMimeType,
            startedAt: 0,
            durationMilliseconds,
            error: ""
          };
        });
      });

      recorder.start();
      setErrorMessage("");
      setAudioRecording({
        status: "recording",
        blob: null,
        url: "",
        mimeType: recorder.mimeType || mimeType || "browser default",
        startedAt,
        durationMilliseconds: 0,
        error: ""
      });
      audioTimerRef.current = window.setInterval(() => {
        setAudioRecording((currentRecording) =>
          currentRecording.status === "recording"
            ? {
                ...currentRecording,
                durationMilliseconds: Date.now() - startedAt
              }
            : currentRecording
        );
      }, 250);
    } catch (error) {
      clearAudioTimer();
      stopAudioTracks();
      setAudioRecording({
        ...EMPTY_AUDIO_RECORDING,
        status: "failed",
        error: error.message || "Microphone permission was denied."
      });
    }
  }

  function stopRecording() {
    if (!canStopRecording) {
      return;
    }

    mediaRecorderRef.current?.stop();
  }

  async function sendRecordedAudio() {
    if (!hasRecordedAudio) {
      return;
    }

    const assistantMessage = createMessage("assistant", "", "streaming");
    let transcriptReceived = false;

    setErrorMessage("");
    setAudioRequest({
      status: "transcribing",
      message: "Transcribing audio"
    });
    setIsSending(true);

    const formData = new FormData();
    const extension = audioRecording.mimeType.includes("wav") ? "wav" : "webm";
    formData.append("file", audioRecording.blob, `voice-question.${extension}`);
    formData.append("new_conversation", hasConversation ? "false" : "true");
    formData.append("stream", "true");

    if (hasConversation) {
      formData.append("conversation_id", conversationId);
    }

    const abortController = new AbortController();
    abortControllerRef.current = abortController;

    try {
      const bearerToken = await getBearerToken();
      const requestHeaders = { Accept: "text/event-stream" };

      if (bearerToken) {
        requestHeaders.Authorization = `Bearer ${bearerToken}`;
      }

      const response = await fetch(buildAudioResponsesUrl(backendUrl), {
        method: "POST",
        headers: requestHeaders,
        body: formData,
        signal: abortController.signal
      });

      if (!response.ok || !response.body) {
        const responseText = await response.text();
        throw new Error(responseText || `Backend returned HTTP ${response.status}`);
      }

      await readEventStream(response.body, assistantMessage.id, {
        onTranscript(transcript) {
          if (transcriptReceived) {
            return;
          }

          transcriptReceived = true;
          setAudioRequest(EMPTY_AUDIO_REQUEST);
          setMessages((currentMessages) => [
            ...currentMessages,
            createMessage("user", transcript || "Voice question"),
            assistantMessage
          ]);
        }
      });
      discardRecording();
    } catch (error) {
      if (error.name !== "AbortError") {
        setAudioRequest(EMPTY_AUDIO_REQUEST);
        setErrorMessage(error.message || "Unable to send the audio request.");
        if (!transcriptReceived) {
          setMessages((currentMessages) => [
            ...currentMessages,
            createMessage("user", "Voice question"),
            {
              ...assistantMessage,
              content: "\n\nUnable to complete the request.",
              status: "complete"
            }
          ]);
        } else {
          appendAssistantToken(
            assistantMessage.id,
            "\n\nUnable to complete the request."
          );
        }
      }
    } finally {
      setAudioRequest(EMPTY_AUDIO_REQUEST);
      completeAssistantMessage(assistantMessage.id);
      setIsSending(false);
      abortControllerRef.current = null;
    }
  }

  async function sendQuestion(event) {
    event.preventDefault();
    const trimmedQuestion = question.trim();

    if (!trimmedQuestion || isSending) {
      return;
    }

    const userMessage = createMessage("user", trimmedQuestion);
    const assistantMessage = createMessage("assistant", "", "streaming");

    setMessages((currentMessages) => [
      ...currentMessages,
      userMessage,
      assistantMessage
    ]);
    setQuestion("");
    setErrorMessage("");
    setIsSending(true);

    const requestPayload = {
      new_conversation: !hasConversation,
      user_request: trimmedQuestion,
      stream: true
    };

    if (hasConversation) {
      requestPayload.conversation_id = conversationId;
    }

    const abortController = new AbortController();
    abortControllerRef.current = abortController;

    try {
      const bearerToken = await getBearerToken();
      const requestHeaders = {
        "Content-Type": "application/json",
        Accept: "text/event-stream"
      };

      if (bearerToken) {
        requestHeaders.Authorization = `Bearer ${bearerToken}`;
      }

      const response = await fetch(backendUrl, {
        method: "POST",
        headers: requestHeaders,
        body: JSON.stringify(requestPayload),
        signal: abortController.signal
      });

      if (!response.ok || !response.body) {
        const responseText = await response.text();
        throw new Error(responseText || `Backend returned HTTP ${response.status}`);
      }

      await readEventStream(response.body, assistantMessage.id);
    } catch (error) {
      if (error.name !== "AbortError") {
        setErrorMessage(error.message || "Unable to reach the backend.");
        appendAssistantToken(assistantMessage.id, "\n\nUnable to complete the request.");
      }
    } finally {
      completeAssistantMessage(assistantMessage.id);
      setIsSending(false);
      abortControllerRef.current = null;
    }
  }

  async function readEventStream(stream, assistantMessageId, options = {}) {
    const reader = stream.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let metadataSeen = false;

    while (true) {
      const { done, value } = await reader.read();
      if (done) {
        break;
      }

      buffer += decoder.decode(value, { stream: true });
      const frames = buffer.split("\n\n");
      buffer = frames.pop() ?? "";

      for (const frame of frames) {
        const parsedFrame = parseSseFrame(frame, metadataSeen);
        if (!parsedFrame) {
          continue;
        }

        if (parsedFrame.eventName === "metadata") {
          setConversationId(parsedFrame.data.conversation_id ?? "");
          metadataSeen = true;
        }

        if (parsedFrame.eventName === "transcript") {
          options.onTranscript?.(
            parsedFrame.data.transcript ?? parsedFrame.data.text ?? ""
          );
        }

        if (parsedFrame.eventName === "token") {
          appendAssistantToken(assistantMessageId, parsedFrame.data.text ?? "");
        }

        if (parsedFrame.eventName === "usage") {
          addUsageToTokenTotals(parsedFrame.data.usage);
        }

        if (parsedFrame.eventName === "error") {
          const backendError = parsedFrame.data.error ?? "Backend stream error.";
          setErrorMessage(backendError);
          appendAssistantToken(assistantMessageId, `\n\n${backendError}`);
          await reader.cancel();
          return;
        }

        if (parsedFrame.eventName === "done") {
          completeAssistantMessage(assistantMessageId);
          await reader.cancel();
          return;
        }
      }
    }
  }

  return (
    <main className={`shell ${theme}`}>
      <aside className="sidebar">
        <div className="brand">
          <div className="mark">OCI</div>
          <div>
            <h1>RAG Agent</h1>
            <p>Reference UI</p>
          </div>
        </div>

        <button className="primaryAction" type="button" onClick={resetConversation}>
          <span aria-hidden="true">+</span>
          New conversation
        </button>

        <label className="field">
          <span>Backend URL</span>
          <input
            value={backendUrl}
            onChange={(event) => setBackendUrl(event.target.value)}
            spellCheck="false"
          />
        </label>

        <section className="authPanel" aria-label="JWT authentication">
          <div className="authHeader">
            <div>
              <span>JWT authentication</span>
              <small>{jwtEnabled ? "Enabled" : "Disabled"}</small>
            </div>
            <label className="switch">
              <input
                checked={jwtEnabled}
                type="checkbox"
                onChange={(event) => {
                  setJwtEnabled(event.target.checked);
                  setTokenState(null);
                  setHealthStatus(null);
                }}
              />
              <span aria-hidden="true" />
            </label>
          </div>

          {jwtEnabled ? (
            <div className="authFields">
              <label className="field compact">
                <span>Identity Domain URL</span>
                <input
                  value={idcsConfig.identityDomainUrl}
                  onChange={(event) =>
                    updateIdcsConfig("identityDomainUrl", event.target.value)
                  }
                  placeholder="https://idcs-..."
                  spellCheck="false"
                />
              </label>
              <label className="field compact">
                <span>Client ID</span>
                <input
                  value={idcsConfig.clientId}
                  onChange={(event) => updateIdcsConfig("clientId", event.target.value)}
                  spellCheck="false"
                />
              </label>
              <label className="field compact">
                <span>Client secret</span>
                <input
                  value={idcsConfig.clientSecret}
                  type="password"
                  onChange={(event) =>
                    updateIdcsConfig("clientSecret", event.target.value)
                  }
                  spellCheck="false"
                />
              </label>
              <label className="field compact">
                <span>IDCS scope</span>
                <input
                  value={idcsConfig.scope}
                  onChange={(event) => updateIdcsConfig("scope", event.target.value)}
                  spellCheck="false"
                />
              </label>
            </div>
          ) : null}

          <button
            className="secondaryAction"
            type="button"
            disabled={!canTestHealth}
            onClick={testHealthAccess}
          >
            {isTestingHealth ? "Testing health..." : "Test health"}
          </button>

          {healthStatus ? (
            <p className={`healthStatus ${healthStatus.status}`}>
              {healthStatus.message}
            </p>
          ) : null}
        </section>

        <section className="runtimePanel" aria-label="Agent runtime">
          <div className="runtimeHeader">
            <div>
              <span>Agent runtime</span>
              <small className={agentRuntime.status}>{agentRuntime.message}</small>
            </div>
            <button
              className="miniAction"
              type="button"
              disabled={!canLoadAgentRuntime}
              onClick={loadAgentRuntime}
            >
              {isLoadingAgentRuntime ? "Loading" : "Refresh"}
            </button>
          </div>
          <dl className="runtimeGrid">
            <div>
              <dt>Model</dt>
              <dd title={agentRuntime.values.modelId ?? "Unavailable"}>
                {agentRuntime.values.modelId ?? "Unavailable"}
              </dd>
            </div>
            <div>
              <dt>Documents</dt>
              <dd>{agentRuntime.values.fileSearchMaxResults ?? "Unavailable"}</dd>
            </div>
            {agentRuntime.values.region ? (
              <div>
                <dt>Region</dt>
                <dd>{agentRuntime.values.region}</dd>
              </div>
            ) : null}
            {agentRuntime.values.streamFinalizationMode ? (
              <div>
                <dt>Stream mode</dt>
                <dd>{agentRuntime.values.streamFinalizationMode}</dd>
              </div>
            ) : null}
          </dl>
        </section>

        <div className="themeControl" aria-label="Theme selector">
          <button
            className={theme === "dark" ? "selected" : ""}
            type="button"
            onClick={() => setTheme("dark")}
          >
            Dark
          </button>
          <button
            className={theme === "light" ? "selected" : ""}
            type="button"
            onClick={() => setTheme("light")}
          >
            Light
          </button>
        </div>

        <div className="tokenPanel" aria-label="Conversation token usage">
          <span>Conversation tokens</span>
          <div className="tokenGrid">
            <div>
              <small>Input</small>
              <strong>{tokenTotals.input.toLocaleString()}</strong>
            </div>
            <div>
              <small>Output</small>
              <strong>{tokenTotals.output.toLocaleString()}</strong>
            </div>
          </div>
        </div>

        <div className="statusPanel">
          <span>Conversation</span>
          <strong title={conversationLabel}>{conversationLabel}</strong>
        </div>
      </aside>

      <section className="chatArea">
        <header className="topBar">
          <div>
            <p className="eyebrow">OCI Enterprise AI</p>
            <h2>Ask your knowledge base</h2>
          </div>
          <div className={isSending ? "live active" : "live"}>
            <span />
            {isSending ? "Streaming" : "Ready"}
          </div>
        </header>

        <div className="messages">
          {messages.length === 0 ? (
            <div className="emptyState">
              <h3>Start with a question</h3>
              <p>
                The assistant will create a conversation, search the configured
                vector store, and stream the answer here.
              </p>
            </div>
          ) : (
            messages.map((message) => (
              <article key={message.id} className={`message ${message.role}`}>
                <div className="avatar">{message.role === "user" ? "You" : "AI"}</div>
                <div className="bubble">
                  {message.role === "assistant" ? (
                    <AssistantMessageContent message={message} />
                  ) : (
                    <p>{message.content}</p>
                  )}
                </div>
              </article>
            ))
          )}
          <div ref={chatEndRef} />
        </div>

        {errorMessage ? <div className="errorBar">{errorMessage}</div> : null}
        {audioRequest.status === "transcribing" ? (
          <div className="transcriptionBar" role="status" aria-live="polite">
            <span className="spinner" aria-hidden="true" />
            <span>{audioRequest.message}</span>
          </div>
        ) : null}

        <form className="composer" onSubmit={sendQuestion}>
          <div className="voiceComposer" aria-label="Voice question recorder">
            <button
              className={
                audioRecording.status === "recording"
                  ? "voiceButton recording"
                  : "voiceButton"
              }
              type="button"
              disabled={!canStartRecording && audioRecording.status !== "recording"}
              onClick={audioRecording.status === "recording" ? stopRecording : startRecording}
              title={
                audioRecording.status === "recording"
                  ? "Stop recording"
                  : "Record voice question"
              }
            >
              <span aria-hidden="true">
                {audioRecording.status === "recording" ? "■" : "●"}
              </span>
            </button>

            <div className="voiceStatus">
              {audioRecording.status === "recording" ? (
                <span>
                  Recording {formatAudioDuration(audioRecording.durationMilliseconds)}
                </span>
              ) : null}
              {audioRecording.status === "recorded" ? (
                <span>
                  Recorded {formatAudioDuration(audioRecording.durationMilliseconds)} ·{" "}
                  {formatAudioSize(audioRecording.blob?.size ?? 0)}
                </span>
              ) : null}
              {audioRecording.status === "failed" ? (
                <span className="failed">{audioRecording.error}</span>
              ) : null}
              {audioRecording.status === "idle" ? <span>Voice input</span> : null}
              <small>{audioRecording.mimeType || "webm/opus when available"}</small>
            </div>

            {hasRecordedAudio ? (
              <div className="voicePreview">
                <audio controls src={audioRecording.url} />
                <button type="button" onClick={sendRecordedAudio}>
                  Use audio
                </button>
                <button type="button" onClick={discardRecording}>
                  Discard
                </button>
              </div>
            ) : null}
          </div>
          <textarea
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                event.currentTarget.form?.requestSubmit();
              }
            }}
            placeholder="Ask about your OCI RAG knowledge base..."
            rows={2}
          />
          <button type="submit" disabled={!canSend}>
            Send
          </button>
        </form>
      </section>
    </main>
  );
}
