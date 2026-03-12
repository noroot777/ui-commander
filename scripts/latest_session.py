#!/usr/bin/env python3
"""Print the latest screen-commander session paths and review artifacts."""

from __future__ import annotations

import json

from state_paths import latest_session_dir, migrate_legacy_state


def main() -> int:
    migrate_legacy_state()
    latest = latest_session_dir()
    if latest is None:
        print("No sessions found.")
        return 1
    summary = latest / "summary.json"
    summary_payload = {}
    if summary.exists():
        summary_payload = json.loads(summary.read_text(encoding="utf-8"))
    payload = {
        "session_dir": str(latest),
        "summary": str(summary),
        "review": summary_payload.get("review", {}),
        "live_review": summary_payload.get("live_review", {}),
        "orchestrator": summary_payload.get("orchestrator", {}),
    }
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
