#!/usr/bin/env python3
"""Run an automatic agent task for a finalized ui-commander session."""

from __future__ import annotations

import argparse
import html
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from preferences_store import read_preferences
from runtime_state import read_runtime_state
from state_paths import latest_session_dir as latest_shared_session_dir, locate_session_dir, migrate_legacy_state, sessions_dir


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SESSIONS_DIR = sessions_dir()
CODEX_BIN = shutil.which("codex") or "/Applications/Codex.app/Contents/Resources/codex"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path, default: object) -> object:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def try_open_local_file(path: Path) -> bool:
    try:
        subprocess.run(["open", str(path)], check=False, capture_output=True)
        return True
    except Exception:  # noqa: BLE001
        return False


def codex_thread_info(events_path: Path) -> dict[str, str] | None:
    if not events_path.exists():
        return None
    for raw_line in events_path.read_text(encoding="utf-8").splitlines():
        if not raw_line.strip():
            continue
        try:
            payload = json.loads(raw_line)
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


def latest_session_dir() -> Path:
    migrate_legacy_state()
    latest = latest_shared_session_dir()
    if latest is None:
        raise FileNotFoundError("No sessions found.")
    return latest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--session", help="session id to process")
    return parser.parse_args()


def prompt_for(session_dir: Path, request: dict) -> str:
    mode = request["mode"]
    summary = request["artifacts"]["summary"]
    focus_regions = request["artifacts"]["focus_regions"]
    transcript = request["artifacts"]["transcript"]
    review_html = request["artifacts"]["review_html"]
    result_lines = [
        "A UI Commander session has just finished.",
        f"Read {summary}.",
        f"Then inspect {focus_regions}, {transcript}, and {review_html}.",
        "Use the overlay images referenced in summary.review.overlay_images as the visual source of truth.",
    ]
    if mode == "apply":
        result_lines.extend(
            [
                "Recover the user's intended frontend change from the session artifacts.",
                "Then modify the current project to implement that change.",
                "Run the narrowest useful verification you can.",
                "Write a concise summary of what changed and the verification result.",
            ]
        )
    else:
        result_lines.extend(
            [
                "Do not modify code.",
                "Produce a concise analysis of what the user likely wants changed, what files are likely involved, and any ambiguity.",
            ]
        )
    return "\n".join(result_lines)


def build_request(session_dir: Path, preferences: dict) -> dict:
    summary_path = session_dir / "summary.json"
    summary = read_json(summary_path, {})
    orchestrator = preferences.get("orchestrator", {}) if isinstance(preferences.get("orchestrator"), dict) else {}
    runtime_state = read_runtime_state()
    active_project_root = runtime_state.get("active_project_root")
    review = summary.get("review", {}) if isinstance(summary.get("review"), dict) else {}
    configured_project_root = orchestrator.get("project_root")
    effective_project_root = (
        str(active_project_root).strip()
        if isinstance(active_project_root, str) and active_project_root.strip()
        else str(Path.cwd())
        if configured_project_root in {None, "", "auto"}
        else str(configured_project_root)
    )
    return {
        "created_at": utc_now(),
        "session_id": session_dir.name,
        "provider": orchestrator.get("provider", "codex-cli"),
        "mode": orchestrator.get("mode", "suggest"),
        "project_root": effective_project_root,
        "configured_project_root": configured_project_root,
        "artifacts": {
            "summary": str(summary_path),
            "focus_regions": str(session_dir / "focus_regions.json"),
            "transcript": str(session_dir / "transcript.txt"),
            "segments": str(session_dir / "segments.json"),
            "intent_evidence": str(session_dir / "intent_evidence.json"),
            "intent_resolution": str(session_dir / "intent_resolution.json"),
            "review_html": str((session_dir / "review.html")),
            "overlay_images": review.get("overlay_images", []),
        },
    }


def workspace_run_dir(project_root: Path, session_id: str) -> Path:
    return project_root / ".ui-commander" / "runs" / session_id


def copy_if_exists(source: Path, destination: Path) -> Path | None:
    if not source.exists():
        return None
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return destination


def copy_review_assets(session_dir: Path, workspace_dir: Path, summary: dict) -> dict[str, list[str] | str | None]:
    review = summary.get("review", {}) if isinstance(summary.get("review"), dict) else {}
    assets_dir = workspace_dir / "assets"
    overlays: list[str] = []
    crops: list[str] = []
    keyframes: list[str] = []

    transcript_path = copy_if_exists(session_dir / "transcript.txt", workspace_dir / "transcript.txt")
    for item in review.get("overlay_images", []):
        copied = copy_if_exists(Path(item), assets_dir / Path(item).name)
        if copied:
            overlays.append(str(copied.relative_to(workspace_dir)))
    for item in review.get("crop_images", []):
        copied = copy_if_exists(Path(item), assets_dir / Path(item).name)
        if copied:
            crops.append(str(copied.relative_to(workspace_dir)))
    for item in review.get("keyframes", []):
        copied = copy_if_exists(Path(item), assets_dir / Path(item).name)
        if copied:
            keyframes.append(str(copied.relative_to(workspace_dir)))

    return {
        "transcript_path": str(transcript_path.relative_to(workspace_dir)) if transcript_path else None,
        "overlay_paths": overlays,
        "crop_paths": crops,
        "keyframe_paths": keyframes,
    }


def run_git(project_root: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(project_root), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def current_repo_status(project_root: Path) -> dict[str, object]:
    status_result = run_git(project_root, ["status", "--porcelain=v1"])
    diff_name_result = run_git(project_root, ["diff", "--name-only"])
    untracked_result = run_git(project_root, ["ls-files", "--others", "--exclude-standard"])
    return {
        "git_available": status_result.returncode == 0,
        "status_lines": [line for line in status_result.stdout.splitlines() if line.strip()],
        "diff_files": [line for line in diff_name_result.stdout.splitlines() if line.strip()],
        "untracked_files": [line for line in untracked_result.stdout.splitlines() if line.strip()],
    }


def current_repo_diff(project_root: Path) -> str:
    result = run_git(project_root, ["diff", "--no-ext-diff", "--binary"])
    return result.stdout if result.returncode == 0 else ""


def format_bullets(items: list[str], empty_text: str) -> str:
    if not items:
        return f"- {empty_text}"
    return "\n".join(f"- {item}" for item in items)


def summarize_agent_event(raw_line: str) -> str:
    try:
        payload = json.loads(raw_line)
    except Exception:  # noqa: BLE001
        return raw_line

    event_type = payload.get("type")
    if event_type == "thread.started":
        thread_id = payload.get("thread_id") or "unknown"
        return f"Started Codex thread `{thread_id}`"

    item = payload.get("item") if isinstance(payload.get("item"), dict) else {}
    item_type = item.get("type")
    status = item.get("status")

    if item_type == "agent_message":
        text = str(item.get("text") or "").strip()
        if len(text) > 140:
            text = text[:137] + "..."
        return text or "Agent posted an update"

    if item_type == "command_execution":
        command = str(item.get("command") or "").strip()
        if len(command) > 110:
            command = command[:107] + "..."
        prefix = "Running" if status == "in_progress" or event_type == "item.started" else "Finished"
        return f"{prefix} command: `{command}`"

    if event_type == "turn.completed":
        return "Agent turn completed"

    if event_type == "turn.failed":
        return "Agent turn failed"

    if event_type == "item.completed":
        return "Agent step completed"

    if event_type == "item.started":
        return "Agent step started"

    return raw_line if len(raw_line) <= 140 else raw_line[:137] + "..."


def write_workspace_links(
    workspace_dir: Path,
    *,
    session_dir: Path,
    summary: dict,
    status: dict,
    request: dict,
    progress_path: Path,
    result_path: Path,
) -> None:
    payload = {
        "session_dir": str(session_dir),
        "summary_json": str(session_dir / "summary.json"),
        "review_html": str(session_dir / "review.html"),
        "agent_status_json": str(session_dir / "agent-status.json"),
        "agent_result_md": str(session_dir / "agent-result.md"),
        "live_review_url": summary.get("live_review", {}).get("live_review_url") if isinstance(summary.get("live_review"), dict) else None,
        "codex_thread": status.get("thread_url"),
        "workspace_progress_md": str(progress_path),
        "workspace_result_md": str(result_path),
        "mode": request.get("mode"),
    }
    write_json(workspace_dir / "links.json", payload)


def write_workspace_recording_md(
    workspace_dir: Path,
    *,
    session_dir: Path,
    summary: dict,
    request: dict,
    asset_paths: dict[str, list[str] | str | None],
) -> Path:
    review = summary.get("review", {}) if isinstance(summary.get("review"), dict) else {}
    live_review_url = summary.get("live_review", {}).get("live_review_url") if isinstance(summary.get("live_review"), dict) else None
    transcript = str(review.get("transcript") or "")
    transcript_preview = transcript.strip() or "No transcript available."
    content = f"""# UI Commander Recording

## Summary

- Session: `{session_dir.name}`
- Mode: `{request.get("mode")}`
- Project: `{request.get("project_root")}`
- Live review: {live_review_url or "not available"}

## Transcript

{transcript_preview}

## Review Assets

- Transcript copy: {asset_paths.get("transcript_path") or "not copied"}
- Overlay images:
{format_bullets(list(asset_paths.get("overlay_paths") or []), "No overlay images copied")}
- Focus crops:
{format_bullets(list(asset_paths.get("crop_paths") or []), "No crop images copied")}
- Keyframes:
{format_bullets(list(asset_paths.get("keyframe_paths") or []), "No keyframes copied")}
"""
    path = workspace_dir / "recording.md"
    write_text(path, content)
    return path


def write_workspace_progress_md(
    workspace_dir: Path,
    *,
    session_dir: Path,
    summary: dict,
    status: dict,
    request: dict,
) -> Path:
    live_review_url = summary.get("live_review", {}).get("live_review_url") if isinstance(summary.get("live_review"), dict) else None
    events_path = session_dir / "agent-events.jsonl"
    events_tail = []
    if events_path.exists():
        lines = [line for line in events_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        events_tail = [summarize_agent_event(line) for line in lines[-5:]]
    content = f"""# UI Commander Agent Progress

## Status

- Session: `{session_dir.name}`
- Status: `{status.get("status", "pending")}`
- Mode: `{status.get("mode") or request.get("mode") or "unknown"}`
- Project: `{status.get("project_root") or request.get("project_root") or "not configured"}`
- Current step: {status.get("reason") or "n/a"}
- Live review: {live_review_url or "not available"}
- Codex thread: {status.get("thread_url") or "not available"}

## Timing

- Started: `{status.get("started_at") or "n/a"}`
- Finished: `{status.get("finished_at") or "n/a"}`
- Exit code: `{status.get("exit_code") if status.get("exit_code") is not None else "n/a"}`

## Recent Events

{format_bullets(events_tail, "No agent events recorded yet")}
"""
    path = workspace_dir / "agent-progress.md"
    write_text(path, content)
    return path


def write_workspace_result_md(
    workspace_dir: Path,
    *,
    session_dir: Path,
    status: dict,
    request: dict,
) -> Path:
    result_path = session_dir / "agent-result.md"
    result_body = result_path.read_text(encoding="utf-8").strip() if result_path.exists() else "No agent result yet."
    content = f"""# UI Commander Agent Result

## Top Line

- Session: `{session_dir.name}`
- Status: `{status.get("status", "pending")}`
- Mode: `{status.get("mode") or request.get("mode") or "unknown"}`
- Project: `{status.get("project_root") or request.get("project_root") or "not configured"}`
- Exit code: `{status.get("exit_code") if status.get("exit_code") is not None else "n/a"}`
- Codex thread: {status.get("thread_url") or "not available"}

## Result

{result_body}
"""
    path = workspace_dir / "agent-result.md"
    write_text(path, content)
    return path


def write_apply_workspace_artifacts(
    workspace_dir: Path,
    *,
    project_root: Path,
    before_snapshot: dict[str, object],
    after_snapshot: dict[str, object],
    status: dict,
) -> None:
    before_lines = set(before_snapshot.get("status_lines", []))
    after_lines = set(after_snapshot.get("status_lines", []))
    payload = {
        "note": "This is based on repository state before and after the run. If the repo already had local changes, treat this as the current diff-oriented view, not guaranteed agent-only attribution.",
        "before_status_lines": sorted(before_lines),
        "after_status_lines": sorted(after_lines),
        "status_delta": sorted(after_lines - before_lines),
        "diff_files": sorted(set(after_snapshot.get("diff_files", []))),
        "untracked_files": sorted(set(after_snapshot.get("untracked_files", []))),
        "status": status.get("status"),
        "exit_code": status.get("exit_code"),
    }
    write_json(workspace_dir / "changed-files.json", payload)
    write_json(
        workspace_dir / "verification.json",
        {
            "status": status.get("status"),
            "exit_code": status.get("exit_code"),
            "finished_at": status.get("finished_at"),
            "note": "Verification details are summarized by the downstream agent in agent-result.md.",
        },
    )
    write_text(workspace_dir / "patch.diff", current_repo_diff(project_root))


def write_status(path: Path, **fields: object) -> None:
    payload = read_json(path, {})
    if not isinstance(payload, dict):
        payload = {}
    for key, value in fields.items():
        if value is None and key in payload:
            payload.pop(key, None)
        else:
            payload[key] = value
    write_json(path, payload)


def reset_terminal_status_fields(status_path: Path) -> None:
    write_status(
        status_path,
        project_root=None,
        started_at=None,
        exit_code=None,
        command=None,
        request_path=None,
        output_path=None,
        events_path=None,
        provider=None,
        mode=None,
    )


def write_agent_review_html(session_dir: Path) -> Path:
    status_path = session_dir / "agent-status.json"
    request_path = session_dir / "agent-request.json"
    result_path = session_dir / "agent-result.md"
    summary_path = session_dir / "summary.json"
    review_path = session_dir / "review.html"

    status = read_json(status_path, {})
    request = read_json(request_path, {})
    summary = read_json(summary_path, {})
    review = summary.get("review", {}) if isinstance(summary.get("review"), dict) else {}
    transcript = str(review.get("transcript") or "")
    thread_info = codex_thread_info(session_dir / "agent-events.jsonl") or {}
    overlay_images = [str(item) for item in review.get("overlay_images", []) if item]
    current_status = str(status.get("status") or "pending")
    current_reason = str(status.get("reason") or "")
    result_text = ""
    if current_status in {"completed", "failed"} and result_path.exists():
        result_text = result_path.read_text(encoding="utf-8").strip()
    badge_color = {
        "running": "#8a6116",
        "completed": "#12684c",
        "failed": "#8f1d1d",
        "skipped": "#5f6b62",
    }.get(current_status, "#5f6b62")
    auto_refresh = current_status == "running"
    meta_refresh = '<meta http-equiv="refresh" content="3">' if auto_refresh else ""

    image_cards = "\n".join(
        (
            '<figure class="image-card">'
            f'<img src="{html.escape(Path(image).name)}" alt="overlay image">'
            f'<figcaption>{html.escape(Path(image).name)}</figcaption>'
            "</figure>"
        )
        for image in overlay_images
        if Path(image).exists()
    )

    project_value = str(status.get("project_root") or request.get("project_root") or "not configured")
    if current_reason == "project_root is not configured":
        project_value = "not configured"
    details_rows = [
        ("Status", current_status),
        ("Mode", str(status.get("mode") or request.get("mode") or "unknown")),
        ("Project", project_value),
        ("Codex Thread", str(thread_info.get("thread_id") or "n/a")),
        ("Started", str(status.get("started_at") or "n/a")),
        ("Finished", str(status.get("finished_at") or "n/a")),
        ("Exit Code", str(status.get("exit_code") if status.get("exit_code") is not None else "n/a")),
        ("Reason", current_reason or "n/a"),
    ]
    detail_html = "\n".join(
        f'<div class="meta-card"><div class="label">{html.escape(label)}</div><div class="value">{html.escape(value)}</div></div>'
        for label, value in details_rows
    )

    result_html = html.escape(result_text) if result_text else "No agent result yet."
    transcript_html = html.escape(transcript) if transcript else "No transcript available."
    image_grid_html = f'<div class="image-grid">{image_cards}</div>' if image_cards else ""
    thread_link_html = (
        f'<a href="{html.escape(str(thread_info["thread_url"]))}">Open Codex thread</a>'
        if thread_info.get("thread_url")
        else ""
    )
    page = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  {meta_refresh}
  <title>UI Commander Agent Status</title>
  <style>
    :root {{
      --bg: #f6f1e8;
      --panel: #fffdf8;
      --ink: #1f2a24;
      --muted: #5f6b62;
      --line: #dccfb9;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Iowan Old Style", "Palatino Linotype", serif;
      background:
        radial-gradient(circle at top left, rgba(18, 104, 76, 0.08), transparent 28rem),
        linear-gradient(180deg, #f9f5ee, var(--bg));
      color: var(--ink);
    }}
    main {{
      max-width: 1180px;
      margin: 0 auto;
      padding: 32px 24px 64px;
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
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      flex-wrap: wrap;
    }}
    .badge {{
      display: inline-block;
      padding: 8px 12px;
      border-radius: 999px;
      background: {badge_color};
      color: white;
      font-weight: 700;
      letter-spacing: 0.04em;
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
    }}
    .hint {{
      color: var(--muted);
      margin-top: 10px;
      font-size: 14px;
    }}
    .links {{
      display: flex;
      gap: 12px;
      flex-wrap: wrap;
      margin-top: 14px;
    }}
    .links a {{
      color: #12684c;
      text-decoration: none;
      font-weight: 600;
    }}
    .content {{
      display: grid;
      grid-template-columns: 1.1fr 0.9fr;
      gap: 20px;
    }}
    pre {{
      white-space: pre-wrap;
      word-break: break-word;
      margin: 0;
      font-size: 15px;
      line-height: 1.6;
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
    @media (max-width: 900px) {{
      .content {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <main>
    <section class="hero">
      <div class="hero-top">
        <div>
          <h1>UI Commander Agent Status</h1>
          <p class="hint">This page refreshes automatically while the downstream agent task is running.</p>
        </div>
        <span class="badge">{html.escape(current_status.upper())}</span>
      </div>
      <div class="meta">{detail_html}</div>
      <div class="links">
        <a href="{html.escape(review_path.name)}">Open recording review</a>
        <a href="{html.escape(summary_path.name)}">Open summary.json</a>
        <a href="{html.escape(status_path.name)}">Open agent-status.json</a>
        {thread_link_html}
      </div>
    </section>
    <div class="content">
      <section>
        <h2>Agent Result</h2>
        <pre>{result_html}</pre>
      </section>
      <section>
        <h2>Transcript Snapshot</h2>
        <pre>{transcript_html}</pre>
        {image_grid_html}
      </section>
    </div>
  </main>
</body>
</html>
"""
    agent_review_path = session_dir / "agent-review.html"
    agent_review_path.write_text(page, encoding="utf-8")
    return agent_review_path


def run_codex_cli(session_dir: Path, request: dict, status_path: Path) -> None:
    project_root = request.get("project_root")
    if not isinstance(project_root, str) or not project_root.strip():
        reset_terminal_status_fields(status_path)
        write_status(
            status_path,
            status="skipped",
            reason="project_root is not configured",
            project_root=None,
            started_at=None,
            exit_code=None,
            finished_at=utc_now(),
        )
        write_agent_review_html(session_dir)
        return

    codex_bin = Path(CODEX_BIN)
    if not codex_bin.exists():
        reset_terminal_status_fields(status_path)
        write_status(
            status_path,
            status="skipped",
            reason="codex CLI is not available",
            project_root=None,
            started_at=None,
            exit_code=None,
            finished_at=utc_now(),
        )
        write_agent_review_html(session_dir)
        return

    project_root_path = Path(project_root).expanduser()
    workspace_dir = workspace_run_dir(project_root_path, session_dir.name)
    workspace_dir.mkdir(parents=True, exist_ok=True)
    request_path = session_dir / "agent-request.json"
    output_path = session_dir / "agent-result.md"
    events_path = session_dir / "agent-events.jsonl"
    prompt = prompt_for(session_dir, request)
    summary = read_json(session_dir / "summary.json", {})
    asset_paths = copy_review_assets(session_dir, workspace_dir, summary)
    recording_md_path = write_workspace_recording_md(
        workspace_dir,
        session_dir=session_dir,
        summary=summary,
        request=request,
        asset_paths=asset_paths,
    )
    command = [
        str(codex_bin),
        "exec",
        "-C",
        str(project_root_path),
        "--add-dir",
        str(session_dir),
        "--skip-git-repo-check",
        "--output-last-message",
        str(output_path),
        "--json",
        "-",
    ]
    if request["mode"] == "apply":
        command.append("--full-auto")
    else:
        command.extend(["-s", "read-only"])

    for image_path in request["artifacts"].get("overlay_images", [])[:3]:
        if isinstance(image_path, str) and Path(image_path).exists():
            command.extend(["-i", image_path])
    command.append(prompt)

    write_json(request_path, request)
    before_snapshot = current_repo_status(project_root_path) if request["mode"] == "apply" else {}
    write_status(
        status_path,
        status="running",
        provider="codex-cli",
        mode=request["mode"],
        project_root=str(project_root_path),
        started_at=utc_now(),
        reason=None,
        finished_at=None,
        exit_code=None,
        command=command,
        request_path=str(request_path),
        output_path=str(output_path),
        events_path=str(events_path),
        workspace_run_dir=str(workspace_dir),
        workspace_recording_md=str(recording_md_path),
        workspace_progress_md=str(workspace_dir / "agent-progress.md"),
        workspace_result_md=str(workspace_dir / "agent-result.md"),
    )
    running_status = read_json(status_path, {})
    progress_md_path = write_workspace_progress_md(
        workspace_dir,
        session_dir=session_dir,
        summary=summary,
        status=running_status if isinstance(running_status, dict) else {},
        request=request,
    )
    result_md_path = write_workspace_result_md(
        workspace_dir,
        session_dir=session_dir,
        status=running_status if isinstance(running_status, dict) else {},
        request=request,
    )
    write_workspace_links(
        workspace_dir,
        session_dir=session_dir,
        summary=summary,
        status=running_status if isinstance(running_status, dict) else {},
        request=request,
        progress_path=progress_md_path,
        result_path=result_md_path,
    )
    try_open_local_file(progress_md_path)
    write_agent_review_html(session_dir)

    with events_path.open("w", encoding="utf-8") as handle:
        result = subprocess.run(
            command,
            cwd=PROJECT_ROOT,
            input=prompt,
            stdout=handle,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )

    thread_details = codex_thread_info(events_path) or {}
    write_status(
        status_path,
        status="completed" if result.returncode == 0 else "failed",
        finished_at=utc_now(),
        exit_code=result.returncode,
        thread_id=thread_details.get("thread_id"),
        thread_url=thread_details.get("thread_url"),
    )
    final_status = read_json(status_path, {})
    if request["mode"] == "apply":
        after_snapshot = current_repo_status(project_root_path)
        write_apply_workspace_artifacts(
            workspace_dir,
            project_root=project_root_path,
            before_snapshot=before_snapshot if isinstance(before_snapshot, dict) else {},
            after_snapshot=after_snapshot,
            status=final_status if isinstance(final_status, dict) else {},
        )
    final_result_md_path = write_workspace_result_md(
        workspace_dir,
        session_dir=session_dir,
        status=final_status if isinstance(final_status, dict) else {},
        request=request,
    )
    final_progress_md_path = write_workspace_progress_md(
        workspace_dir,
        session_dir=session_dir,
        summary=summary,
        status=final_status if isinstance(final_status, dict) else {},
        request=request,
    )
    write_workspace_links(
        workspace_dir,
        session_dir=session_dir,
        summary=summary,
        status=final_status if isinstance(final_status, dict) else {},
        request=request,
        progress_path=final_progress_md_path,
        result_path=final_result_md_path,
    )
    write_agent_review_html(session_dir)


def run(session_dir: Path) -> int:
    preferences = read_preferences()
    orchestrator = preferences.get("orchestrator", {}) if isinstance(preferences.get("orchestrator"), dict) else {}
    status_path = session_dir / "agent-status.json"
    if not orchestrator.get("enabled", True):
        reset_terminal_status_fields(status_path)
        write_status(
            status_path,
            status="skipped",
            reason="orchestrator disabled",
            project_root=None,
            started_at=None,
            exit_code=None,
            finished_at=utc_now(),
        )
        write_agent_review_html(session_dir)
        return 0
    if not orchestrator.get("auto_run", True):
        reset_terminal_status_fields(status_path)
        write_status(
            status_path,
            status="skipped",
            reason="auto_run disabled",
            project_root=None,
            started_at=None,
            exit_code=None,
            finished_at=utc_now(),
        )
        write_agent_review_html(session_dir)
        return 0

    request = build_request(session_dir, preferences)
    provider = request["provider"]
    if provider == "codex-cli":
        run_codex_cli(session_dir, request, status_path)
        return 0

    reset_terminal_status_fields(status_path)
    write_status(
        status_path,
        status="skipped",
        reason=f"unsupported provider: {provider}",
        project_root=None,
        started_at=None,
        exit_code=None,
        finished_at=utc_now(),
    )
    write_agent_review_html(session_dir)
    return 0


def main() -> int:
    migrate_legacy_state()
    args = parse_args()
    session_dir = locate_session_dir(args.session) if args.session else latest_session_dir()
    if session_dir is None:
        raise FileNotFoundError(f"Session not found: {args.session}")
    return run(session_dir)


if __name__ == "__main__":
    raise SystemExit(main())
