#!/opt/homebrew/opt/python@3.11/libexec/bin/python
"""Serve a live localhost review page for screen-commander sessions."""

from __future__ import annotations

import argparse
import html
import json
import mimetypes
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
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Screen Commander Live Review</title>
  <style>
    :root {{
      --bg: #f6f1e8;
      --panel: #fffdf8;
      --ink: #1f2a24;
      --muted: #5f6b62;
      --line: #dccfb9;
      --accent: #12684c;
      --warn: #8a6116;
      --bad: #8f1d1d;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Iowan Old Style", "Palatino Linotype", serif;
      background:
        radial-gradient(circle at top right, rgba(18, 104, 76, 0.08), transparent 28rem),
        linear-gradient(180deg, #f9f5ee, var(--bg));
      color: var(--ink);
    }}
    main {{
      max-width: 1180px;
      margin: 0 auto;
      padding: 28px 20px 56px;
    }}
    .hero, section {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 20px;
      box-shadow: 0 14px 40px rgba(52, 44, 28, 0.08);
      margin-bottom: 20px;
    }}
    .hero-top {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 16px;
      flex-wrap: wrap;
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
    .meta {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 12px;
      margin-top: 16px;
    }}
    .meta-card {{
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 12px;
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
      grid-template-columns: 1.1fr 0.9fr;
      gap: 20px;
    }}
    .image-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
      gap: 16px;
      margin-top: 14px;
    }}
    .image-card {{
      margin: 0;
      border: 1px solid var(--line);
      border-radius: 14px;
      overflow: hidden;
      background: #fff;
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
      gap: 12px;
      flex-wrap: wrap;
      margin-top: 12px;
    }}
    .links a {{
      color: var(--accent);
      text-decoration: none;
      font-weight: 600;
    }}
    ul {{
      margin: 10px 0 0;
      padding-left: 20px;
    }}
    @media (max-width: 920px) {{
      .content {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <main>
    <section class="hero">
      <div class="hero-top">
        <div>
          <h1>Screen Commander Live Review</h1>
          <div class="hint">Session {session_id_html}. This page refreshes itself while the downstream agent task is running.</div>
        </div>
        <span id="badge" class="badge">WAITING</span>
      </div>
      <div class="meta" id="meta"></div>
      <div class="links" id="links"></div>
    </section>
    <div class="content">
      <section>
        <h2>Recognized Transcript</h2>
        <pre id="transcript">Loading…</pre>
        <div id="image-grid" class="image-grid"></div>
      </section>
      <section>
        <h2>Agent Progress</h2>
        <pre id="agent-result">Waiting for agent output…</pre>
        <h3>Recent Agent Events</h3>
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

    function badgeColor(status) {{
      if (status === "completed") return "#12684c";
      if (status === "running") return "#8a6116";
      if (status === "failed") return "#8f1d1d";
      return "#5f6b62";
    }}

    function renderMeta(snapshot) {{
      const review = snapshot.review || {{}};
      const agent = snapshot.agent || {{}};
      const rows = [
        ["Transcript Status", review.transcript_status || "unknown"],
        ["Model", review.model || "unknown"],
        ["Language", review.language || "auto"],
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
      agentResultEl.textContent = agent.result || (status === "running" ? "Agent is still working…" : "No agent result yet.");
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
        renderMeta(snapshot);
        renderLinks(snapshot);
        renderImages(snapshot);
        transcriptEl.textContent = snapshot.review?.transcript || "No transcript available.";
        renderAgent(snapshot);
      }} catch (error) {{
        agentResultEl.textContent = `Live review temporarily unavailable: ${{error.message}}`;
      }}
    }}

    refresh();
    setInterval(refresh, 2000);
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
