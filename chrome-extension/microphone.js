const statusRoot = document.getElementById("status");
const grantButton = document.getElementById("grant");
const closeButton = document.getElementById("close");

function setStatus(title, detail) {
  statusRoot.innerHTML = `<strong>${title}</strong><span>${detail}</span>`;
}

function targetTabId() {
  const params = new URLSearchParams(window.location.search);
  const value = Number(params.get("tabId"));
  return Number.isFinite(value) ? value : null;
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
    audioInputs.find((device) => /microphone|mic/i.test(device.label)) ||
    audioInputs[0];
  return preferred
    ? {
        deviceId: preferred.deviceId,
        label: preferred.label || "Unknown microphone"
      }
    : null;
}

async function requestMicrophoneAccess() {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
  stream.getTracks().forEach((track) => track.stop());
}

async function startRecordingWithPermission() {
  const tabId = targetTabId();
  if (tabId === null) {
    throw new Error("Missing target tab for recording");
  }
  setStatus("Waiting for Chrome", "Approve microphone access in the browser prompt if it appears.");
  await requestMicrophoneAccess();
  const microphone = await detectPreferredMicrophone();
  setStatus("Starting recording", "UI Commander is switching back to your original page.");
  const response = await chrome.runtime.sendMessage({
    type: "microphone-helper-start",
    tabId,
    microphone
  });
  if (!response?.ok) {
    throw new Error(response?.error || "Unable to start recording");
  }
  await chrome.tabs.update(tabId, { active: true });
  setStatus("Recording started", "You can return to the original page and reproduce the bug now.");
}

grantButton.addEventListener("click", async () => {
  grantButton.disabled = true;
  try {
    await startRecordingWithPermission();
  } catch (error) {
    setStatus("Microphone still unavailable", error?.message || "Chrome did not grant microphone access.");
    grantButton.disabled = false;
  }
});

closeButton.addEventListener("click", async () => {
  const tab = await chrome.tabs.getCurrent();
  if (tab?.id) {
    await chrome.tabs.remove(tab.id);
  }
});
