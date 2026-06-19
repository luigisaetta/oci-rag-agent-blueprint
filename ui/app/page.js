"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { buildHealthUrl, buildTokenState, isAccessTokenUsable } from "./auth.mjs";
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

  const hasConversation = Boolean(conversationId);
  const canSend =
    question.trim().length > 0 &&
    !isSending &&
    (!jwtEnabled || hasIdcsConfig(idcsConfig));
  const canTestHealth = !isTestingHealth && (!jwtEnabled || hasIdcsConfig(idcsConfig));

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

  function resetConversation() {
    abortControllerRef.current?.abort();
    abortControllerRef.current = null;
    setMessages([]);
    setConversationId("");
    setTokenTotals(EMPTY_TOKEN_TOTALS);
    setErrorMessage("");
    setIsSending(false);
  }

  function updateIdcsConfig(fieldName, value) {
    setIdcsConfig((currentConfig) => ({
      ...currentConfig,
      [fieldName]: value
    }));
    setTokenState(null);
    setHealthStatus(null);
  }

  async function getBearerToken() {
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
  }

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

  async function readEventStream(stream, assistantMessageId) {
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

        <form className="composer" onSubmit={sendQuestion}>
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
