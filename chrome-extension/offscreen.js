let mediaRecorder = null;
let mediaStream = null;
let chunks = [];
let totalBytes = 0;
let recorderMimeType = "";
let lastRecorderError = null;
const STOP_TIMEOUT_MS = 4000;
const keepAlivePort = chrome.runtime.connect({ name: "ui-commander-offscreen-keepalive" });

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

async function startAudioRecording(preferredMicrophone = null) {
  if (mediaRecorder) {
    return {
      ok: true,
      alreadyRecording: true,
      mimeType: recorderMimeType || mediaRecorder.mimeType || "default"
    };
  }

  const audioConstraints = {
    echoCancellation: true,
    noiseSuppression: true
  };
  if (preferredMicrophone?.deviceId && preferredMicrophone.deviceId !== "default") {
    audioConstraints.deviceId = { exact: preferredMicrophone.deviceId };
  }

  try {
    mediaStream = await navigator.mediaDevices.getUserMedia({
      audio: audioConstraints,
      video: false
    });
  } catch (error) {
    const messageParts = [];
    if (error?.name) {
      messageParts.push(error.name);
    }
    if (error?.message) {
      messageParts.push(error.message);
    }
    throw new Error(messageParts.join(": ") || "getUserMedia failed");
  }

  chunks = [];
  totalBytes = 0;
  lastRecorderError = null;
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
  mediaRecorder.onerror = (event) => {
    lastRecorderError = event.error?.message || "MediaRecorder error";
  };
  mediaRecorder.start();
  return {
    ok: true,
    mimeType: recorderMimeType || "default",
    track: mediaStream.getAudioTracks()[0]?.label || null,
    deviceId: preferredMicrophone?.deviceId || "default"
  };
}

async function blobToBase64(blob) {
  return await new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onloadend = () => {
      const dataUrl = reader.result;
      resolve(String(dataUrl).split(",")[1]);
    };
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(blob);
  });
}

function resetRecorderState() {
  if (mediaRecorder) {
    try {
      mediaRecorder.ondataavailable = null;
      mediaRecorder.onerror = null;
      mediaRecorder.onstop = null;
      if (mediaRecorder.state === "recording" || mediaRecorder.state === "paused") {
        mediaRecorder.stop();
      }
    } catch (_error) {
      // Ignore recorder shutdown errors while forcing cleanup.
    }
  }
  if (mediaStream) {
    mediaStream.getTracks().forEach((track) => {
      try {
        track.stop();
      } catch (_error) {
        // Ignore individual track shutdown errors.
      }
    });
  }
  mediaRecorder = null;
  mediaStream = null;
  chunks = [];
  totalBytes = 0;
  recorderMimeType = "";
}

async function cleanupAudioRecording() {
  resetRecorderState();
  lastRecorderError = null;
  return { ok: true, cleanedUp: true };
}

async function stopAudioRecording() {
  if (!mediaRecorder) {
    return { ok: true, audio: null };
  }

  const recorder = mediaRecorder;
  const stream = mediaStream;
  const currentMimeType = recorderMimeType || recorder.mimeType || "audio/webm";
  let finalChunkCount = chunks.length;
  let finalByteCount = totalBytes;

  const stopped = new Promise((resolve, reject) => {
    recorder.onerror = (event) => {
      reject(new Error(event.error?.message || "MediaRecorder error"));
    };
    recorder.ondataavailable = (event) => {
      if (event.data && event.data.size > 0) {
        chunks.push(event.data);
        totalBytes += event.data.size;
        finalChunkCount = chunks.length;
        finalByteCount = totalBytes;
      }
    };
    recorder.onstop = resolve;
  });

  let timedOut = false;
  if (recorder.state === "recording" || recorder.state === "paused") {
    try {
      recorder.requestData();
    } catch (_error) {
      // Some implementations do not support requestData in this state.
    }
    recorder.stop();
    const stopOutcome = await Promise.race([
      stopped.then(() => "stopped"),
      new Promise((resolve) => {
        setTimeout(() => resolve("timed_out"), STOP_TIMEOUT_MS);
      })
    ]);
    timedOut = stopOutcome === "timed_out";
  } else if (recorder.state !== "inactive") {
    await stopped;
  }
  if (timedOut) {
    lastRecorderError = lastRecorderError || "MediaRecorder stop timed out";
  }

  const blob = new Blob(chunks, { type: currentMimeType || "audio/webm" });
  const base64 = blob.size > 0 ? await blobToBase64(blob) : null;

  resetRecorderState();
  const recorderError = lastRecorderError;
  lastRecorderError = null;

  return {
    ok: true,
    chunkCount: finalChunkCount,
    byteCount: finalByteCount,
    timedOut,
    recorderError,
    audio: base64
      ? {
          mimeType: blob.type || currentMimeType || "audio/webm",
          data: base64,
          size: blob.size
        }
      : null
  };
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message.target !== "offscreen") {
    return false;
  }

  (async () => {
    if (message.type === "start-audio-recording") {
      sendResponse(await startAudioRecording(message.microphone || null));
      return;
    }

    if (message.type === "stop-audio-recording") {
      sendResponse(await stopAudioRecording());
      return;
    }
    if (message.type === "cleanup-audio-recording") {
      sendResponse(await cleanupAudioRecording());
      return;
    }
    sendResponse({ ok: false, error: "unknown offscreen command" });
  })().catch((error) => {
    sendResponse({ ok: false, error: error.message });
  });

  return true;
});

keepAlivePort.onDisconnect.addListener(() => {
  resetRecorderState();
  // The background service worker may restart and the offscreen document will reconnect on reload.
});

window.addEventListener("pagehide", () => {
  resetRecorderState();
});

window.addEventListener("beforeunload", () => {
  resetRecorderState();
});
