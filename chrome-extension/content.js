if (!window.__screenCommanderInjected) {
  window.__screenCommanderInjected = true;

  let eventCounter = 0;
  let lastScrollAt = 0;
  let lastMoveAt = 0;
  let extensionAlive = true;
  let captureEnabled = true;
  let cueElement = null;
  let cueTimer = null;
  let cueTitleElement = null;
  let cueBodyElement = null;
  let cueHintElement = null;
  let cueSequence = 0;

  function runtimeAvailable() {
    try {
      return typeof chrome !== "undefined" && Boolean(chrome.runtime?.id);
    } catch (_error) {
      return false;
    }
  }

  function nextId() {
    eventCounter += 1;
    return `${Date.now()}-${eventCounter}`;
  }

  function selectorFor(element) {
    if (!element || element.nodeType !== Node.ELEMENT_NODE) {
      return null;
    }
    if (element.id) {
      return `#${element.id}`;
    }
    if (element.getAttribute("data-testid")) {
      return `[data-testid="${element.getAttribute("data-testid")}"]`;
    }
    if (element.className && typeof element.className === "string") {
      const className = element.className.trim().split(/\s+/).slice(0, 2).join(".");
      if (className) {
        return `${element.tagName.toLowerCase()}.${className}`;
      }
    }
    return element.tagName.toLowerCase();
  }

  function targetSummary(element) {
    if (!element || element.nodeType !== Node.ELEMENT_NODE) {
      return null;
    }
    try {
      const cueRoot = typeof element.closest === "function"
        ? element.closest("[data-screen-commander-cue='true']")
        : null;
      const rect = typeof element.getBoundingClientRect === "function"
        ? element.getBoundingClientRect()
        : { x: 0, y: 0, width: 0, height: 0 };
      return {
        tag: element.tagName.toLowerCase(),
        text: (element.innerText || element.value || "").trim().slice(0, 120),
        selector: selectorFor(element),
        role: typeof element.getAttribute === "function" ? element.getAttribute("role") : null,
        name: typeof element.getAttribute === "function" ? element.getAttribute("name") : null,
        screenCommanderCue: Boolean(cueRoot),
        rect: {
          x: Math.round(rect.x || 0),
          y: Math.round(rect.y || 0),
          width: Math.round(rect.width || 0),
          height: Math.round(rect.height || 0)
        }
      };
    } catch (_error) {
      extensionAlive = false;
      return null;
    }
  }

  function postEvent(type, target, extra = {}) {
    if (!captureEnabled) {
      return;
    }
    if (!extensionAlive || !runtimeAvailable()) {
      extensionAlive = false;
      return;
    }

    try {
      chrome.runtime.sendMessage({
        type: "content-event",
        event: {
          id: nextId(),
          time: Date.now(),
          type,
          url: location.href,
          title: document.title,
          target: targetSummary(target),
          viewport: {
            width: window.innerWidth,
            height: window.innerHeight,
            dpr: window.devicePixelRatio || 1
          },
          ...extra
        }
      }, () => {
        try {
          if (chrome.runtime.lastError) {
            extensionAlive = false;
          }
        } catch (_error) {
          extensionAlive = false;
        }
      });
    } catch (_error) {
      extensionAlive = false;
    }
  }

  function resetInjectionFlag() {
    window.__screenCommanderInjected = false;
  }

  function normalizeCuePayload(payload, tone = "info") {
    if (typeof payload === "string") {
      return {
        title: payload,
        body: "",
        hint: "",
        tone,
        durationMs: tone === "success" ? 3200 : 4200,
        sticky: false
      };
    }

    const resolvedTone = payload?.tone || tone || "info";
    return {
      title: payload?.title || payload?.text || "Screen Commander",
      body: payload?.body || "",
      hint: payload?.hint || "",
      tone: resolvedTone,
      durationMs: payload?.durationMs ?? (resolvedTone === "success" ? 3200 : 4200),
      sticky: Boolean(payload?.sticky),
      maxStickyMs: payload?.maxStickyMs ?? 15000
    };
  }

  function showCue(message, tone = "info") {
    if (!document.documentElement) {
      return;
    }
    const payload = normalizeCuePayload(message, tone);
    cueSequence += 1;
    const currentCueSequence = cueSequence;
    if (cueTimer) {
      clearTimeout(cueTimer);
      cueTimer = null;
    }
    if (!cueElement) {
      cueElement = document.createElement("div");
      cueElement.setAttribute("data-screen-commander-cue", "true");
      cueElement.style.position = "fixed";
      cueElement.style.top = "18px";
      cueElement.style.left = "50%";
      cueElement.style.transform = "translateX(-50%) translateY(0)";
      cueElement.style.zIndex = "2147483647";
      cueElement.style.padding = "14px 16px";
      cueElement.style.borderRadius = "14px";
      cueElement.style.fontFamily = "ui-sans-serif, system-ui, sans-serif";
      cueElement.style.lineHeight = "1.4";
      cueElement.style.maxWidth = "360px";
      cueElement.style.minWidth = "280px";
      cueElement.style.boxShadow = "0 16px 40px rgba(0, 0, 0, 0.24)";
      cueElement.style.border = "1px solid rgba(255, 255, 255, 0.24)";
      cueElement.style.backdropFilter = "blur(12px)";
      cueElement.style.webkitBackdropFilter = "blur(12px)";
      cueElement.style.display = "flex";
      cueElement.style.flexDirection = "column";
      cueElement.style.gap = "6px";

      cueTitleElement = document.createElement("div");
      cueTitleElement.style.fontSize = "14px";
      cueTitleElement.style.fontWeight = "700";
      cueTitleElement.style.letterSpacing = "0.01em";
      cueElement.appendChild(cueTitleElement);

      cueBodyElement = document.createElement("div");
      cueBodyElement.style.fontSize = "13px";
      cueBodyElement.style.opacity = "0.92";
      cueBodyElement.style.whiteSpace = "pre-wrap";
      cueBodyElement.style.display = "none";
      cueElement.appendChild(cueBodyElement);

      cueHintElement = document.createElement("div");
      cueHintElement.style.fontSize = "12px";
      cueHintElement.style.fontWeight = "600";
      cueHintElement.style.opacity = "0.9";
      cueHintElement.style.display = "none";
      cueHintElement.style.marginTop = "2px";
      cueElement.appendChild(cueHintElement);

      document.documentElement.appendChild(cueElement);
    }

    if (payload.tone === "success") {
      cueElement.style.background = "rgba(19, 109, 58, 0.92)";
      cueElement.style.color = "#f4fff8";
    } else if (payload.tone === "warning") {
      cueElement.style.background = "rgba(133, 77, 14, 0.94)";
      cueElement.style.color = "#fff7ed";
    } else {
      cueElement.style.background = "rgba(31, 41, 55, 0.92)";
      cueElement.style.color = "#ffffff";
    }
    cueTitleElement.textContent = payload.title;
    cueBodyElement.textContent = payload.body;
    cueBodyElement.style.display = payload.body ? "block" : "none";
    cueHintElement.textContent = payload.hint;
    cueHintElement.style.display = payload.hint ? "block" : "none";
    cueElement.style.opacity = "1";
    cueElement.style.transform = "translateX(-50%) translateY(0)";
    cueElement.style.transition = "opacity 180ms ease, transform 180ms ease";

    const scheduleHide = (delayMs) => {
      cueTimer = window.setTimeout(() => {
        if (currentCueSequence !== cueSequence) {
          return;
        }
        hideCue();
      }, Math.max(0, delayMs));
    };

    if (!payload.sticky) {
      scheduleHide(payload.durationMs);
    } else if (payload.maxStickyMs > 0) {
      scheduleHide(payload.maxStickyMs);
    }
  }

  function hideCue() {
    if (cueTimer) {
      clearTimeout(cueTimer);
      cueTimer = null;
    }
    if (!cueElement) {
      return;
    }
    cueElement.style.opacity = "0";
    cueElement.style.transform = "translateX(-50%) translateY(-6px)";
  }

  function removeCue() {
    if (cueTimer) {
      clearTimeout(cueTimer);
      cueTimer = null;
    }
    if (cueElement?.parentNode) {
      cueElement.parentNode.removeChild(cueElement);
    }
    cueElement = null;
    cueTitleElement = null;
    cueBodyElement = null;
    cueHintElement = null;
  }

  window.addEventListener("pagehide", resetInjectionFlag);
  window.addEventListener("beforeunload", resetInjectionFlag);

  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") {
      window.__screenCommanderInjected = false;
    }
  });

  postEvent("page_ready", document.body, {
    readyState: document.readyState,
    captureScreenshot: false
  });

  document.addEventListener("click", (event) => {
    postEvent("click", event.target, {
      x: Math.round(event.clientX),
      y: Math.round(event.clientY),
      button: event.button
    });
  }, true);

  document.addEventListener("dblclick", (event) => {
    postEvent("dblclick", event.target, {
      x: Math.round(event.clientX),
      y: Math.round(event.clientY),
      button: event.button
    });
  }, true);

  document.addEventListener("input", (event) => {
    const value = typeof event.target?.value === "string" ? event.target.value.slice(0, 200) : null;
    postEvent("input", event.target, { value, captureScreenshot: false });
  }, true);

  document.addEventListener("change", (event) => {
    const value = typeof event.target?.value === "string" ? event.target.value.slice(0, 200) : null;
    postEvent("change", event.target, { value });
  }, true);

  document.addEventListener("submit", (event) => {
    postEvent("submit", event.target);
  }, true);

  document.addEventListener("keydown", (event) => {
    if (!["Enter", "Escape", "Tab"].includes(event.key)) {
      return;
    }
    postEvent("keydown", event.target, { key: event.key, captureScreenshot: false });
  }, true);

  document.addEventListener("mousemove", (event) => {
    const now = Date.now();
    if (now - lastMoveAt < 120) {
      return;
    }
    lastMoveAt = now;
    postEvent("mousemove", event.target, {
      x: Math.round(event.clientX),
      y: Math.round(event.clientY),
      captureScreenshot: false
    });
  }, true);

  window.addEventListener("scroll", () => {
    if (Date.now() - lastScrollAt < 400) {
      return;
    }
    lastScrollAt = Date.now();
    postEvent("scroll", document.documentElement, {
      scrollX: window.scrollX,
      scrollY: window.scrollY,
      captureScreenshot: false
    });
  }, { passive: true });

  let lastUrl = location.href;
  function emitNavigation(kind) {
    if (location.href !== lastUrl) {
      lastUrl = location.href;
      postEvent("navigation", document.body, { navigationKind: kind });
    }
  }

  const originalPushState = history.pushState;
  history.pushState = function pushState(...args) {
    const result = originalPushState.apply(this, args);
    emitNavigation("pushState");
    return result;
  };

  const originalReplaceState = history.replaceState;
  history.replaceState = function replaceState(...args) {
    const result = originalReplaceState.apply(this, args);
    emitNavigation("replaceState");
    return result;
  };

  window.addEventListener("popstate", () => {
    emitNavigation("popstate");
  });

  document.addEventListener("visibilitychange", () => {
    postEvent("visibilitychange", document.body, {
      visibilityState: document.visibilityState,
      captureScreenshot: false
    });
  });

  setInterval(() => {
    emitNavigation("poll");
  }, 500);

  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (message.type === "screen-commander-ping") {
      sendResponse({ ok: true });
      return true;
    }
    if (message.type === "screen-commander-set-capture") {
      captureEnabled = message.enabled !== false;
      sendResponse({ ok: true, captureEnabled });
      return true;
    }
    if (message.type === "screen-commander-command-stop") {
      chrome.runtime.sendMessage({ type: "command-stop" }, (response) => {
        if (chrome.runtime.lastError) {
          sendResponse({ ok: false, error: chrome.runtime.lastError.message });
          return;
        }
        sendResponse(response || { ok: true });
      });
      return true;
    }
    if (message.type === "screen-commander-remove-cue") {
      removeCue();
      sendResponse({ ok: true });
      return true;
    }
    if (message.type === "screen-commander-cue") {
      showCue(message.payload || message.text || "Screen Commander ready", message.tone || "info");
      sendResponse({ ok: true });
      return true;
    }
    if (message.type === "screen-commander-hide-cue") {
      hideCue();
      sendResponse({ ok: true });
      return true;
    }
    return false;
  });
}
