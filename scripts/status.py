#!/opt/homebrew/opt/python@3.11/libexec/bin/python
"""Report the local readiness state for screen-commander."""

from __future__ import annotations

import importlib
import importlib.util
import json
import os
import shutil
from pathlib import Path

from install_native_host import HOST_NAME, extension_id, manifest_dir, project_root
from preferences_store import read_preferences


CHROME_ROOT = Path.home() / "Library" / "Application Support" / "Google" / "Chrome"
PYTHON_BIN = "/opt/homebrew/opt/python@3.11/libexec/bin/python"
COMMON_COMMAND_PATHS = {
    "ffmpeg": [
        "/opt/homebrew/bin/ffmpeg",
        "/usr/local/bin/ffmpeg",
    ],
}


def host_manifest_path() -> Path:
    return manifest_dir() / f"{HOST_NAME}.json"


def host_ready(expected_extension_id: str) -> bool:
    path = host_manifest_path()
    if not path.exists():
        return False
    payload = json.loads(path.read_text())
    origins = payload.get("allowed_origins", [])
    return f"chrome-extension://{expected_extension_id}/" in origins


def chrome_profiles() -> list[Path]:
    if not CHROME_ROOT.exists():
        return []
    candidates = []
    for child in CHROME_ROOT.iterdir():
        if not child.is_dir():
            continue
        if child.name == "Default" or child.name.startswith("Profile "):
            prefs = child / "Preferences"
            if prefs.exists():
                candidates.append(child)
    return candidates


def extension_installed(expected_extension_id: str) -> tuple[bool, str | None]:
    for profile in chrome_profiles():
        prefs_path = profile / "Preferences"
        try:
            payload = json.loads(prefs_path.read_text())
        except Exception:  # noqa: BLE001
            continue
        settings = payload.get("extensions", {}).get("settings", {})
        if expected_extension_id in settings:
            return True, profile.name
    return False, None


def state_for(extension_ok: bool, host_ok: bool) -> str:
    if not extension_ok:
        return "not_installed"
    if not host_ok:
        return "extension_installed"
    return "ready_to_record"


def dependency_status() -> dict[str, object]:
    whisper_installed = False
    whisper_hint = f"{PYTHON_BIN} -m pip uninstall -y whisper && {PYTHON_BIN} -m pip install openai-whisper"
    spec = importlib.util.find_spec("whisper")
    if spec is not None:
        try:
            whisper = importlib.import_module("whisper")
            whisper_installed = hasattr(whisper, "load_model")
            if not whisper_installed:
                whisper_hint = f"remove incompatible whisper module at {getattr(whisper, '__file__', 'unknown')} and install openai-whisper"
        except Exception:  # noqa: BLE001
            whisper_installed = False
    ffmpeg_available = shutil.which("ffmpeg") is not None or any(
        os.path.exists(path) for path in COMMON_COMMAND_PATHS["ffmpeg"]
    )
    return {
        "whisper_installed": whisper_installed,
        "ffmpeg_available": ffmpeg_available,
        "transcription_ready": whisper_installed and ffmpeg_available,
        "install_hints": {
            "whisper": None if whisper_installed else whisper_hint,
            "ffmpeg": None if ffmpeg_available else "brew install ffmpeg",
        },
    }


def main() -> int:
    expected_extension_id = extension_id()
    extension_ok, profile = extension_installed(expected_extension_id)
    host_ok = host_ready(expected_extension_id)
    preferences = read_preferences()
    preferred_language = preferences.get("transcription", {}).get("preferred_language")

    payload = {
        "state": state_for(extension_ok, host_ok),
        "extension_id": expected_extension_id,
        "extension_dir": str(project_root() / "chrome-extension"),
        "native_host_manifest": str(host_manifest_path()),
        "extension_installed": extension_ok,
        "native_host_ready": host_ok,
        "chrome_profile": profile,
        "dependencies": dependency_status(),
        "preferences": preferences,
        "needs_language_setup": not bool(preferred_language),
    }
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
