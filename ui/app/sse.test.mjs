import assert from "node:assert/strict";
import test from "node:test";

import { parseSseFrame } from "./sse.mjs";

test("parseSseFrame preserves named SSE events", () => {
  const frame = 'event: token\ndata: {"text": "ok"}';

  assert.deepEqual(parseSseFrame(frame), {
    eventName: "token",
    data: { text: "ok" }
  });
});

test("parseSseFrame infers hosted gateway event names from data frames", () => {
  assert.deepEqual(parseSseFrame('data: {"conversation_id": "conv-123"}'), {
    eventName: "metadata",
    data: { conversation_id: "conv-123" }
  });
  assert.deepEqual(parseSseFrame('data: {"text": "ok"}', true), {
    eventName: "token",
    data: { text: "ok" }
  });
  assert.deepEqual(parseSseFrame('data: {"transcript": "hello"}', true), {
    eventName: "transcript",
    data: { transcript: "hello" }
  });
  assert.deepEqual(parseSseFrame('data: {"references": []}', true), {
    eventName: "references",
    data: { references: [] }
  });
  assert.deepEqual(parseSseFrame('data: {"usage": {"total_tokens": 10}}', true), {
    eventName: "usage",
    data: { usage: { total_tokens: 10 } }
  });
  assert.deepEqual(parseSseFrame('data: {"conversation_id": "conv-123"}', true), {
    eventName: "done",
    data: { conversation_id: "conv-123" }
  });
});
