const METADATA_DISPLAY_KEYS = [
  "title",
  "path",
  "url",
  "source",
  "document_id",
  "file_id"
];

export function normalizeReferences(references) {
  if (!Array.isArray(references)) {
    return [];
  }

  return references
    .filter((reference) => reference && typeof reference === "object")
    .map((reference) => ({
      fileName: toDisplayString(reference.file_name) || "Unknown source",
      page: Number.isInteger(reference.page) ? reference.page : null,
      metadata: normalizeMetadata(reference.metadata)
    }));
}

export function formatReferenceLabel(reference, index) {
  const fileName = reference?.fileName || "Unknown source";
  const pageLabel = Number.isInteger(reference?.page)
    ? `, page ${reference.page}`
    : "";

  return `${index}. ${fileName}${pageLabel}`;
}

export function formatMetadataSummary(metadata) {
  if (!metadata || typeof metadata !== "object") {
    return "";
  }

  for (const key of METADATA_DISPLAY_KEYS) {
    const value = toDisplayString(metadata[key]);
    if (value) {
      return value;
    }
  }

  const [firstValue] = Object.values(metadata)
    .map((value) => toDisplayString(value))
    .filter(Boolean);

  return firstValue || "";
}

function normalizeMetadata(metadata) {
  if (!metadata || typeof metadata !== "object" || Array.isArray(metadata)) {
    return {};
  }

  return metadata;
}

function toDisplayString(value) {
  if (typeof value === "string") {
    return value.trim();
  }

  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }

  return "";
}
