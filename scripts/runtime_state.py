#!/usr/bin/env python3
"""Shared runtime state helpers for ui-commander."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from state_paths import runtime_state_path


RUNTIME_STATE_PATH = runtime_state_path()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_runtime_state() -> dict:
    if not RUNTIME_STATE_PATH.exists():
        return {}
    try:
        payload = json.loads(RUNTIME_STATE_PATH.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    return payload if isinstance(payload, dict) else {}


def write_runtime_state(payload: dict) -> None:
    RUNTIME_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    RUNTIME_STATE_PATH.write_text(
        json.dumps(payload, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )


def set_active_project_root(project_root: str | None) -> dict:
    state = read_runtime_state()
    cleaned = project_root.strip() if isinstance(project_root, str) else ""
    state["active_project_root"] = cleaned or None
    state["active_project_updated_at"] = utc_now()
    write_runtime_state(state)
    return state

