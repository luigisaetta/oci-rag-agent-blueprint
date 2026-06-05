"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

const DEFAULT_BACKEND_URL = "http://localhost:8080/responses";

function createMessage(role, content, status = "complete") {
  return {
    id: globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random()}`,
    role,
    content,
    status
  };
}

function parseSseFrame(frame) {
  const lines = frame.split("\n");
  let eventName = "message";
  const dataLines = [];

  for (const line of lines) {
    if (line.startsWith("event:")) {
      eventName = line.slice("event:".length).trim();
    }

    if (line.startsWith("data:")) {
      dataLines.push(line.slice("data:".length).trim());
    }
  }

  if (!dataLines.length) {
    return null;
  }

  return {
    eventName,
    data: JSON.parse(dataLines.join("\n"))
  };
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
  const [messages, setMessages] = useState([]);
  const [question, setQuestion] = useState("");
  const [isSending, setIsSending] = useState(false);
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
  const canSend = question.trim().length > 0 && !isSending;

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
    setErrorMessage("");
    setIsSending(false);
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
      const response = await fetch(backendUrl, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Accept: "text/event-stream"
        },
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

    while (true) {
      const { done, value } = await reader.read();
      if (done) {
        break;
      }

      buffer += decoder.decode(value, { stream: true });
      const frames = buffer.split("\n\n");
      buffer = frames.pop() ?? "";

      for (const frame of frames) {
        const parsedFrame = parseSseFrame(frame);
        if (!parsedFrame) {
          continue;
        }

        if (parsedFrame.eventName === "metadata") {
          setConversationId(parsedFrame.data.conversation_id ?? "");
        }

        if (parsedFrame.eventName === "token") {
          appendAssistantToken(assistantMessageId, parsedFrame.data.text ?? "");
        }

        if (parsedFrame.eventName === "error") {
          const backendError = parsedFrame.data.error ?? "Backend stream error.";
          setErrorMessage(backendError);
          appendAssistantToken(assistantMessageId, `\n\n${backendError}`);
        }

        if (parsedFrame.eventName === "done") {
          completeAssistantMessage(assistantMessageId);
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
