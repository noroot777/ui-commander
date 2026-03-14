#!/usr/bin/env python3
"""Resolve a usable Python executable for ui-commander."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path


COMMON_PYTHON_PATHS = (
    "/opt/homebrew/opt/python@3.11/libexec/bin/python",
    "/opt/homebrew/bin/python3",
    "/usr/local/bin/python3",
    "/usr/bin/python3",
)


def _looks_like_windows_store_alias(candidate: str) -> bool:
    normalized = str(Path(candidate).expanduser()).lower().replace("/", "\\")
    return "\\microsoft\\windowsapps\\python" in normalized


def _candidate_paths(preferred: str | None = None) -> list[str]:
    candidates: list[str] = []
    windows_candidates: tuple[str | None, ...] = ()
    if os.name == "nt":
        windows_candidates = (
            shutil.which("py"),
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Python", "Launcher", "py.exe"),
        )
    for candidate in (
        preferred,
        os.environ.get("UI_COMMANDER_PYTHON"),
        sys.executable,
        shutil.which("python3"),
        shutil.which("python"),
        *windows_candidates,
        *COMMON_PYTHON_PATHS,
    ):
        if not candidate:
            continue
        normalized = str(Path(candidate).expanduser())
        if normalized not in candidates:
            candidates.append(normalized)
    return candidates


def _is_usable_python(candidate: str) -> bool:
    normalized = str(Path(candidate).expanduser())
    if _looks_like_windows_store_alias(normalized):
        return False
    if not (os.path.isfile(normalized) and os.access(normalized, os.X_OK)):
        return False
    try:
        result = subprocess.run(
            [normalized, "-c", "import sys; print(sys.executable)"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except Exception:  # noqa: BLE001
        return False
    if result.returncode != 0:
        return False
    resolved = result.stdout.strip()
    if not resolved:
        return False
    if _looks_like_windows_store_alias(resolved):
        return False
    return True


def resolve_python_executable(preferred: str | None = None) -> str:
    for candidate in _candidate_paths(preferred):
        if _is_usable_python(candidate):
            return str(Path(candidate).expanduser())
        discovered = shutil.which(candidate)
        if discovered and _is_usable_python(discovered):
            return discovered
    raise RuntimeError("Unable to find a usable Python 3 executable for ui-commander")


def quoted_python_executable(preferred: str | None = None) -> str:
    return shlex.quote(resolve_python_executable(preferred))
