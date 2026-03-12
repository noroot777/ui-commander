const status = document.getElementById("status");
const port = chrome.runtime.connect({ name: "screen-commander-recorder" });

let mediaRecorder = null;
let mediaStream = null;
let chunks = [];
let totalBytes = 0;
let recorderMimeType = "";
let selectedMicrophone = null;

function setStatus(text) {
  status.textContent = text;
}

function pickMimeType() {
  const candidates = [
    "audio/webm;codecs=opus",
    "audio/webm",
    "audio/mp4"
  ];
  for (const candidate of candidates) {
    if (MediaRecorder.isTypeSupported(candidate)) {
      return candidate;
    }
  }
  return "";
}

async function startRecording(microphone = null) {
  if (mediaRecorder) {
    return {
      ok: true,
      alreadyRecording: true,
      mimeType: recorderMimeType || mediaRecorder.mimeType || "default",
      track: mediaStream?.getAudioTracks?.()[0]?.label || null,
      deviceId: selectedMicrophone?.deviceId || microphone?.deviceId || "default"
    };
  }

  selectedMicrophone = microphone || null;
  const audioConstraints = {
    echoCancellation: true,
    noiseSuppression: true
  };
  if (microphone?.deviceId && microphone.deviceId !== "default") {
    audioConstraints.deviceId = { exact: microphone.deviceId };
  }

  mediaStream = await navigator.mediaDevices.getUserMedia({
    audio: audioConstraints,
    video: false
  });

  chunks = [];
  totalBytes = 0;
  const mimeType = pickMimeType();
  mediaRecorder = mimeType
    ? new MediaRecorder(mediaStream, { mimeType })
    : new MediaRecorder(mediaStream);
  recorderMimeType = mediaRecorder.mimeType || mimeType || "";
  mediaRecorder.ondataavailable = (event) => {
    if (event.data && event.data.size > 0) {
      chunks.push(event.data);
      totalBytes += event.data.size;
    }
  };
  mediaRecorder.start();
  setStatus(`Recording from ${mediaStream.getAudioTracks()[0]?.label || microphone?.label || "microphone"}`);
  return {
    ok: true,
    mimeType: recorderMimeType || "default",
    track: mediaStream.getAudioTracks()[0]?.label || null,
    deviceId: microphone?.deviceId || "default"
  };
}

async function blobToBase64(blob) {
  return await new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onloadend = () => resolve(String(reader.result).split(",")[1]);
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(blob);
  });
}

async function stopRecording() {
  if (!mediaRecorder) {
    return { ok: true, audio: null, chunkCount: 0, byteCount: 0 };
  }

  const recorder = mediaRecorder;
  const stream = mediaStream;
  const currentMimeType = recorderMimeType || recorder.mimeType || "audio/webm";

  const stopped = new Promise((resolve, reject) => {
    recorder.onerror = (event) => {
      reject(new Error(event.error?.message || "MediaRecorder error"));
    };
    recorder.ondataavailable = (event) => {
      if (event.data && event.data.size > 0) {
        chunks.push(event.data);
        totalBytes += event.data.size;
      }
    };
    recorder.onstop = resolve;
  });

  try {
    recorder.requestData();
  } catch (_error) {
    // Ignore unsupported requestData calls.
  }
  recorder.stop();
  await stopped;

  const blob = new Blob(chunks, { type: currentMimeType });
  const base64 = blob.size > 0 ? await blobToBase64(blob) : null;
  stream.getTracks().forEach((track) => track.stop());

  mediaRecorder = null;
  mediaStream = null;
  recorderMimeType = "";
  selectedMicrophone = null;
  const chunkCount = chunks.length;
  const byteCount = totalBytes;
  chunks = [];
  totalBytes = 0;
  setStatus("Idle");

  return {
    ok: true,
    chunkCount,
    byteCount,
    audio: base64
      ? {
          mimeType: blob.type || currentMimeType || "audio/webm",
          data: base64,
          size: blob.size
        }
      : null
  };
}

port.onMessage.addListener((message) => {
  (async () => {
    if (message.type === "start-recording") {
      const result = await startRecording(message.microphone || null);
      port.postMessage({
        type: "command-result",
        commandId: message.commandId,
        ok: true,
        result
      });
      return;
    }

    if (message.type === "stop-recording") {
      const result = await stopRecording();
      port.postMessage({
        type: "command-result",
        commandId: message.commandId,
        ok: true,
        result
      });
      return;
    }

    port.postMessage({
      type: "command-result",
      commandId: message.commandId,
      ok: false,
      error: "unknown recorder command"
    });
  })().catch((error) => {
    port.postMessage({
      type: "command-result",
      commandId: message.commandId,
      ok: false,
      error: error.message
    });
  });
});

setStatus("Ready");
port.postMessage({ type: "recorder-ready" });
