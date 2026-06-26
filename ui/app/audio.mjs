export const PREFERRED_AUDIO_TYPES = [
  "audio/webm;codecs=opus",
  "audio/webm",
  "audio/ogg;codecs=opus",
  "audio/ogg",
  "audio/wav"
];

export function buildAudioResponsesUrl(backendUrl) {
  const cleanUrl = backendUrl.replace(/\/+$/u, "");

  if (cleanUrl.endsWith("/responses")) {
    return `${cleanUrl.slice(0, -"/responses".length)}/responses/audio`;
  }

  if (cleanUrl.endsWith("/responses/audio")) {
    return cleanUrl;
  }

  return `${cleanUrl}/responses/audio`;
}

export function selectSupportedAudioType(mediaRecorderClass = globalThis.MediaRecorder) {
  if (!mediaRecorderClass?.isTypeSupported) {
    return "";
  }

  return (
    PREFERRED_AUDIO_TYPES.find((audioType) =>
      mediaRecorderClass.isTypeSupported(audioType)
    ) ?? ""
  );
}

export function formatAudioDuration(milliseconds) {
  const totalSeconds = Math.max(0, Math.floor(milliseconds / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;

  return `${minutes}:${seconds.toString().padStart(2, "0")}`;
}

export function formatAudioSize(bytes) {
  if (!Number.isFinite(bytes) || bytes <= 0) {
    return "0 KB";
  }

  const kibibytes = bytes / 1024;
  if (kibibytes < 1024) {
    return `${Math.ceil(kibibytes)} KB`;
  }

  return `${(kibibytes / 1024).toFixed(1)} MB`;
}
