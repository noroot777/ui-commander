#!/usr/bin/env python3
"""Wait for the next finalized ui-commander session."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from preferences_store import read_preferences, update_preferences
from runtime_state import set_active_project_root
from state_paths import all_session_dirs, locate_session_dir, migrate_legacy_state


def read_json(path: Path, default: object) -> object:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return default


def session_payload(session_dir: Path) -> dict[str, object]:
    summary_path = session_dir / "summary.json"
    summary = read_json(summary_path, {})
    status = read_json(session_dir / "agent-status.json", {})
    return {
        "session_id": session_dir.name,
        "session_dir": str(session_dir),
        "summary": str(summary_path),
        "recording_mode": summary.get("recording_mode"),
        "dynamic_recording": summary.get("dynamic_recording"),
        "review": summary.get("review", {}),
        "live_review": summary.get("live_review", {}),
        "orchestrator": summary.get("orchestrator", {}),
        "agent_status": status,
    }


def latest_candidates() -> list[Path]:
    return sorted(all_session_dirs(), key=lambda path: path.stat().st_mtime_ns)


def existing_session_ids() -> set[str]:
    return {path.name for path in latest_candidates()}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout", type=float, default=1800.0)
    parser.add_argument("--poll-interval", type=float, default=0.75)
    parser.add_argument("--after-session", help="ignore this session id and anything older")
    parser.add_argument("--after-mtime-ns", type=int, default=None)
    parser.add_argument("--suppress-auto-run", choices=("on", "off"), default="on")
    parser.add_argument("--recording-mode", choices=("standard", "dynamic"), help="queue recording mode for the next session")
    return parser.parse_args()


def baseline_mtime_ns(after_session: str | None, explicit_after_mtime_ns: int | None) -> int:
    if explicit_after_mtime_ns is not None:
        return explicit_after_mtime_ns
    if after_session:
        path = locate_session_dir(after_session)
        if path and path.exists():
            return path.stat().st_mtime_ns
    candidates = latest_candidates()
    if not candidates:
        return 0
    return candidates[-1].stat().st_mtime_ns


def should_accept(
    session_dir: Path,
    baseline_ns: int,
    after_session: str | None,
    initial_session_ids: set[str],
) -> bool:
    if session_dir.name in initial_session_ids:
        return False
    if after_session and session_dir.name == after_session:
        return False
    if session_dir.stat().st_mtime_ns <= baseline_ns:
        return False
    return (session_dir / "summary.json").exists()


def main() -> int:
    migrate_legacy_state()
    args = parse_args()
    set_active_project_root(str(Path.cwd()))
    baseline_ns = baseline_mtime_ns(args.after_session, args.after_mtime_ns)
    initial_session_ids = existing_session_ids()
    previous_auto_run = None
    previous_next_recording_mode = None
    found_session = False

    if args.suppress_auto_run == "on":
        preferences = read_preferences()
        previous_auto_run = bool(preferences.get("orchestrator", {}).get("auto_run", True))
        previous_next_recording_mode = preferences.get("recording", {}).get("next_mode")
        if previous_auto_run:
            update_preferences(auto_run=False)
    else:
        previous_next_recording_mode = read_preferences().get("recording", {}).get("next_mode")

    if args.recording_mode:
        update_preferences(next_recording_mode=args.recording_mode)

    started = time.monotonic()
    try:
        while time.monotonic() - started <= args.timeout:
            for candidate in reversed(latest_candidates()):
                if should_accept(candidate, baseline_ns, args.after_session, initial_session_ids):
                    found_session = True
                    print(json.dumps(session_payload(candidate), indent=2, ensure_ascii=True))
                    return 0
            time.sleep(args.poll_interval)
    finally:
        if previous_auto_run is not None:
            update_preferences(auto_run=previous_auto_run)
        if args.recording_mode and not found_session:
            if previous_next_recording_mode:
                update_preferences(next_recording_mode=str(previous_next_recording_mode))
            else:
                update_preferences(clear_next_recording_mode=True)

    print(json.dumps({"error": "timeout waiting for next finalized session"}, indent=2, ensure_ascii=True))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
