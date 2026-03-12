#!/usr/bin/env python3
"""Resolve a usable Python executable for screen-commander."""

from __future__ import annotations

import os
import shlex
import shutil
import sys
from pathlib import Path


COMMON_PYTHON_PATHS = (
    "/opt/homebrew/opt/python@3.11/libexec/bin/python",
    "/opt/homebrew/bin/python3",
    "/usr/local/bin/python3",
    "/usr/bin/python3",
)


def _candidate_paths(preferred: str | None = None) -> list[str]:
    candidates: list[str] = []
    for candidate in (
        preferred,
        os.environ.get("SCREEN_COMMANDER_PYTHON"),
        sys.executable,
        shutil.which("python3"),
        shutil.which("python"),
        *COMMON_PYTHON_PATHS,
    ):
        if not candidate:
            continue
        normalized = str(Path(candidate).expanduser())
        if normalized not in candidates:
            candidates.append(normalized)
    return candidates


def resolve_python_executable(preferred: str | None = None) -> str:
    for candidate in _candidate_paths(preferred):
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
        discovered = shutil.which(candidate)
        if discovered:
            return discovered
    raise RuntimeError("Unable to find a usable Python 3 executable for screen-commander")


def quoted_python_executable(preferred: str | None = None) -> str:
    return shlex.quote(resolve_python_executable(preferred))
