#!/usr/bin/env python3
"""Validate local dependencies for ui-commander."""

from __future__ import annotations

import importlib
import os
import platform
import shutil
import subprocess
import sys

from python_runtime import quoted_python_executable


PYTHON_PIP_HINT = quoted_python_executable(sys.executable)

OPTIONAL_MODULES = {
    "whisper": f"{PYTHON_PIP_HINT} -m pip uninstall -y whisper && {PYTHON_PIP_HINT} -m pip install openai-whisper",
}

OPTIONAL_COMMANDS = {
    "ffmpeg": "choco install ffmpeg" if platform.system() == "Windows" else "brew install ffmpeg",
}

COMMON_COMMAND_PATHS = {
    "ffmpeg": [
        "/opt/homebrew/bin/ffmpeg",
        "/usr/local/bin/ffmpeg",
    ],
}


def check_chrome() -> bool:
    if shutil.which("google-chrome") or shutil.which("chrome") or shutil.which("chromium") or shutil.which("chrome.exe"):
        print("[OK] Chrome executable found on PATH")
        return True

    if platform.system() == "Windows":
        candidates = [
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "Google", "Chrome", "Application", "chrome.exe"),
            os.path.join(os.environ.get("PROGRAMFILES", ""), "Google", "Chrome", "Application", "chrome.exe"),
            os.path.join(os.environ.get("PROGRAMFILES(X86)", ""), "Google", "Chrome", "Application", "chrome.exe"),
        ]
        for candidate in candidates:
            if candidate and os.path.exists(candidate):
                print(f"[OK] Chrome app found at {candidate}")
                return True
        print("[MISSING] Google Chrome: install Google Chrome")
        return False

    mac_app = "/Applications/Google Chrome.app"
    if os.path.exists(mac_app):
        print(f"[OK] Chrome app found at {mac_app}")
        return True

    try:
        subprocess.run(["open", "-Ra", "Google Chrome"], check=True, capture_output=True)
        print("[OK] Google Chrome is installed")
        return True
    except Exception:  # noqa: BLE001
        print("[MISSING] Google Chrome: install Google Chrome")
        return False


def check_module(name: str, hint: str, optional: bool = False) -> bool:
    try:
        module = importlib.import_module(name)
    except ImportError:
        level = "OPTIONAL" if optional else "MISSING"
        print(f"[{level}] python module {name}: install with {hint}")
        return optional
    if name == "whisper" and not hasattr(module, "load_model"):
        level = "OPTIONAL" if optional else "MISSING"
        print(
            f"[{level}] python module {name}: incompatible module at {getattr(module, '__file__', 'unknown')}; install with {hint}"
        )
        return optional
    print(f"[OK] python module {name}")
    return True


def find_command(name: str) -> str | None:
    path = shutil.which(name)
    if path:
        return path
    for candidate in COMMON_COMMAND_PATHS.get(name, []):
        if os.path.exists(candidate):
            return candidate
    return None


def main() -> int:
    ok = True
    optional_ok: dict[str, bool] = {}

    print("Checking ui-commander dependencies")
    print()

    ok = check_chrome() and ok

    for name, hint in OPTIONAL_MODULES.items():
        optional_ok[name] = check_module(name, hint, optional=True)

    for name, hint in OPTIONAL_COMMANDS.items():
        path = find_command(name)
        if path:
            print(f"[OK] optional command {name}: {path}")
            optional_ok[name] = True
        else:
            print(f"[OPTIONAL] command {name}: install with {hint}")
            optional_ok[name] = False

    if sys.version_info < (3, 9):
        print(f"[MISSING] python >= 3.9 required, found {sys.version.split()[0]}")
        ok = False
    else:
        print(f"[OK] python {sys.version.split()[0]}")

    print()
    if ok:
        print("Dependencies look good.")
        if not optional_ok.get("whisper", False) or not optional_ok.get("ffmpeg", False):
            print("Speech transcription is not fully available yet.")
        return 0

    print("Install the missing dependencies before using this skill.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
