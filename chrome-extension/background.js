const HOST_NAME = "dev.fjh.screen_commander";

let nativePort = null;
let sessionId = null;
let recording = false;
let activeTabId = null;
let attachedDebugger = null;
let nativeQueue = Promise.resolve();
let finalizing = false;
let recorderPort = null;
let recorderWindowId = null;
let recorderCommandId = 0;
const recorderPending = new Map();
let keyframeTimer = null;
let keyframeCaptureInFlight = false;
const KEYFRAME_INTERVAL_MS = 900;
let platformOs = null;
let preferredLanguage = null;

const I18N = {
  en: {
    recordingStartedTitle: "Recording started",
    recordingStartedBody: "Start speaking now, then reproduce the bug in this page.",
    recordingStartedNoMicBody: "Microphone is unavailable, so this run will capture visuals only.",
    stopWith: (stop) => `Stop with ${stop}`,
    savingTitle: "Saving recording",
    savingBody: "Please wait while Screen Commander writes the session, transcript, and review.",
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
    alreadyRecordingBody: "Screen Commander is already capturing this page.",
    unableToStartTitle: "Unable to start recording",
    unableToStartBody: (start) => `Screen Commander could not start this recording with ${start}.`,
    notRecordingTitle: "Not currently recording",
    notRecordingBody: (start) => `Press ${start} first to start a new Screen Commander session.`,
    unableToStopTitle: "Unable to stop recording",
    unableToStopBody: (stop) => `Screen Commander could not stop this recording cleanly with ${stop}.`,
    shortcutsTitle: "Screen Commander shortcuts",
    shortcutsBody: (start, stop) => `Press ${start} to start recording on this page.\nPress ${stop} to stop and save the session.`,
    shortcutsHint: "After the start cue appears, begin speaking.",
  },
  zh: {
    recordingStartedTitle: "开始录制",
    recordingStartedBody: "现在可以开始说了，然后在这个页面里复现问题。",
    recordingStartedNoMicBody: "麦克风当前不可用，这次只会采集画面和操作。",
    stopWith: (stop) => `按 ${stop} 结束录制`,
    savingTitle: "正在保存录制",
    savingBody: "Screen Commander 正在整理 session、转录文本和 review 页面，请稍等。",
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
    alreadyRecordingBody: "Screen Commander 正在采集当前页面。",
    unableToStartTitle: "无法开始录制",
    unableToStartBody: (start) => `Screen Commander 暂时无法用 ${start} 开始这次录制。`,
    notRecordingTitle: "当前没有在录制",
    notRecordingBody: (start) => `请先按 ${start} 开始新的 Screen Commander 录制。`,
    unableToStopTitle: "无法结束录制",
    unableToStopBody: (stop) => `Screen Commander 暂时无法用 ${stop} 正常结束这次录制。`,
    shortcutsTitle: "Screen Commander 快捷键",
    shortcutsBody: (start, stop) => `按 ${start} 开始录制当前页面。\n按 ${stop} 结束并保存这次 session。`,
    shortcutsHint: "看到开始提示后，再开口描述问题。",
  },
  ja: {
    recordingStartedTitle: "録画を開始しました",
    recordingStartedBody: "ここから話し始めて、このページで不具合を再現してください。",
    recordingStartedNoMicBody: "マイクが使えないため、今回は画面と操作だけを記録します。",
    stopWith: (stop) => `${stop} で停止`,
    savingTitle: "録画を保存しています",
    savingBody: "Screen Commander が session、文字起こし、review を保存しています。少し待ってください。",
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
    alreadyRecordingBody: "Screen Commander はこのページをすでに記録しています。",
    unableToStartTitle: "録画を開始できませんでした",
    unableToStartBody: (start) => `${start} でこの録画を開始できませんでした。`,
    notRecordingTitle: "現在は録画していません",
    notRecordingBody: (start) => `まず ${start} を押して、新しい Screen Commander session を開始してください。`,
    unableToStopTitle: "録画を停止できませんでした",
    unableToStopBody: (stop) => `${stop} でこの録画を正常に停止できませんでした。`,
    shortcutsTitle: "Screen Commander ショートカット",
    shortcutsBody: (start, stop) => `${start} でこのページの録画を開始します。\n${stop} で停止して session を保存します。`,
    shortcutsHint: "開始メッセージが出てから話し始めてください。",
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
  return { start: "Alt+S", stop: "Alt+E" };
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

function setIdleBadge() {
  chrome.action.setBadgeText({ text: "" });
  chrome.action.setTitle({ title: "Screen Commander" });
}

function setRecordingBadge() {
  chrome.action.setBadgeBackgroundColor({ color: "#136d3a" });
  chrome.action.setBadgeText({ text: "REC" });
  chrome.action.setTitle({ title: "Screen Commander: recording" });
}

function setFinalizingBadge() {
  chrome.action.setBadgeBackgroundColor({ color: "#8a6116" });
  chrome.action.setBadgeText({ text: "..." });
  chrome.action.setTitle({ title: "Screen Commander: finalizing" });
}

function ensurePort() {
  if (nativePort) {
    return nativePort;
  }
  nativePort = chrome.runtime.connectNative(HOST_NAME);
  nativePort.onDisconnect.addListener(() => {
    nativePort = null;
  });
  return nativePort;
}

function sendNative(command, payload = {}) {
  nativeQueue = nativeQueue.catch(() => null).then(() => new Promise((resolve, reject) => {
    const port = ensurePort();
    const handleMessage = (message) => {
      port.onMessage.removeListener(handleMessage);
      if (!message.ok) {
        reject(new Error(message.error || "native host error"));
        return;
      }
      resolve(message);
    };

    port.onMessage.addListener(handleMessage);
    port.postMessage({ command, payload });
  }));

  return nativeQueue;
}

async function ensureRecorderWindow() {
  if (recorderPort) {
    return;
  }

  const window = await chrome.windows.create({
    url: chrome.runtime.getURL("recorder.html"),
    type: "popup",
    width: 320,
    height: 180,
    focused: false
  });
  recorderWindowId = window.id ?? null;

  await new Promise((resolve, reject) => {
    const timeout = setTimeout(() => {
      reject(new Error("Recorder window did not connect"));
    }, 5000);

    const checkReady = () => {
      if (recorderPort) {
        clearTimeout(timeout);
        resolve();
      } else {
        setTimeout(checkReady, 100);
      }
    };
    checkReady();
  });
}

async function closeRecorderWindow() {
  if (recorderWindowId !== null) {
    try {
      await chrome.windows.remove(recorderWindowId);
    } catch (_error) {
      // Ignore remove failures during shutdown.
    }
  }
  recorderWindowId = null;
}

function sendRecorderCommand(type, payload = {}) {
  if (!recorderPort) {
    return Promise.reject(new Error("Recorder is not connected"));
  }

  recorderCommandId += 1;
  const commandId = `recorder-${recorderCommandId}`;
  return new Promise((resolve, reject) => {
    recorderPending.set(commandId, { resolve, reject });
    recorderPort.postMessage({
      type,
      commandId,
      ...payload
    });
  });
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
  const debuggee = { tabId };
  await chrome.debugger.attach(debuggee, "1.3");
  attachedDebugger = debuggee;
  await chrome.debugger.sendCommand(debuggee, "Runtime.enable");
  await chrome.debugger.sendCommand(debuggee, "Network.enable");
  await chrome.debugger.sendCommand(debuggee, "Log.enable");
}

async function ensureContentScript(tabId) {
  await chrome.scripting.executeScript({
    target: { tabId, allFrames: true },
    files: ["content.js"]
  });
}

async function pingContentScript(tabId) {
  try {
    const response = await chrome.tabs.sendMessage(tabId, {
      type: "screen-commander-ping"
    });
    return response?.ok === true;
  } catch (_error) {
    return false;
  }
}

async function showPageCue(tabId, textOrPayload, tone = "info") {
  try {
    const payload = typeof textOrPayload === "string"
      ? { text: textOrPayload, tone }
      : { ...textOrPayload, tone: textOrPayload?.tone || tone };
    await chrome.tabs.sendMessage(tabId, {
      type: "screen-commander-cue",
      text: typeof textOrPayload === "string" ? textOrPayload : textOrPayload?.text,
      tone: payload.tone,
      payload
    });
  } catch (_error) {
    // Ignore cue failures if the page is navigating or content script is not available.
  }
}

async function hidePageCue(tabId) {
  try {
    await chrome.tabs.sendMessage(tabId, {
      type: "screen-commander-hide-cue"
    });
  } catch (_error) {
    // Ignore cue failures if the page is navigating or content script is not available.
  }
}

async function setContentCaptureState(tabId, enabled) {
  try {
    await chrome.tabs.sendMessage(tabId, {
      type: "screen-commander-set-capture",
      enabled
    });
  } catch (_error) {
    // Ignore if the page is navigating or content script is not available.
  }
}

async function detachDebugger() {
  if (!attachedDebugger) {
    return;
  }
  try {
    await chrome.debugger.detach(attachedDebugger);
  } catch (_error) {
    // Ignore detach failures during shutdown.
  }
  attachedDebugger = null;
}

async function startSession(tab, microphone = null) {
  const shortcuts = await shortcutLabels();
  const copy = await localizedCopy();
  await ensureRecorderWindow();
  const response = await sendNative("start_session", {
    url: tab.url,
    title: tab.title
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
  await attachDebugger(tab.id);
  let audioEnabled = false;
  try {
    const audioStart = await sendRecorderCommand("start-recording", {
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
  } catch (_error) {
    audioEnabled = false;
    await appendInternalEvent("audio_status", "unavailable");
  }
  if (contentReady) {
    await showPageCue(
      tab.id,
      audioEnabled || response.native_audio?.enabled
        ? {
            title: copy.recordingStartedTitle,
            body: copy.recordingStartedBody,
            hint: copy.stopWith(shortcuts.stop),
            durationMs: 5200
          }
        : {
            title: copy.recordingStartedTitle,
            body: copy.recordingStartedNoMicBody,
            hint: copy.stopWith(shortcuts.stop),
            durationMs: 5600,
            tone: "warning"
          },
      audioEnabled || response.native_audio?.enabled ? "success" : "warning"
    );
  }
  return {
    ...response,
    audioEnabled,
    contentReady,
    nativeAudio: response.native_audio || null,
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
      sticky: true
    }, "info");
  }

  stopKeyframeCapture();
  await persistKeyframe("stop");

  try {
    const audioResult = await sendRecorderCommand("stop-recording");
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
      await hidePageCue(stoppingTabId);
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
  await closeRecorderWindow();
  sessionId = null;
  activeTabId = null;
  finalizing = false;
  setIdleBadge();
  return response;
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

chrome.debugger.onEvent.addListener((source, method, params) => {
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

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  (async () => {
    if (message.type === "popup-start") {
      const tab = await currentTab();
      const result = await startSession(tab, message.microphone || null);
      sendResponse(result);
      return;
    }

    if (message.type === "popup-stop") {
      const result = await stopSession();
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
    void (async () => {
      const shortcuts = await shortcutLabels();
      const copy = await localizedCopy();
      if (recording || finalizing) {
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
        return;
      }
      const tab = await currentTab();
      await startSession(tab, null);
    })().catch(async (error) => {
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
        return;
      }
      if (!recording) {
        const tab = await currentTab().catch(() => null);
        if (tab?.id) {
          await showPageCue(tab.id, {
            title: copy.notRecordingTitle,
            body: copy.notRecordingBody(shortcuts.start)
          }, "info");
        }
        return;
      }
      await stopSession();
    })().catch(async (error) => {
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
  if (port.name !== "screen-commander-recorder") {
    return;
  }

  recorderPort = port;
  port.onDisconnect.addListener(() => {
    recorderPort = null;
    for (const pending of recorderPending.values()) {
      pending.reject(new Error("Recorder disconnected"));
    }
    recorderPending.clear();
  });

  port.onMessage.addListener((message) => {
    if (message.type === "recorder-ready") {
      return;
    }
    if (message.type !== "command-result" || !message.commandId) {
      return;
    }
    const pending = recorderPending.get(message.commandId);
    if (!pending) {
      return;
    }
    recorderPending.delete(message.commandId);
    if (message.ok) {
      pending.resolve(message.result);
    } else {
      pending.reject(new Error(message.error || "Recorder command failed"));
    }
  });
});
