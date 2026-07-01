import assert from "node:assert/strict";
import test from "node:test";

import {
  formatMetadataSummary,
  formatReferenceLabel,
  normalizeReferences
} from "./references.mjs";

test("normalizeReferences keeps displayable source metadata", () => {
  const references = normalizeReferences([
    {
      file_name: "guide.pdf",
      page: 7,
      metadata: {
        title: "OCI RAG guide"
      }
    },
    {
      file_name: "notes.md",
      page: null,
      metadata: ["ignored"]
    },
    null
  ]);

  assert.deepEqual(references, [
    {
      fileName: "guide.pdf",
      page: 7,
      metadata: {
        title: "OCI RAG guide"
      }
    },
    {
      fileName: "notes.md",
      page: null,
      metadata: {}
    }
  ]);
});

test("normalizeReferences handles malformed payloads as empty references", () => {
  assert.deepEqual(normalizeReferences(undefined), []);
  assert.deepEqual(normalizeReferences({ file_name: "guide.pdf" }), []);
});

test("formatReferenceLabel includes page when available", () => {
  assert.equal(
    formatReferenceLabel({ fileName: "guide.pdf", page: 3 }, 1),
    "1. guide.pdf, page 3"
  );
  assert.equal(
    formatReferenceLabel({ fileName: "guide.pdf", page: null }, 2),
    "2. guide.pdf"
  );
});

test("formatMetadataSummary prefers readable metadata keys", () => {
  assert.equal(
    formatMetadataSummary({
      id: "opaque",
      path: "docs/guide.pdf"
    }),
    "docs/guide.pdf"
  );
  assert.equal(formatMetadataSummary({ chunk: 4 }), "4");
  assert.equal(formatMetadataSummary([]), "");
});
