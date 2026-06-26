import assert from "node:assert/strict";
import test from "node:test";

import {
  buildAudioResponsesUrl,
  formatAudioDuration,
  formatAudioSize,
  selectSupportedAudioType
} from "./audio.mjs";

test("buildAudioResponsesUrl derives audio endpoint from responses endpoint", () => {
  assert.equal(
    buildAudioResponsesUrl("https://example.com/invoke/responses"),
    "https://example.com/invoke/responses/audio"
  );
  assert.equal(
    buildAudioResponsesUrl("https://example.com/invoke/responses/"),
    "https://example.com/invoke/responses/audio"
  );
});

test("buildAudioResponsesUrl preserves explicit audio endpoint", () => {
  assert.equal(
    buildAudioResponsesUrl("https://example.com/invoke/responses/audio"),
    "https://example.com/invoke/responses/audio"
  );
});

test("buildAudioResponsesUrl appends audio path to base URL", () => {
  assert.equal(
    buildAudioResponsesUrl("https://example.com/invoke"),
    "https://example.com/invoke/responses/audio"
  );
});

test("selectSupportedAudioType chooses the first browser-supported type", () => {
  const mediaRecorderClass = {
    isTypeSupported(audioType) {
      return audioType === "audio/ogg;codecs=opus";
    }
  };

  assert.equal(
    selectSupportedAudioType(mediaRecorderClass),
    "audio/ogg;codecs=opus"
  );
});

test("formatAudioDuration renders mm:ss", () => {
  assert.equal(formatAudioDuration(0), "0:00");
  assert.equal(formatAudioDuration(65_400), "1:05");
});

test("formatAudioSize renders compact binary sizes", () => {
  assert.equal(formatAudioSize(0), "0 KB");
  assert.equal(formatAudioSize(15_001), "15 KB");
  assert.equal(formatAudioSize(1_572_864), "1.5 MB");
});
