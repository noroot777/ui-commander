#!/usr/bin/env python3
"""Shared state paths for screen-commander across local and global installs."""

from __future__ import annotations

import hashlib
import re
import shutil
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
LEGACY_ROOT = PROJECT_ROOT / ".screen-commander"
STATE_ROOT = Path.home() / ".screen-commander"
TEMP_ROOT = Path("/tmp") / "screen-commander"
LEGACY_SESSION_ROOTS = (
    LEGACY_ROOT / "sessions",
    STATE_ROOT / "sessions",
)


def state_root() -> Path:
    return STATE_ROOT


def sessions_dir() -> Path:
    return TEMP_ROOT / "sessions"


def preferences_path() -> Path:
    return STATE_ROOT / "preferences.json"


def runtime_state_path() -> Path:
    return STATE_ROOT / "runtime-state.json"


def language_profile_path() -> Path:
    return STATE_ROOT / "language-profile.json"


def server_info_path() -> Path:
    return STATE_ROOT / "session-server.json"


def native_host_log_path() -> Path:
    return STATE_ROOT / "native-host.log"


def python_bin_path() -> Path:
    return STATE_ROOT / "python-bin"


def ensure_state_root() -> Path:
    STATE_ROOT.mkdir(parents=True, exist_ok=True)
    return STATE_ROOT


def ensure_sessions_root() -> Path:
    path = sessions_dir()
    path.mkdir(parents=True, exist_ok=True)
    return path


def normalize_project_root(project_root: str | Path | None) -> str | None:
    if project_root is None:
        return None
    value = str(project_root).strip()
    if not value or value == "auto":
        return None
    return value


def project_slug(project_root: str | Path | None) -> str:
    normalized = normalize_project_root(project_root)
    if not normalized:
        return "unassigned"
    path = Path(normalized).expanduser()
    base = path.name or "workspace"
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", base).strip("-._") or "workspace"
    suffix = hashlib.sha1(str(path).encode("utf-8")).hexdigest()[:8]
    return f"{safe}-{suffix}"


def session_group_dir(project_root: str | Path | None) -> Path:
    return ensure_sessions_root() / project_slug(project_root)


def session_path(session_id: str, project_root: str | Path | None = None) -> Path:
    if project_root is not None:
        return session_group_dir(project_root) / session_id
    found = locate_session_dir(session_id)
    if found is not None:
        return found
    return session_group_dir(None) / session_id


def _collect_session_dirs(root: Path) -> list[Path]:
    if not root.exists():
        return []
    candidates: list[Path] = []
    for child in root.iterdir():
        if not child.is_dir():
            continue
        if (child / "session.json").exists() or (child / "summary.json").exists():
            candidates.append(child)
            continue
        for grandchild in child.iterdir():
            if not grandchild.is_dir():
                continue
            if (grandchild / "session.json").exists() or (grandchild / "summary.json").exists():
                candidates.append(grandchild)
    return candidates


def all_session_dirs() -> list[Path]:
    seen: set[str] = set()
    ordered: list[Path] = []
    for root in (sessions_dir(), *LEGACY_SESSION_ROOTS):
        for candidate in _collect_session_dirs(root):
            key = str(candidate.resolve())
            if key in seen:
                continue
            seen.add(key)
            ordered.append(candidate)
    return ordered


def latest_session_dir() -> Path | None:
    candidates = all_session_dirs()
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime_ns)


def locate_session_dir(session_id: str) -> Path | None:
    for candidate in all_session_dirs():
        if candidate.name == session_id:
            return candidate
    return None


def migrate_legacy_state() -> None:
    ensure_state_root()
    if not LEGACY_ROOT.exists() or LEGACY_ROOT.resolve() == STATE_ROOT.resolve():
        return

    for name in ("preferences.json", "runtime-state.json", "language-profile.json", "session-server.json", "native-host.log"):
        source = LEGACY_ROOT / name
        target = STATE_ROOT / name
        if source.exists() and not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
