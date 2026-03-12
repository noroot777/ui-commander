#!/usr/bin/env python3
"""One-shot local setup for screen-commander."""

from __future__ import annotations

import argparse
import platform
import subprocess
import sys
from pathlib import Path

from status import extension_installed
from install_native_host import extension_id
from python_runtime import resolve_python_executable


PROJECT_ROOT = Path(__file__).resolve().parent.parent
EXTENSION_DIR = PROJECT_ROOT / "chrome-extension"
PYTHON_BIN = resolve_python_executable(sys.executable)


def ensure_executable(path: Path) -> None:
    path.chmod(path.stat().st_mode | 0o111)


def run(script_name: str) -> int:
    script_path = PROJECT_ROOT / "scripts" / script_name
    result = subprocess.run([PYTHON_BIN, str(script_path)], cwd=PROJECT_ROOT)
    return result.returncode


def try_open(path_or_url: str, app: str | None = None) -> None:
    cmd = ["open"]
    if app:
        cmd.extend(["-a", app])
    cmd.append(path_or_url)
    try:
        subprocess.run(cmd, check=True, capture_output=True)
    except Exception:
        pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--open", action="store_true", help="open Chrome Extensions and Finder after setup")
    parser.add_argument("--no-open", action="store_true", help="do not open Chrome or Finder after setup")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    chrome_extension_id = extension_id()
    extension_ok, _profile = extension_installed(chrome_extension_id)
    start_shortcut = "Option+S" if platform.system() == "Darwin" else "Alt+S"
    stop_shortcut = "Option+E" if platform.system() == "Darwin" else "Alt+E"
    ensure_executable(PROJECT_ROOT / "scripts" / "native_host_entry.sh")

    if run("check_deps.py") != 0:
        return 1

    if run("install_native_host.py") != 0:
        return 1

    should_open = args.open or (not args.no_open and not extension_ok)
    if should_open:
        try_open("chrome://extensions", app="Google Chrome")
        try_open(str(EXTENSION_DIR))

    print()
    print("Setup complete.")
    print(f"Extension folder: {EXTENSION_DIR}")
    if extension_ok:
        print("Chrome extension already detected. Native host was refreshed without reopening Chrome.")
        print(f"Focus the page, press {start_shortcut} to start, and {stop_shortcut} to stop.")
    else:
        print("Next: in Chrome Extensions, enable Developer mode, click 'Load unpacked', pick that folder.")
        print(f"Then pin Screen Commander, focus the page, press {start_shortcut} to start, and {stop_shortcut} to stop.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
