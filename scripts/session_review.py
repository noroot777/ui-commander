#!/usr/bin/env python3
"""Print a compact review payload for a screen-commander session."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from state_paths import latest_session_dir as latest_shared_session_dir, locate_session_dir, migrate_legacy_state

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def codex_thread_info(events_path: Path) -> dict[str, str]:
    if not events_path.exists():
        return {}
    for raw in events_path.read_text(encoding="utf-8").splitlines():
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
    return {}


def latest_local_session_dir() -> Path:
    latest = latest_shared_session_dir()
    if latest is None:
        raise FileNotFoundError("No sessions found.")
    return latest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session", help="session id to inspect")
    return parser.parse_args()


def read_json(path: Path, default: object) -> object:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    migrate_legacy_state()
    args = parse_args()
    session_dir = locate_session_dir(args.session) if args.session else latest_local_session_dir()
    if session_dir is None:
        raise FileNotFoundError(f"Session not found: {args.session}")
    summary = read_json(session_dir / "summary.json", {})
    focus_regions = read_json(session_dir / "focus_regions.json", [])
    agent_status = read_json(session_dir / "agent-status.json", {})
    transcript_path = session_dir / "transcript.txt"
    transcript = transcript_path.read_text(encoding="utf-8").strip() if transcript_path.exists() else ""
    thread_info = codex_thread_info(session_dir / "agent-events.jsonl")
    if not thread_info and isinstance(agent_status, dict):
        thread_id = agent_status.get("thread_id")
        thread_url = agent_status.get("thread_url")
        if isinstance(thread_id, str) and thread_id.strip():
            thread_info = {"thread_id": thread_id, "thread_url": thread_url or f"codex://threads/{thread_id}"}

    payload = {
        "session_id": session_dir.name,
        "session_dir": str(session_dir),
        "review": summary.get("review", {}),
        "review_html": summary.get("artifacts", {}).get("review_html"),
        "agent_review_html": summary.get("artifacts", {}).get("agent_review_html"),
        "live_review": summary.get("live_review", {}),
        "orchestrator": summary.get("orchestrator", {}),
        "codex_thread": thread_info,
        "transcript": transcript,
        "focus_regions": [
            {
                "region_id": item.get("region_id"),
                "gesture": item.get("gesture"),
                "overlay": item.get("artifacts", {}).get("overlay"),
                "crop": item.get("artifacts", {}).get("crop"),
                "keyframe": item.get("artifacts", {}).get("keyframe"),
            }
            for item in focus_regions
        ],
    }
    print(json.dumps(payload, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
