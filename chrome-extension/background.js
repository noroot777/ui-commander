const HOST_NAME = "dev.codex.ui_commander";
const EXTENSION_VERSION = chrome.runtime.getManifest().version;

let nativePort = null;
let sessionId = null;
let recording = false;
let activeTabId = null;
let attachedDebugger = null;
let nativeQueue = Promise.resolve();
let finalizing = false;
let keyframeTimer = null;
let keyframeCaptureInFlight = false;
const KEYFRAME_INTERVAL_MS = 900;
const OFFSCREEN_STOP_TIMEOUT_MS = 5000;
const OFFSCREEN_DOCUMENT_PATH = "offscreen.html";
const MICROPHONE_HELPER_PATH = "microphone.html";
let platformOs = null;
let preferredLanguage = null;
let currentNativeRequest = null;
let offscreenCreatePromise = null;
const debuggerApi = chrome.debugger || null;

const I18N = {
  en: {
    recordingStartedTitle: "Recording started",
    recordingStartedBody: "Start speaking now, then reproduce the bug in this page.",
    recordingStartedNoMicBody: "Microphone is unavailable, so this run will capture visuals only.",
    stopWith: (stop) => `Stop with ${stop}`,
    savingTitle: "Saving recording",
    savingBody: "Please wait while UI Commander writes the session, transcript, and review.",
    savingHint: "This message will update when everything is ready.",
    completeTitle: "Recording complete",
    completeBody: "The session was saved successfully.",
    completeHint: "Review is ready.",
    completeWithAgentBody: "Review is ready and the follow-up agent task has started.",
    completeWithAgentHint: "You can switch to the review page or stay in the IDE.",
    stillSavingTitle: "Still saving the last recording",
    stillSavingBody: "Please wait for the current session to finish finalizing before you start a new one.",
    stillSavingShortBody: "Please wait a moment before trying to stop again.",
    alreadyRecordingTitle: "Already recording",
    alreadyRecordingBody: "UI Commander is already capturing this page.",
    unableToStartTitle: "Unable to start recording",
    unableToStartBody: (start) => `UI Commander could not start this recording with ${start}.`,
    notRecordingTitle: "Not currently recording",
    notRecordingBody: (start) => `Press ${start} first to start a new UI Commander session.`,
    unableToStopTitle: "Unable to stop recording",
    unableToStopBody: (stop) => `UI Commander could not stop this recording cleanly with ${stop}.`,
    microphonePermissionTitle: "Microphone permission needed",
    microphonePermissionBody: "UI Commander opened a helper tab so you can allow microphone access before recording.",
    microphonePermissionHint: "Approve microphone access there, then recording will start.",
    microphoneRetryTitle: "Microphone access still blocked",
    microphoneRetryBody: "This session will continue without audio. The helper tab can re-enable microphone access for the next recording.",
    microphoneRetryHint: "Use the helper tab to allow microphone access in Chrome.",
    shortcutsTitle: "UI Commander shortcuts",
    shortcutsBody: (start, stop) => `Press ${start} to start recording on this page.\nPress ${stop} to stop and save the session.`,
    shortcutsHint: "After the start cue appears, begin speaking.",
    extensionReloadTitle: "Reload the extension",
    extensionReloadBody: (recorded, expected) => `Recording started, but Chrome is still running extension ${recorded}. The updated skill expects ${expected}.`,
    extensionReloadHint: "Open chrome://extensions and click Reload before the next recording.",
  },
  zh: {
    recordingStartedTitle: "开始录制",
    recordingStartedBody: "现在可以开始说了，然后在这个页面里复现问题。",
    recordingStartedNoMicBody: "麦克风当前不可用，这次只会采集画面和操作。",
    stopWith: (stop) => `按 ${stop} 结束录制`,
    savingTitle: "正在保存录制",
    savingBody: "UI Commander 正在整理 session、转录文本和 review 页面，请稍等。",
    savingHint: "完成后这条提示会自动更新。",
    completeTitle: "录制完成",
    completeBody: "这次 session 已经成功保存。",
    completeHint: "review 已准备好。",
    completeWithAgentBody: "review 已准备好，后续 agent 任务也已经启动。",
    completeWithAgentHint: "你可以切到 review 页面，也可以留在 IDE 里继续看。",
    stillSavingTitle: "上一条录制还在保存",
    stillSavingBody: "请等当前 session 完成收尾后，再开始下一条录制。",
    stillSavingShortBody: "请稍等一下，当前录制还在保存。",
    alreadyRecordingTitle: "已经在录制中了",
    alreadyRecordingBody: "UI Commander 正在采集当前页面。",
    unableToStartTitle: "无法开始录制",
    unableToStartBody: (start) => `UI Commander 暂时无法用 ${start} 开始这次录制。`,
    notRecordingTitle: "当前没有在录制",
    notRecordingBody: (start) => `请先按 ${start} 开始新的 UI Commander 录制。`,
    unableToStopTitle: "无法结束录制",
    unableToStopBody: (stop) => `UI Commander 暂时无法用 ${stop} 正常结束这次录制。`,
    microphonePermissionTitle: "需要麦克风权限",
    microphonePermissionBody: "UI Commander 已打开一个辅助页面，先在那里允许麦克风访问，再开始录制。",
    microphonePermissionHint: "在新页面里允许麦克风后，录制会继续开始。",
    microphoneRetryTitle: "麦克风权限仍未放行",
    microphoneRetryBody: "这次录制会继续以无音频模式进行。你可以在辅助页面里重新放行麦克风，供下一次录制使用。",
    microphoneRetryHint: "请在辅助页面里允许 Chrome 使用麦克风。",
    shortcutsTitle: "UI Commander 快捷键",
    shortcutsBody: (start, stop) => `按 ${start} 开始录制当前页面。\n按 ${stop} 结束并保存这次 session。`,
    shortcutsHint: "看到开始提示后，再开口描述问题。",
    extensionReloadTitle: "扩展还没重新 Reload",
    extensionReloadBody: (recorded, expected) => `这次录制已经开始，但 Chrome 里的扩展还是 ${recorded}，当前 skill 已更新到 ${expected}。`,
    extensionReloadHint: "请到 chrome://extensions 点一下 Reload，再录下一条。",
  },
  ja: {
    recordingStartedTitle: "録画を開始しました",
    recordingStartedBody: "ここから話し始めて、このページで不具合を再現してください。",
    recordingStartedNoMicBody: "マイクが使えないため、今回は画面と操作だけを記録します。",
    stopWith: (stop) => `${stop} で停止`,
    savingTitle: "録画を保存しています",
    savingBody: "UI Commander が session、文字起こし、review を保存しています。少し待ってください。",
    savingHint: "準備が整うとこの表示が更新されます。",
    completeTitle: "録画が完了しました",
    completeBody: "この session は正常に保存されました。",
    completeHint: "review の準備ができました。",
    completeWithAgentBody: "review の準備ができ、後続の agent タスクも開始しました。",
    completeWithAgentHint: "review ページに切り替えても、そのまま IDE にいても大丈夫です。",
    stillSavingTitle: "前回の録画を保存中です",
    stillSavingBody: "現在の session の保存が終わるまで、新しい録画の開始を少し待ってください。",
    stillSavingShortBody: "前回の録画をまだ保存中です。少し待ってください。",
    alreadyRecordingTitle: "すでに録画中です",
    alreadyRecordingBody: "UI Commander はこのページをすでに記録しています。",
    unableToStartTitle: "録画を開始できませんでした",
    unableToStartBody: (start) => `${start} でこの録画を開始できませんでした。`,
    notRecordingTitle: "現在は録画していません",
    notRecordingBody: (start) => `まず ${start} を押して、新しい UI Commander session を開始してください。`,
    unableToStopTitle: "録画を停止できませんでした",
    unableToStopBody: (stop) => `${stop} でこの録画を正常に停止できませんでした。`,
    microphonePermissionTitle: "マイク権限が必要です",
    microphonePermissionBody: "UI Commander がマイク権限を許可するためのヘルパータブを開きました。許可してから録画を開始してください。",
    microphonePermissionHint: "新しいタブでマイクを許可すると録画を始められます。",
    microphoneRetryTitle: "マイク権限がまだ許可されていません",
    microphoneRetryBody: "この録画は音声なしで続行されます。次回の録画用にヘルパータブでマイク権限を許可してください。",
    microphoneRetryHint: "ヘルパータブで Chrome のマイク利用を許可してください。",
    shortcutsTitle: "UI Commander ショートカット",
    shortcutsBody: (start, stop) => `${start} でこのページの録画を開始します。\n${stop} で停止して session を保存します。`,
    shortcutsHint: "開始メッセージが出てから話し始めてください。",
    extensionReloadTitle: "拡張機能を再読み込みしてください",
    extensionReloadBody: (recorded, expected) => `録画は開始しましたが、Chrome 側の拡張機能はまだ ${recorded} のままです。現在の skill は ${expected} を想定しています。`,
    extensionReloadHint: "次の録画前に chrome://extensions で Reload してください。",
  }
};

function platformInfo() {
  return new Promise((resolve) => {
    chrome.runtime.getPlatformInfo((info) => {
      resolve(info || { os: "unknown" });
    });
  });
}

async function shortcutLabels() {
  if (!platformOs) {
    const info = await platformInfo();
    platformOs = info.os || "unknown";
  }
  if (platformOs === "mac") {
    return { start: "Option+S", stop: "Option+E" };
  }
  return { start: "Alt+Shift+S", stop: "Alt+Shift+E" };
}

async function ensurePreferredLanguage() {
  if (preferredLanguage) {
    return preferredLanguage;
  }
  try {
    const response = await sendNative("get_preferences");
    preferredLanguage = response?.preferences?.transcription?.preferred_language || "en";
  } catch (_error) {
    preferredLanguage = "en";
  }
  return preferredLanguage;
}

async function localizedCopy() {
  const language = await ensurePreferredLanguage();
  return I18N[language] || I18N.en;
}

async function loadPreferredMicrophone() {
  try {
    const stored = await chrome.storage.local.get("preferredMicrophone");
    const microphone = stored?.preferredMicrophone;
    if (!microphone || typeof microphone !== "object") {
      return null;
    }
    if (typeof microphone.deviceId !== "string" || typeof microphone.label !== "string") {
      return null;
    }
    return {
      deviceId: microphone.deviceId,
      label: microphone.label
    };
  } catch (_error) {
    return null;
  }
}

async function savePreferredMicrophone(microphone) {
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

async function openMicrophoneHelper(targetTabId = null, reason = "permission") {
  const url = new URL(chrome.runtime.getURL(MICROPHONE_HELPER_PATH));
  if (targetTabId !== null && targetTabId !== undefined) {
    url.searchParams.set("tabId", String(targetTabId));
  }
  if (reason) {
    url.searchParams.set("reason", reason);
  }
  return chrome.tabs.create({
    url: url.toString(),
    active: true
  });
}

function setIdleBadge() {
  chrome.action.setBadgeText({ text: "" });
  chrome.action.setTitle({ title: "UI Commander" });
}

function setRecordingBadge() {
  chrome.action.setBadgeBackgroundColor({ color: "#136d3a" });
  chrome.action.setBadgeText({ text: "REC" });
  chrome.action.setTitle({ title: "UI Commander: recording" });
}

function setFinalizingBadge() {
  chrome.action.setBadgeBackgroundColor({ color: "#8a6116" });
  chrome.action.setBadgeText({ text: "..." });
  chrome.action.setTitle({ title: "UI Commander: finalizing" });
}

function ensurePort() {
  if (nativePort) {
    return nativePort;
  }
  nativePort = chrome.runtime.connectNative(HOST_NAME);
  nativePort.onDisconnect.addListener(() => {
    const disconnectMessage = chrome.runtime.lastError?.message || "";
    const pendingRequest = currentNativeRequest;
    nativePort = null;
    currentNativeRequest = null;
    if (pendingRequest) {
      pendingRequest.cleanup();
      pendingRequest.reject(new Error(disconnectMessage || "Native messaging host disconnected"));
    }
  });
  return nativePort;
}

function sendNative(command, payload = {}) {
  nativeQueue = nativeQueue.catch(() => null).then(() => new Promise((resolve, reject) => {
    const port = ensurePort();
    let settled = false;

    const cleanup = () => {
      port.onMessage.removeListener(handleMessage);
      if (currentNativeRequest?.cleanup === cleanup) {
        currentNativeRequest = null;
      }
    };

    const handleMessage = (message) => {
      if (settled) {
        return;
      }
      settled = true;
      cleanup();
      if (!message.ok) {
        reject(new Error(message.error || "native host error"));
        return;
      }
      resolve(message);
    };

    currentNativeRequest = {
      command,
      cleanup,
      reject,
    };
    port.onMessage.addListener(handleMessage);
    try {
      port.postMessage({ command, payload });
    } catch (error) {
      if (!settled) {
        settled = true;
        cleanup();
      }
      reject(error);
    }
  }));

  return nativeQueue;
}

async function hasOffscreenDocument() {
  const offscreenUrl = chrome.runtime.getURL(OFFSCREEN_DOCUMENT_PATH);
  if (typeof chrome.runtime.getContexts === "function") {
    const contexts = await chrome.runtime.getContexts({
      contextTypes: ["OFFSCREEN_DOCUMENT"],
      documentUrls: [offscreenUrl]
    });
    return contexts.length > 0;
  }

  const matchedClients = await clients.matchAll();
  return matchedClients.some((client) => client.url === offscreenUrl);
}

async function ensureOffscreenDocument() {
  if (await hasOffscreenDocument()) {
    return;
  }

  if (!offscreenCreatePromise) {
    offscreenCreatePromise = chrome.offscreen.createDocument({
      url: OFFSCREEN_DOCUMENT_PATH,
      reasons: ["USER_MEDIA"],
      justification: "Record microphone audio while UI Commander captures a session."
    }).finally(() => {
      offscreenCreatePromise = null;
    });
  }

  await offscreenCreatePromise;
}

async function closeOffscreenDocument() {
  if (!(await hasOffscreenDocument())) {
    return;
  }
  try {
    await chrome.offscreen.closeDocument();
  } catch (_error) {
    // Ignore close failures during shutdown.
  }
}

async function withTimeout(promise, timeoutMs, label) {
  if (!timeoutMs || timeoutMs <= 0) {
    return promise;
  }
  let timerId = null;
  try {
    return await Promise.race([
      promise,
      new Promise((_, reject) => {
        timerId = setTimeout(() => {
          reject(new Error(`${label} timed out after ${timeoutMs}ms`));
        }, timeoutMs);
      })
    ]);
  } finally {
    if (timerId !== null) {
      clearTimeout(timerId);
    }
  }
}

async function sendOffscreenCommand(type, payload = {}, options = {}) {
  await ensureOffscreenDocument();
  const response = await withTimeout(
    chrome.runtime.sendMessage({
      target: "offscreen",
      type,
      ...payload
    }),
    options.timeoutMs || 0,
    `Offscreen command ${type}`
  );
  if (!response?.ok) {
    throw new Error(response?.error || "Offscreen command failed");
  }
  return response;
}

async function appendInternalEvent(type, value = null) {
  if (!sessionId) {
    return;
  }
  await sendNative("append_event", {
    session_id: sessionId,
    event: {
      id: `${type}-${Date.now()}`,
      time: Date.now(),
      type,
      url: null,
      title: null,
      target: null,
      value,
      screenshot: null
    }
  });
}

async function captureScreenshot() {
  const dataUrl = await chrome.tabs.captureVisibleTab(undefined, { format: "png" });
  return dataUrl.split(",")[1];
}

async function persistKeyframe(reason = "interval") {
  if (!sessionId || !recording || keyframeCaptureInFlight) {
    return;
  }
  keyframeCaptureInFlight = true;
  try {
    const screenshot = await captureScreenshot();
    const time = Date.now();
    const screenshotPath = `screenshots/keyframes/${time}.png`;
    await sendNative("write_artifact", {
      session_id: sessionId,
      path: screenshotPath,
      data: screenshot,
      encoding: "base64"
    });
    await sendNative("append_event", {
      session_id: sessionId,
      event: {
        id: `keyframe-${time}`,
        time,
        type: "screenshot_keyframe",
        url: null,
        title: null,
        target: null,
        value: reason,
        screenshot: screenshotPath,
        captureScreenshot: false
      }
    });
  } catch (_error) {
    // Ignore intermittent screenshot failures; later keyframes may still succeed.
  } finally {
    keyframeCaptureInFlight = false;
  }
}

function startKeyframeCapture() {
  if (keyframeTimer) {
    clearInterval(keyframeTimer);
  }
  keyframeTimer = setInterval(() => {
    void persistKeyframe("interval");
  }, KEYFRAME_INTERVAL_MS);
}

function stopKeyframeCapture() {
  if (keyframeTimer) {
    clearInterval(keyframeTimer);
    keyframeTimer = null;
  }
}

async function persistEventWithOptionalScreenshot(message, sender) {
  let screenshotPath = null;
  if (message.event.captureScreenshot !== false) {
    try {
      const screenshot = await captureScreenshot();
      screenshotPath = `screenshots/${message.event.id}.png`;
      await sendNative("write_artifact", {
        session_id: sessionId,
        path: screenshotPath,
        data: screenshot,
        encoding: "base64"
      });
    } catch (_error) {
      screenshotPath = null;
    }
  }

  await sendNative("append_event", {
    session_id: sessionId,
    event: {
      ...message.event,
      screenshot: screenshotPath,
      tabId: sender.tab?.id || null,
      frameId: sender.frameId,
      target: domTargetFromMessage(message.event.target)
    }
  });
}

function domTargetFromMessage(target) {
  return {
    tag: target?.tag || null,
    text: target?.text || null,
    selector: target?.selector || null,
    rect: target?.rect || null,
    role: target?.role || null,
    name: target?.name || null
  };
}

async function attachDebugger(tabId) {
  if (!debuggerApi?.attach || !debuggerApi?.sendCommand) {
    return false;
  }
  const debuggee = { tabId };
  await debuggerApi.attach(debuggee, "1.3");
  attachedDebugger = debuggee;
  await debuggerApi.sendCommand(debuggee, "Runtime.enable");
  await debuggerApi.sendCommand(debuggee, "Network.enable");
  await debuggerApi.sendCommand(debuggee, "Log.enable");
  return true;
}

async function ensureContentScript(tabId) {
  await chrome.scripting.executeScript({
    target: { tabId, allFrames: true },
    files: ["content.js"]
  });
}

async function pingContentScript(tabId) {
  try {
    await ensureContentScript(tabId);
    const response = await chrome.tabs.sendMessage(tabId, {
      type: "ui-commander-ping"
    });
    return response?.ok === true;
  } catch (_error) {
    return false;
  }
}

async function showPageCue(tabId, textOrPayload, tone = "info") {
  try {
    await ensureContentScript(tabId);
    const payload = typeof textOrPayload === "string"
      ? { text: textOrPayload, tone }
      : { ...textOrPayload, tone: textOrPayload?.tone || tone };
    await chrome.tabs.sendMessage(tabId, {
      type: "ui-commander-cue",
      text: typeof textOrPayload === "string" ? textOrPayload : textOrPayload?.text,
      tone: payload.tone,
      payload
    });
  } catch (_error) {
    // Ignore cue failures if the page is navigating or content script is not available.
  }
}

async function removePageCue(tabId) {
  try {
    await ensureContentScript(tabId);
    await chrome.scripting.executeScript({
      target: { tabId, allFrames: false },
      func: () => {
        const cue = document.querySelector("[data-ui-commander-cue='true']");
        if (cue instanceof HTMLElement) {
          cue.remove();
        }
      }
    });
    return true;
  } catch (_error) {
    try {
      await chrome.tabs.sendMessage(tabId, {
        type: "ui-commander-remove-cue"
      });
      return true;
    } catch (_nestedError) {
      return false;
    }
  }
}

async function setContentCaptureState(tabId, enabled) {
  try {
    await ensureContentScript(tabId);
    await chrome.tabs.sendMessage(tabId, {
      type: "ui-commander-set-capture",
      enabled
    });
  } catch (_error) {
    // Ignore if the page is navigating or content script is not available.
  }
}

async function detachDebugger() {
  if (!attachedDebugger || !debuggerApi?.detach) {
    return;
  }
  try {
    await debuggerApi.detach(attachedDebugger);
  } catch (_error) {
    // Ignore detach failures during shutdown.
  }
  attachedDebugger = null;
}

async function startSession(tab, microphone = null, options = {}) {
  const shortcuts = await shortcutLabels();
  const copy = await localizedCopy();
  await ensureOffscreenDocument();
  const response = await sendNative("start_session", {
    url: tab.url,
    title: tab.title,
    extension_version: EXTENSION_VERSION
  });
  sessionId = response.session_id;
  activeTabId = tab.id;
  recording = true;
  setRecordingBadge();
  startKeyframeCapture();
  await ensureContentScript(tab.id);
  await setContentCaptureState(tab.id, true);
  await sendNative("append_event", {
    session_id: sessionId,
    event: {
      id: `session-start-${Date.now()}`,
      time: Date.now(),
      type: "session_started",
      url: tab.url,
      title: tab.title,
      target: null,
      screenshot: null
    }
  });
  const contentReady = await pingContentScript(tab.id);
  await sendNative("append_event", {
    session_id: sessionId,
    event: {
      id: `content-ready-${Date.now()}`,
      time: Date.now(),
      type: "content_script_status",
      url: tab.url,
      title: tab.title,
      target: null,
      value: contentReady ? "ready" : "missing",
      screenshot: null
    }
  });
  const debuggerAttached = await attachDebugger(tab.id);
  if (!debuggerAttached) {
    await appendInternalEvent("debugger_status", "unavailable");
  }
  let audioEnabled = false;
  let audioError = null;
  try {
    const audioStart = await sendOffscreenCommand("start-audio-recording", {
      microphone
    });
    audioEnabled = true;
    await appendInternalEvent(
      "audio_status",
      `recording:${audioStart?.mimeType || "unknown"}:${audioStart?.track || "unknown-track"}`
    );
    await appendInternalEvent(
      "audio_device",
      `${audioStart?.deviceId || microphone?.deviceId || "unknown"}:${audioStart?.track || microphone?.label || "unknown"}`
    );
  } catch (error) {
    audioEnabled = false;
    audioError = error?.message || "unknown";
    await appendInternalEvent("audio_status", `start_error:${audioError}`);
    if (options.openPermissionHelperOnAudioError !== false && /NotAllowedError|Permission dismissed|NotFoundError/i.test(audioError)) {
      await openMicrophoneHelper(tab.id, "retry");
      if (contentReady) {
        await showPageCue(
          tab.id,
          {
            title: copy.microphoneRetryTitle,
            body: copy.microphoneRetryBody,
            hint: copy.microphoneRetryHint,
            durationMs: 4200,
            tone: "warning"
          },
          "warning"
        );
      }
    }
  }
  if (contentReady) {
    await showPageCue(
      tab.id,
      audioEnabled || response.native_audio?.enabled
        ? {
            title: copy.recordingStartedTitle,
            body: copy.recordingStartedBody,
            hint: copy.stopWith(shortcuts.stop),
            durationMs: 1200
          }
        : {
            title: copy.recordingStartedTitle,
            body: copy.recordingStartedNoMicBody,
            hint: copy.stopWith(shortcuts.stop),
            durationMs: 1200,
            tone: "warning"
          },
      audioEnabled || response.native_audio?.enabled ? "success" : "warning"
    );
    if (response?.extension?.reload_required) {
      await showPageCue(
        tab.id,
        {
          title: copy.extensionReloadTitle,
          body: copy.extensionReloadBody(
            response.extension.recorded_version || EXTENSION_VERSION,
            response.extension.expected_version || "unknown"
          ),
          hint: copy.extensionReloadHint,
          durationMs: 6200,
          tone: "warning"
        },
        "warning"
      );
    }
  }
  return {
    ...response,
    audioEnabled,
    contentReady,
    nativeAudio: response.native_audio || null,
    audioError,
    microphone: audioEnabled
      ? {
          deviceId: microphone?.deviceId || null,
          label: microphone?.label || null
        }
      : null
  };
}

async function stopSession() {
  const copy = await localizedCopy();
  if (!sessionId || finalizing) {
    return null;
  }
  finalizing = true;
  const stoppingTabId = activeTabId;
  await appendInternalEvent("stop_requested", stoppingTabId);
  recording = false;
  setFinalizingBadge();
  if (stoppingTabId !== null) {
    await setContentCaptureState(stoppingTabId, false);
    await showPageCue(stoppingTabId, {
      title: copy.savingTitle,
      body: copy.savingBody,
      hint: copy.savingHint,
      sticky: true,
      maxStickyMs: 15000
    }, "info");
  }

  stopKeyframeCapture();
  await persistKeyframe("stop");

  try {
    const audioResult = await sendOffscreenCommand(
      "stop-audio-recording",
      {},
      { timeoutMs: OFFSCREEN_STOP_TIMEOUT_MS }
    );
    if (audioResult?.audio?.data) {
      await sendNative("write_artifact", {
        session_id: sessionId,
        path: "audio/mic.webm",
        data: audioResult.audio.data,
        encoding: "base64"
      });
      await appendInternalEvent(
        "audio_status",
        `saved:${audioResult.audio.size || 0}:${audioResult.chunkCount || 0}:${audioResult.byteCount || 0}`
      );
    } else {
      await appendInternalEvent(
        "audio_status",
        `empty:${audioResult?.chunkCount || 0}:${audioResult?.byteCount || 0}:${audioResult?.recorderError || "none"}`
      );
    }
  } catch (error) {
    await appendInternalEvent("audio_status", `error:${error.message || "unknown"}`);
    // Continue finalization even if microphone stop or upload fails.
  }

  await detachDebugger();
  const response = await sendNative("finalize_session", {
    session_id: sessionId
  });
  if (stoppingTabId !== null) {
    if (response?.review_opened) {
      const hidden = await removePageCue(stoppingTabId);
      if (!hidden) {
        await showPageCue(
          stoppingTabId,
          {
            title: copy.completeTitle,
            body: copy.completeWithAgentBody,
            hint: copy.completeWithAgentHint,
            durationMs: 900
          },
          "success"
        );
      }
    } else {
      await showPageCue(
        stoppingTabId,
        response?.orchestrator?.triggered
          ? {
              title: copy.completeTitle,
              body: copy.completeWithAgentBody,
              hint: copy.completeWithAgentHint
            }
          : {
              title: copy.completeTitle,
              body: copy.completeBody,
              hint: copy.completeHint
            },
        "success"
      );
    }
  }
  await closeOffscreenDocument();
  sessionId = null;
  activeTabId = null;
  finalizing = false;
  setIdleBadge();
  return response;
}

async function handleStartRequest(microphone = null) {
  if (recording || finalizing) {
    const copy = await localizedCopy();
    if (activeTabId !== null) {
      await showPageCue(
        activeTabId,
        finalizing
          ? {
              title: copy.stillSavingTitle,
              body: copy.stillSavingBody
            }
          : {
              title: copy.alreadyRecordingTitle,
              body: copy.alreadyRecordingBody
            },
        "info"
      );
    }
    return null;
  }

  const tab = await currentTab();
  let selectedMicrophone = microphone;
  if (!selectedMicrophone) {
    selectedMicrophone = await loadPreferredMicrophone();
  } else {
    await savePreferredMicrophone(selectedMicrophone);
  }

  if (!selectedMicrophone) {
    const info = await platformInfo();
    platformOs = info.os || platformOs || "unknown";
    if (platformOs === "win") {
      const copy = await localizedCopy();
      await openMicrophoneHelper(tab.id, "setup");
      await showPageCue(
        tab.id,
        {
          title: copy.microphonePermissionTitle,
          body: copy.microphonePermissionBody,
          hint: copy.microphonePermissionHint,
          durationMs: 4200,
          tone: "info"
        },
        "info"
      );
      return { ok: true, helperOpened: true };
    }
  }

  return startSession(tab, selectedMicrophone);
}

async function handleStopRequest() {
  const shortcuts = await shortcutLabels();
  const copy = await localizedCopy();
  if (finalizing) {
    const tab = await currentTab().catch(() => null);
    if (tab?.id) {
      await showPageCue(tab.id, {
        title: copy.stillSavingTitle,
        body: copy.stillSavingShortBody
      }, "info");
    }
    return null;
  }
  if (!recording) {
    const tab = await currentTab().catch(() => null);
    if (tab?.id) {
      await showPageCue(tab.id, {
        title: copy.notRecordingTitle,
        body: copy.notRecordingBody(shortcuts.start)
      }, "info");
    }
    return null;
  }
  return stopSession();
}

async function currentTab() {
  const [tab] = await chrome.tabs.query({
    active: true,
    lastFocusedWindow: true
  });
  if (!tab || !tab.id) {
    throw new Error("No active tab to record");
  }
  return tab;
}

if (debuggerApi?.onEvent) {
  debuggerApi.onEvent.addListener((source, method, params) => {
    if (!recording || !sessionId || source.tabId !== activeTabId) {
      return;
    }

    if (method === "Runtime.consoleAPICalled") {
      void sendNative("append_console", {
        session_id: sessionId,
        entry: {
          time: Date.now(),
          type: "console",
          level: params.type,
          text: (params.args || []).map((arg) => arg.value ?? arg.description ?? "").join(" "),
          stackTrace: params.stackTrace || null
        }
      });
      return;
    }

    if (method === "Runtime.exceptionThrown") {
      void sendNative("append_console", {
        session_id: sessionId,
        entry: {
          time: Date.now(),
          type: "exception",
          text: params.exceptionDetails?.text || "Runtime exception",
          stackTrace: params.exceptionDetails?.stackTrace || null
        }
      });
      return;
    }

    if (method === "Network.requestWillBeSent") {
      void sendNative("append_network", {
        session_id: sessionId,
        entry: {
          time: Date.now(),
          type: "request",
          requestId: params.requestId,
          url: params.request?.url,
          method: params.request?.method
        }
      });
      return;
    }

    if (method === "Network.responseReceived") {
      void sendNative("append_network", {
        session_id: sessionId,
        entry: {
          time: Date.now(),
          type: "response",
          requestId: params.requestId,
          url: params.response?.url,
          status: params.response?.status
        }
      });
      return;
    }

    if (method === "Network.loadingFailed") {
      void sendNative("append_network", {
        session_id: sessionId,
        entry: {
          time: Date.now(),
          type: "loadingFailed",
          requestId: params.requestId,
          errorText: params.errorText,
          canceled: params.canceled
        }
      });
    }
  });
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.target === "offscreen") {
    return false;
  }

  (async () => {
    if (message.type === "popup-start") {
      const result = await handleStartRequest(message.microphone || null);
      sendResponse(result || { ok: true });
      return;
    }

    if (message.type === "popup-stop" || message.type === "command-stop") {
      const result = await handleStopRequest();
      sendResponse(result || { ok: true });
      return;
    }

    if (message.type === "microphone-helper-start") {
      const targetTabId = Number(message.tabId);
      if (!Number.isFinite(targetTabId)) {
        throw new Error("missing target tab");
      }
      const targetTab = await chrome.tabs.get(targetTabId);
      await savePreferredMicrophone(message.microphone || null);
      const result = await startSession(targetTab, message.microphone || null, {
        openPermissionHelperOnAudioError: false
      });
      sendResponse(result || { ok: true });
      return;
    }

    if (message.type === "content-event" && recording && sessionId) {
      await persistEventWithOptionalScreenshot(message, sender);
      sendResponse({ ok: true });
      return;
    }

    if (message.type === "popup-status") {
      sendResponse({ ok: true, recording, finalizing, sessionId });
      return;
    }

    sendResponse({ ok: true, ignored: true });
  })().catch((error) => {
    sendResponse({ ok: false, error: error.message });
  });

  return true;
});

chrome.commands.onCommand.addListener((command) => {
  if (command === "start-recording") {
    void handleStartRequest(null).catch(async (error) => {
      const shortcuts = await shortcutLabels();
      const copy = await localizedCopy();
      const tab = activeTabId ? { id: activeTabId } : await currentTab().catch(() => null);
      if (tab?.id) {
        await showPageCue(tab.id, {
          title: copy.unableToStartTitle,
          body: error.message || copy.unableToStartBody(shortcuts.start)
        }, "warning");
      }
    });
    return;
  }
  if (command === "stop-recording") {
    void (async () => {
      if (recording && activeTabId !== null) {
        try {
          await chrome.tabs.sendMessage(activeTabId, {
            type: "ui-commander-command-stop"
          });
          return;
        } catch (_error) {
          // Fall back to the direct path if the tab is navigating or the content script is unavailable.
        }
      }
      await handleStopRequest();
    })().catch(async (error) => {
      const shortcuts = await shortcutLabels();
      const copy = await localizedCopy();
      const tab = activeTabId ? { id: activeTabId } : await currentTab().catch(() => null);
      if (tab?.id) {
        await showPageCue(tab.id, {
          title: copy.unableToStopTitle,
          body: error.message || copy.unableToStopBody(shortcuts.stop)
        }, "warning");
      }
    });
  }
});

chrome.action.onClicked.addListener(async (tab) => {
  if (!tab.id) {
    return;
  }
  const shortcuts = await shortcutLabels();
  const copy = await localizedCopy();
  await showPageCue(tab.id, {
    title: copy.shortcutsTitle,
    body: copy.shortcutsBody(shortcuts.start, shortcuts.stop),
    hint: copy.shortcutsHint,
    durationMs: 7000
  }, "info");
});

setIdleBadge();

chrome.runtime.onConnect.addListener((port) => {
  if (port.name !== "ui-commander-offscreen-keepalive") {
    return;
  }

  port.onDisconnect.addListener(() => {
    // No-op. The open port keeps the service worker alive while the offscreen recorder exists.
  });
});
