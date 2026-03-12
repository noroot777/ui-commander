#!/usr/bin/env python3
"""Serve a live localhost review page for screen-commander sessions."""

from __future__ import annotations

import argparse
import html
import json
import mimetypes
import os
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, unquote

from state_paths import locate_session_dir, migrate_legacy_state, server_info_path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SERVER_INFO_PATH = server_info_path()


def utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path, default: object) -> object:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return default


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def session_dir(session_id: str) -> Path:
    migrate_legacy_state()
    path = locate_session_dir(session_id)
    if path is None:
        return Path("__missing_session__")
    return path


def json_response(handler: BaseHTTPRequestHandler, status: int, payload: object) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body)


def extract_events_tail(path: Path, limit: int = 12) -> list[str]:
    if not path.exists():
        return []
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    tail = lines[-limit:]
    result: list[str] = []
    for raw in tail:
        try:
            payload = json.loads(raw)
        except Exception:  # noqa: BLE001
            result.append(raw[-240:])
            continue
        event_type = payload.get("type")
        if event_type == "item.completed":
            item = payload.get("item", {})
            if item.get("type") == "command_execution":
                command = str(item.get("command") or "").replace("\n", " ")
                if len(command) > 160:
                    command = command[:157] + "..."
                result.append(f"command completed: {command}")
                continue
        result.append(str(event_type or raw[-240:]))
    return result


def codex_thread_info(path: Path) -> dict[str, str] | None:
    if not path.exists():
        return None
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        try:
            payload = json.loads(raw)
        except Exception:  # noqa: BLE001
            continue
        if payload.get("type") == "thread.started":
            thread_id = payload.get("thread_id")
            if isinstance(thread_id, str) and thread_id.strip():
                return {
                    "thread_id": thread_id,
                    "thread_url": f"codex://threads/{thread_id}",
                }
    return None


def file_url(session_id: str, absolute_path: str | None) -> str | None:
    if not absolute_path:
        return None
    path = Path(absolute_path)
    try:
        relative = path.resolve().relative_to(session_dir(session_id).resolve())
    except Exception:  # noqa: BLE001
        return None
    return f"/sessions/{quote(session_id)}/files/{quote(relative.as_posix())}"


def build_snapshot(session_id: str, server_base_url: str) -> dict[str, object]:
    path = session_dir(session_id)
    summary = read_json(path / "summary.json", {})
    review = summary.get("review", {}) if isinstance(summary, dict) and isinstance(summary.get("review"), dict) else {}
    status = read_json(path / "agent-status.json", {})
    transcript_path = path / "transcript.txt"
    transcript = transcript_path.read_text(encoding="utf-8").strip() if transcript_path.exists() else ""
    result_path = path / "agent-result.md"
    result_text = result_path.read_text(encoding="utf-8").strip() if result_path.exists() else ""
    thread_info = codex_thread_info(path / "agent-events.jsonl") or {}
    overlay_images = [
        url for url in (file_url(session_id, item) for item in review.get("overlay_images", [])) if url
    ]
    crop_images = [
        url for url in (file_url(session_id, item) for item in review.get("crop_images", [])) if url
    ]
    keyframes = [
        url for url in (file_url(session_id, item) for item in review.get("keyframes", [])) if url
    ]
    return {
        "session_id": session_id,
        "base_url": server_base_url,
        "extension": summary.get("extension", {}) if isinstance(summary.get("extension"), dict) else {},
        "review": {
            "transcript": transcript or str(review.get("transcript") or ""),
            "overlay_images": overlay_images,
            "crop_images": crop_images,
            "keyframes": keyframes,
            "transcript_status": summary.get("transcript_status"),
            "model": summary.get("transcription", {}).get("model") if isinstance(summary.get("transcription"), dict) else None,
            "language": summary.get("transcription", {}).get("selected_language") if isinstance(summary.get("transcription"), dict) else None,
        },
        "agent": {
            "status": status.get("status") or "pending",
            "mode": status.get("mode"),
            "project_root": status.get("project_root"),
            "thread_id": thread_info.get("thread_id"),
            "thread_url": thread_info.get("thread_url"),
            "started_at": status.get("started_at"),
            "finished_at": status.get("finished_at"),
            "exit_code": status.get("exit_code"),
            "reason": status.get("reason"),
            "workspace_run_dir": status.get("workspace_run_dir"),
            "workspace_progress_md": status.get("workspace_progress_md"),
            "workspace_result_md": status.get("workspace_result_md"),
            "result": result_text,
            "events_tail": extract_events_tail(path / "agent-events.jsonl"),
        },
        "links": {
            "summary_json": file_url(session_id, str(path / "summary.json")),
            "agent_status_json": file_url(session_id, str(path / "agent-status.json")),
            "review_html": file_url(session_id, str(path / "review.html")),
            "agent_result": file_url(session_id, str(path / "agent-result.md")),
            "codex_thread": thread_info.get("thread_url"),
        },
    }


def live_page_html(session_id: str) -> str:
    session_id_json = json.dumps(session_id)
    session_id_html = html.escape(session_id)
    copy_analyze_prefix = json.dumps("使用screen commander分析 ")
    copy_fix_prefix = json.dumps("使用screen commander分析并直接修复 ")
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Screen Commander Live Review</title>
  <style>
    :root {{
      --bg: #efe7da;
      --panel: rgba(255, 252, 245, 0.92);
      --panel-strong: #fffaf1;
      --ink: #18231e;
      --muted: #657166;
      --line: rgba(117, 101, 76, 0.18);
      --accent: #165f46;
      --accent-2: #c86a24;
      --warn: #8a6116;
      --bad: #8f1d1d;
      --shadow: 0 24px 60px rgba(73, 57, 33, 0.12);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Avenir Next", "Segoe UI", sans-serif;
      background:
        radial-gradient(circle at top right, rgba(22, 95, 70, 0.14), transparent 28rem),
        radial-gradient(circle at top left, rgba(200, 106, 36, 0.09), transparent 22rem),
        linear-gradient(180deg, #f9f3e8, var(--bg));
      color: var(--ink);
    }}
    main {{
      max-width: 1240px;
      margin: 0 auto;
      padding: 28px 20px 72px;
    }}
    .hero, section {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 28px;
      padding: 24px;
      box-shadow: var(--shadow);
      backdrop-filter: blur(12px);
      margin-bottom: 20px;
    }}
    .hero {{
      padding: 28px;
    }}
    .hero-top {{
      display: grid;
      grid-template-columns: minmax(0, 1.35fr) minmax(360px, 420px);
      align-items: start;
      gap: 24px;
    }}
    .hero-copy {{
      min-width: 0;
      display: flex;
      flex-direction: column;
      gap: 18px;
    }}
    .hero h1 {{
      margin: 0;
      font-family: "Iowan Old Style", "Palatino Linotype", serif;
      font-size: clamp(42px, 6vw, 64px);
      line-height: 0.95;
      letter-spacing: -0.04em;
    }}
    .hero-lead {{
      max-width: 720px;
      margin-top: 6px;
      color: var(--muted);
      font-size: 18px;
      line-height: 1.6;
    }}
    .hero-session {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 8px 12px;
      border-radius: 999px;
      border: 1px solid rgba(22, 95, 70, 0.18);
      background: rgba(22, 95, 70, 0.06);
      color: var(--accent);
      font-size: 13px;
      font-weight: 700;
      letter-spacing: 0.04em;
      text-transform: uppercase;
    }}
    .badge {{
      display: inline-block;
      padding: 8px 12px;
      border-radius: 999px;
      color: #fff;
      font-weight: 700;
      letter-spacing: 0.04em;
      background: var(--muted);
    }}
    .hero-actions {{
      display: flex;
      flex-direction: column;
      align-items: stretch;
      gap: 14px;
      min-width: min(100%, 380px);
      max-width: 420px;
      padding: 18px;
      border-radius: 24px;
      border: 1px solid rgba(22, 95, 70, 0.16);
      background:
        linear-gradient(180deg, rgba(255, 255, 255, 0.82), rgba(246, 240, 229, 0.88)),
        radial-gradient(circle at top right, rgba(22, 95, 70, 0.08), transparent 16rem);
    }}
    .action-header {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
    }}
    .action-title {{
      font-size: 15px;
      font-weight: 800;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: var(--muted);
    }}
    .action-buttons {{
      display: grid;
      gap: 12px;
    }}
    .copy-button {{
      appearance: none;
      border: 0;
      border-radius: 18px;
      background: linear-gradient(135deg, #12684c, #1b8a64);
      color: #fffdf8;
      font-size: 18px;
      font-weight: 800;
      line-height: 1.2;
      padding: 18px 20px;
      width: 100%;
      box-shadow: 0 18px 34px rgba(18, 104, 76, 0.26);
      cursor: pointer;
      transition: transform 120ms ease, box-shadow 120ms ease, filter 120ms ease;
      text-align: left;
    }}
    .copy-button strong {{
      display: block;
      font-size: 20px;
      margin-bottom: 4px;
    }}
    .copy-button span {{
      display: block;
      font-size: 13px;
      opacity: 0.88;
      font-weight: 600;
    }}
    .copy-button:hover {{
      transform: translateY(-1px);
      box-shadow: 0 22px 36px rgba(18, 104, 76, 0.30);
      filter: brightness(1.03);
    }}
    .copy-button:active {{
      transform: translateY(0);
    }}
    .copy-button.secondary {{
      background: linear-gradient(135deg, #b95f23, #d27a31);
      box-shadow: 0 18px 34px rgba(185, 95, 35, 0.22);
    }}
    .copy-help {{
      color: var(--muted);
      font-size: 13px;
      line-height: 1.6;
    }}
    .copy-preview {{
      border-radius: 16px;
      border: 1px dashed rgba(22, 95, 70, 0.2);
      background: rgba(255, 255, 255, 0.7);
      padding: 12px 14px;
      color: var(--ink);
      font-size: 13px;
      line-height: 1.6;
      word-break: break-word;
    }}
    .copy-preview-label {{
      display: block;
      margin-bottom: 6px;
      color: var(--muted);
      font-size: 11px;
      font-weight: 800;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }}
    .copy-status {{
      min-height: 20px;
      color: var(--accent);
      font-size: 13px;
      font-weight: 700;
    }}
    .warning-banner {{
      border-radius: 18px;
      border: 1px solid rgba(185, 95, 35, 0.26);
      background: linear-gradient(180deg, rgba(255, 247, 238, 0.96), rgba(255, 241, 228, 0.92));
      box-shadow: 0 14px 30px rgba(185, 95, 35, 0.10);
      padding: 14px 16px;
      color: #7b4518;
    }}
    .warning-banner strong {{
      display: block;
      margin-bottom: 4px;
      font-size: 15px;
    }}
    .warning-banner span {{
      display: block;
      font-size: 13px;
      line-height: 1.6;
    }}
    .meta {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 14px;
      margin-top: 2px;
    }}
    .meta-card {{
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 14px;
      background: rgba(18, 104, 76, 0.03);
    }}
    .label {{
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--muted);
      margin-bottom: 6px;
    }}
    .value {{
      font-size: 16px;
      font-weight: 600;
      word-break: break-word;
      white-space: pre-wrap;
    }}
    .hint {{
      color: var(--muted);
      margin-top: 8px;
      font-size: 14px;
    }}
    .content {{
      display: grid;
      grid-template-columns: minmax(0, 1.15fr) minmax(320px, 0.85fr);
      gap: 20px;
    }}
    .section-title {{
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      gap: 12px;
      margin-bottom: 14px;
    }}
    .section-title h2 {{
      margin: 0;
      font-family: "Iowan Old Style", "Palatino Linotype", serif;
      font-size: 26px;
      letter-spacing: -0.03em;
    }}
    .section-kicker {{
      color: var(--muted);
      font-size: 12px;
      font-weight: 800;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }}
    .image-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
      gap: 18px;
      margin-top: 14px;
    }}
    .image-card {{
      margin: 0;
      border: 1px solid var(--line);
      border-radius: 18px;
      overflow: hidden;
      background: #fff;
      box-shadow: 0 12px 26px rgba(52, 44, 28, 0.06);
    }}
    .image-card img {{
      display: block;
      width: 100%;
      height: auto;
      background: #efe8da;
    }}
    figcaption {{
      padding: 10px 12px 12px;
      color: var(--muted);
      font-size: 13px;
    }}
    pre {{
      margin: 0;
      white-space: pre-wrap;
      word-break: break-word;
      line-height: 1.6;
      font-size: 15px;
    }}
    .links {{
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      margin-top: 2px;
    }}
    .links a {{
      color: var(--accent);
      text-decoration: none;
      font-weight: 700;
      padding: 8px 12px;
      border-radius: 999px;
      background: rgba(22, 95, 70, 0.07);
      border: 1px solid rgba(22, 95, 70, 0.08);
    }}
    ul {{
      margin: 10px 0 0;
      padding-left: 20px;
    }}
    @media (max-width: 920px) {{
      .hero-top {{
        grid-template-columns: 1fr;
      }}
      .content {{ grid-template-columns: 1fr; }}
      .hero-actions {{
        max-width: none;
        width: 100%;
      }}
    }}
    @media (max-width: 720px) {{
      main {{
        padding: 18px 14px 48px;
      }}
      .hero, section {{
        border-radius: 22px;
        padding: 18px;
      }}
      .hero h1 {{
        font-size: 40px;
      }}
    }}
  </style>
</head>
<body>
  <main>
    <section class="hero">
      <div class="hero-top">
        <div class="hero-copy">
          <h1>Screen Commander Live Review</h1>
          <div class="hero-lead">先在这里确认轨迹、转写和热点区域，再一键把“分析”或“直接修复”的提示词连同 session URL 复制到 IDE 对话里。</div>
          <div class="hero-session">Session {session_id_html}</div>
          <div id="extension-warning" class="warning-banner" hidden></div>
          <div class="meta" id="meta"></div>
          <div class="links" id="links"></div>
        </div>
        <div class="hero-actions">
          <div class="action-header">
            <div class="action-title">Quick Trigger</div>
            <span id="badge" class="badge">WAITING</span>
          </div>
          <div class="action-buttons">
            <button id="copy-analyze-button" class="copy-button" type="button">
              <strong>复制分析提示词 + URL</strong>
              <span>粘贴后进入 `screen-commander` 分析流程</span>
            </button>
            <button id="copy-fix-button" class="copy-button secondary" type="button">
              <strong>复制直接修复提示词 + URL</strong>
              <span>粘贴后明确表达“分析并直接修复”</span>
            </button>
          </div>
          <div class="copy-help">推荐：不想来回解释时，直接复制按钮里的完整提示词，去 IDE 粘贴。</div>
          <div class="copy-preview"><span class="copy-preview-label">即将复制的提示词</span><span id="copy-preview-text">加载中…</span></div>
          <div id="copy-status" class="copy-status"></div>
        </div>
      </div>
    </section>
    <div class="content">
      <section>
        <div class="section-title">
          <h2>识别结果</h2>
          <div class="section-kicker">旁白 + 轨迹热点</div>
        </div>
        <pre id="transcript">Loading…</pre>
        <div id="image-grid" class="image-grid"></div>
      </section>
      <section>
        <div class="section-title">
          <h2>处理进度</h2>
          <div class="section-kicker">下游执行状态</div>
        </div>
        <pre id="agent-result">Waiting for agent output…</pre>
        <h3>最近事件</h3>
        <ul id="agent-events"></ul>
      </section>
    </div>
  </main>
  <script>
    const sessionId = {session_id_json};
    const metaEl = document.getElementById("meta");
    const linksEl = document.getElementById("links");
    const transcriptEl = document.getElementById("transcript");
    const imageGridEl = document.getElementById("image-grid");
    const agentResultEl = document.getElementById("agent-result");
    const agentEventsEl = document.getElementById("agent-events");
    const badgeEl = document.getElementById("badge");
    const extensionWarningEl = document.getElementById("extension-warning");
    const copyAnalyzeButtonEl = document.getElementById("copy-analyze-button");
    const copyFixButtonEl = document.getElementById("copy-fix-button");
    const copyStatusEl = document.getElementById("copy-status");
    const copyPreviewTextEl = document.getElementById("copy-preview-text");

    function promptWithUrl(mode) {{
      const prefix = mode === "fix" ? {copy_fix_prefix} : {copy_analyze_prefix};
      return prefix + window.location.href;
    }}

    async function copyPromptWithUrl(mode) {{
      const text = promptWithUrl(mode);
      try {{
        if (navigator.clipboard?.writeText) {{
          await navigator.clipboard.writeText(text);
        }} else {{
          const textarea = document.createElement("textarea");
          textarea.value = text;
          textarea.setAttribute("readonly", "true");
          textarea.style.position = "fixed";
          textarea.style.opacity = "0";
          document.body.appendChild(textarea);
          textarea.focus();
          textarea.select();
          document.execCommand("copy");
          document.body.removeChild(textarea);
        }}
        copyPreviewTextEl.textContent = text;
        copyStatusEl.textContent = mode === "fix"
          ? "已复制“直接修复”提示词，去 IDE 里粘贴。"
          : "已复制“分析”提示词，去 IDE 里粘贴。";
      }} catch (error) {{
        copyStatusEl.textContent = "复制失败，请手动复制当前页面 URL。";
      }}
    }}

    function badgeColor(status) {{
      if (status === "completed") return "#12684c";
      if (status === "running") return "#8a6116";
      if (status === "failed") return "#8f1d1d";
      return "#5f6b62";
    }}

    function renderMeta(snapshot) {{
      const review = snapshot.review || {{}};
      const agent = snapshot.agent || {{}};
      const extension = snapshot.extension || {{}};
      const extensionValue = extension.recorded_version
        ? (extension.reload_required && extension.expected_version
            ? `${{extension.recorded_version}} -> ${{extension.expected_version}}`
            : extension.recorded_version)
        : "unknown";
      const rows = [
        ["Transcript Status", review.transcript_status || "unknown"],
        ["Model", review.model || "unknown"],
        ["Language", review.language || "auto"],
        ["Extension", extensionValue],
        ["Agent Status", agent.status || "pending"],
        ["Mode", agent.mode || "unknown"],
        ["Project", agent.project_root || "not configured"],
        ["Codex Thread", agent.thread_id || "n/a"],
        ["Workspace Run", agent.workspace_run_dir || "n/a"],
      ];
      metaEl.innerHTML = rows.map(([label, value]) => `
        <div class="meta-card">
          <div class="label">${{label}}</div>
          <div class="value">${{value ?? "n/a"}}</div>
        </div>
      `).join("");
    }}

    function renderExtensionWarning(snapshot) {{
      const extension = snapshot.extension || {{}};
      if (!extension.reload_required) {{
        extensionWarningEl.hidden = true;
        extensionWarningEl.innerHTML = "";
        return;
      }}
      const recordedVersion = extension.recorded_version || "unknown";
      const expectedVersion = extension.expected_version || "unknown";
      extensionWarningEl.hidden = false;
      extensionWarningEl.innerHTML = `
        <strong>Chrome 里的扩展还是旧版本</strong>
        <span>这条 session 是用 ${{recordedVersion}} 录的，但当前 skill 已经是 ${{expectedVersion}}。去 ` + "`chrome://extensions`" + ` 点一下 Reload，再录下一条。</span>
      `;
    }}

    function renderLinks(snapshot) {{
      const links = snapshot.links || {{}};
      const rows = [
        ["summary.json", links.summary_json],
        ["agent-status.json", links.agent_status_json],
        ["static review", links.review_html],
        ["agent-result.md", links.agent_result],
        ["Codex thread", links.codex_thread],
      ].filter(([, href]) => !!href);
      linksEl.innerHTML = rows.map(([label, href]) => `<a href="${{href}}" target="_blank" rel="noreferrer">${{label}}</a>`).join("");
    }}

    function renderImages(snapshot) {{
      const review = snapshot.review || {{}};
      const images = [
        ...(review.overlay_images || []),
        ...(review.crop_images || []),
        ...(review.keyframes || []),
      ];
      imageGridEl.innerHTML = images.map((src) => `
        <figure class="image-card">
          <img src="${{src}}" alt="session artifact">
          <figcaption>${{src.split("/").pop()}}</figcaption>
        </figure>
      `).join("");
    }}

    function renderAgent(snapshot) {{
      const agent = snapshot.agent || {{}};
      const status = agent.status || "pending";
      badgeEl.textContent = status.toUpperCase();
      badgeEl.style.background = badgeColor(status);
      agentResultEl.textContent = agent.result || (status === "running" ? "正在继续处理这条 session…" : "还没有生成结果。");
      const events = agent.events_tail || [];
      agentEventsEl.innerHTML = events.length
        ? events.map((event) => `<li>${{event}}</li>`).join("")
        : "<li>No agent events yet.</li>";
    }}

    async function refresh() {{
      try {{
        const response = await fetch(`/api/sessions/${{encodeURIComponent(sessionId)}}/snapshot`, {{ cache: "no-store" }});
        if (!response.ok) throw new Error(`HTTP ${{response.status}}`);
        const snapshot = await response.json();
        renderExtensionWarning(snapshot);
        renderMeta(snapshot);
        renderLinks(snapshot);
        renderImages(snapshot);
        transcriptEl.textContent = snapshot.review?.transcript || "还没有可用转写。";
        renderAgent(snapshot);
      }} catch (error) {{
        agentResultEl.textContent = `Live review 暂时不可用：${{error.message}}`;
      }}
    }}

    refresh();
    setInterval(refresh, 2000);
    copyPreviewTextEl.textContent = promptWithUrl("analyze");
    copyAnalyzeButtonEl.addEventListener("click", () => copyPromptWithUrl("analyze"));
    copyFixButtonEl.addEventListener("click", () => copyPromptWithUrl("fix"));
  </script>
</body>
</html>
"""


class SessionServer(ThreadingHTTPServer):
    def __init__(self, server_address: tuple[str, int], idle_timeout: int) -> None:
        super().__init__(server_address, SessionServerHandler)
        self.idle_timeout = idle_timeout
        self.last_request_monotonic = time.monotonic()


class SessionServerHandler(BaseHTTPRequestHandler):
    server: SessionServer

    def log_message(self, format: str, *args: object) -> None:  # noqa: A003
        return

    def do_GET(self) -> None:  # noqa: N802
        self.server.last_request_monotonic = time.monotonic()
        path = self.path.split("?", 1)[0]
        if path == "/health":
            json_response(self, HTTPStatus.OK, {"ok": True})
            return
        if path.startswith("/api/sessions/") and path.endswith("/snapshot"):
            session_id = unquote(path[len("/api/sessions/") : -len("/snapshot")]).strip("/")
            if not session_dir(session_id).exists():
                json_response(self, HTTPStatus.NOT_FOUND, {"error": "session not found"})
                return
            port = self.server.server_address[1]
            json_response(self, HTTPStatus.OK, build_snapshot(session_id, f"http://127.0.0.1:{port}"))
            return
        if path.startswith("/sessions/") and path.endswith("/live"):
            session_id = unquote(path[len("/sessions/") : -len("/live")]).strip("/")
            if not session_dir(session_id).exists():
                self.send_error(HTTPStatus.NOT_FOUND, "session not found")
                return
            body = live_page_html(session_id).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        if path.startswith("/sessions/") and "/files/" in path:
            session_id_encoded, rel_path_encoded = path[len("/sessions/") :].split("/files/", 1)
            session_id = unquote(session_id_encoded).strip("/")
            base_dir = session_dir(session_id).resolve()
            rel_path = Path(unquote(rel_path_encoded))
            target = (base_dir / rel_path).resolve()
            try:
                target.relative_to(base_dir)
            except Exception:  # noqa: BLE001
                self.send_error(HTTPStatus.FORBIDDEN, "invalid path")
                return
            if not target.exists() or not target.is_file():
                self.send_error(HTTPStatus.NOT_FOUND, "file not found")
                return
            body = target.read_bytes()
            content_type, _ = mimetypes.guess_type(str(target))
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type or "application/octet-stream")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_error(HTTPStatus.NOT_FOUND, "not found")


def bind_server(preferred_port: int, idle_timeout: int) -> SessionServer:
    try:
        return SessionServer(("127.0.0.1", preferred_port), idle_timeout)
    except OSError:
        if preferred_port == 0:
            raise
        return SessionServer(("127.0.0.1", 0), idle_timeout)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--port", type=int, default=47321)
    run_parser.add_argument("--idle-timeout", type=int, default=1800)
    return parser.parse_args()


def main() -> int:
    migrate_legacy_state()
    args = parse_args()
    if args.command != "run":
        return 1
    server = bind_server(args.port, args.idle_timeout)
    host, port = server.server_address
    write_json(
        SERVER_INFO_PATH,
        {
            "host": host,
            "port": port,
            "base_url": f"http://{host}:{port}",
            "started_at": utc_now(),
            "idle_timeout": args.idle_timeout,
            "pid": os.getpid(),
            "script_mtime_ns": Path(__file__).stat().st_mtime_ns,
        },
    )
    while True:
        server.timeout = 1
        server.handle_request()
        if time.monotonic() - server.last_request_monotonic > server.idle_timeout:
            break
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
