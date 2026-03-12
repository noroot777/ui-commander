#!/opt/homebrew/opt/python@3.11/libexec/bin/python
"""One-shot local setup for screen-commander."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
EXTENSION_DIR = PROJECT_ROOT / "chrome-extension"
PYTHON_BIN = Path("/opt/homebrew/opt/python@3.11/libexec/bin/python")


def ensure_executable(path: Path) -> None:
    path.chmod(path.stat().st_mode | 0o111)


def run(script_name: str) -> int:
    script_path = PROJECT_ROOT / "scripts" / script_name
    result = subprocess.run([str(PYTHON_BIN), str(script_path)], cwd=PROJECT_ROOT)
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
    parser.add_argument("--no-open", action="store_true", help="do not open Chrome or Finder after setup")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    ensure_executable(PROJECT_ROOT / "scripts" / "native_host_entry.sh")

    if run("check_deps.py") != 0:
        return 1

    if run("install_native_host.py") != 0:
        return 1

    if not args.no_open:
        try_open("chrome://extensions", app="Google Chrome")
        try_open(str(EXTENSION_DIR))

    print()
    print("Setup complete.")
    print(f"Extension folder: {EXTENSION_DIR}")
    print("Next: in Chrome Extensions, enable Developer mode, click 'Load unpacked', pick that folder.")
    print("Then pin Screen Commander, focus the page, press Option+S to start, and Option+E to stop.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
