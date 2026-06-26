export function parseSseFrame(frame, metadataSeen = false) {
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

  const data = JSON.parse(dataLines.join("\n"));

  return {
    eventName: normalizeSseEventName(eventName, data, metadataSeen),
    data
  };
}

export function normalizeSseEventName(eventName, data, metadataSeen = false) {
  if (eventName !== "message") {
    return eventName;
  }

  const payloadKeyEvents = {
    transcript: "transcript",
    text: "token",
    references: "references",
    usage: "usage",
    error: "error"
  };

  for (const [payloadKey, inferredEventName] of Object.entries(payloadKeyEvents)) {
    if (Object.hasOwn(data, payloadKey)) {
      return inferredEventName;
    }
  }

  if (Object.hasOwn(data, "conversation_id")) {
    return metadataSeen ? "done" : "metadata";
  }

  return eventName;
}
