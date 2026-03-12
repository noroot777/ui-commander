#!/opt/homebrew/opt/python@3.11/libexec/bin/python
"""Print the latest screen-commander session paths and review artifacts."""

from __future__ import annotations

import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SESSIONS_DIR = PROJECT_ROOT / ".screen-commander" / "sessions"


def main() -> int:
    if not SESSIONS_DIR.exists():
        print("No sessions directory found.")
        return 1

    candidates = [path for path in SESSIONS_DIR.iterdir() if path.is_dir()]
    if not candidates:
        print("No sessions found.")
        return 1

    latest = max(candidates, key=lambda path: path.stat().st_mtime)
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
