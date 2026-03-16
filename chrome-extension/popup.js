const status = document.getElementById("status");
let lastSelectedMic = null;

async function send(type) {
  const response = await chrome.runtime.sendMessage({ type });
  if (!response?.ok) {
    throw new Error(response?.error || "unknown error");
  }
  return response;
}

async function sendWithPayload(type, payload = {}) {
  const response = await chrome.runtime.sendMessage({ type, ...payload });
  if (!response?.ok) {
    throw new Error(response?.error || "unknown error");
  }
  return response;
}

async function refreshStatus() {
  try {
    const response = await send("popup-status");
    status.textContent = response.recording ? `Recording: ${response.sessionId}` : "Idle";
  } catch (error) {
    status.textContent = error.message;
  }
}

async function requestMicrophoneAccess() {
  if (!navigator.mediaDevices?.getUserMedia) {
    return false;
  }
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
    stream.getTracks().forEach((track) => track.stop());
    return true;
  } catch (_error) {
    return false;
  }
}

async function detectPreferredMicrophone() {
  if (!navigator.mediaDevices?.enumerateDevices) {
    return null;
  }
  const devices = await navigator.mediaDevices.enumerateDevices();
  const audioInputs = devices.filter((device) => device.kind === "audioinput");
  if (!audioInputs.length) {
    return null;
  }

  const preferred =
    audioInputs.find((device) => device.deviceId === "default") ||
    audioInputs.find((device) => /airpods/i.test(device.label)) ||
    audioInputs[0];

  return preferred
    ? {
        deviceId: preferred.deviceId,
        label: preferred.label || "Unknown microphone"
      }
    : null;
}

async function rememberMicrophone(microphone) {
  if (!microphone?.deviceId || !microphone?.label) {
    return;
  }
  await chrome.storage.local.set({
    preferredMicrophone: {
      deviceId: microphone.deviceId,
      label: microphone.label
    }
  });
}

document.getElementById("start").addEventListener("click", async () => {
  status.textContent = "Starting session...";
  try {
    const micGranted = await requestMicrophoneAccess();
    lastSelectedMic = micGranted ? await detectPreferredMicrophone() : null;
    if (lastSelectedMic) {
      await rememberMicrophone(lastSelectedMic);
    }
    const response = await sendWithPayload("popup-start", {
      microphone: lastSelectedMic
    });
    if (response.nativeAudio?.enabled) {
      status.textContent = `Recording (${response.nativeAudio.device_name || "native mic"}): ${response.session_id}`;
    } else if (response.audioEnabled) {
      const micLabel = response.microphone?.label || lastSelectedMic?.label;
      status.textContent = micLabel
        ? `Recording (${micLabel}): ${response.session_id}`
        : `Recording: ${response.session_id}`;
    } else if (!micGranted) {
      status.textContent = `Recording without mic permission: ${response.session_id}`;
    } else {
      status.textContent = `Recording without mic: ${response.session_id}`;
    }
  } catch (error) {
    status.textContent = error.message;
  }
});

refreshStatus();

document.getElementById("stop").addEventListener("click", async () => {
  status.textContent = "Finalizing session...";
  try {
    const response = await send("popup-stop");
    status.textContent = response?.summary_path || "Stopped";
  } catch (error) {
    status.textContent = error.message;
  }
});
