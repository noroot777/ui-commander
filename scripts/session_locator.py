#!/usr/bin/env python3
"""Resolve a UI Commander session from a session id or localhost review URL."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from urllib.parse import urlparse

from state_paths import locate_session_dir, migrate_legacy_state

SESSION_ID_PATTERN = re.compile(r"\b(\d{8}-\d{6}-[a-f0-9]{6,})\b")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", help="session id or localhost live/review URL")
    return parser.parse_args()


def extract_session_id(source: str) -> str | None:
    raw = source.strip()
    if not raw:
        return None
    match = SESSION_ID_PATTERN.search(raw)
    if match:
        return match.group(1)
    try:
        parsed = urlparse(raw)
    except Exception:  # noqa: BLE001
        return None
    path_match = re.search(r"/sessions/([^/]+)", parsed.path or "")
    if path_match:
        candidate = path_match.group(1).strip()
        match = SESSION_ID_PATTERN.search(candidate)
        if match:
            return match.group(1)
    return None


def read_json(path: Path, default: object) -> object:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return default


def build_payload(session_dir: Path) -> dict[str, object]:
    summary_path = session_dir / "summary.json"
    summary = read_json(summary_path, {})
    script_dir = Path(__file__).resolve().parent
    llm_intent = summary.get("llm_intent", {}) if isinstance(summary, dict) else {}
    llm_status = str(llm_intent.get("status") or "")
    host_fusion = {
        "status": llm_status,
        "needs_resolution": llm_status == "pending_host_fusion",
        "prompt_command": f"python3 {script_dir / 'intent_resolution.py'} prompt --session {session_dir.name}",
        "show_command": f"python3 {script_dir / 'intent_resolution.py'} show --session {session_dir.name}",
        "write_command": f"python3 {script_dir / 'intent_resolution.py'} write --session {session_dir.name} --input <json-file-or-stdin>",
    }
    return {
        "session_id": session_dir.name,
        "session_dir": str(session_dir),
        "summary": str(summary_path),
        "review": summary.get("review", {}) if isinstance(summary, dict) else {},
        "llm_intent": llm_intent,
        "host_fusion": host_fusion,
        "live_review": summary.get("live_review", {}) if isinstance(summary, dict) else {},
        "orchestrator": summary.get("orchestrator", {}) if isinstance(summary, dict) else {},
        "artifacts": summary.get("artifacts", {}) if isinstance(summary, dict) else {},
    }


def main() -> int:
    migrate_legacy_state()
    args = parse_args()
    session_id = extract_session_id(args.source)
    if not session_id:
        print(json.dumps({"error": "could_not_extract_session_id", "source": args.source}, indent=2, ensure_ascii=True))
        return 1

    session_dir = locate_session_dir(session_id)
    if session_dir is None:
        print(json.dumps({"error": "session_not_found", "session_id": session_id}, indent=2, ensure_ascii=True))
        return 1

    print(json.dumps(build_payload(session_dir), indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
