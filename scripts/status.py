#!/usr/bin/env python3
"""Report the local readiness state for ui-commander."""

from __future__ import annotations

import importlib
import importlib.util
import json
import os
import platform
import shlex
import shutil
import sys
from pathlib import Path

from install_native_host import HOST_NAME, extension_id, manifest_dir, project_root, windows_registry_entries
from preferences_store import read_preferences
from python_runtime import resolve_python_executable
from state_paths import migrate_legacy_state, runtime_state_path


def chrome_root() -> Path:
    system = platform.system()
    if system == "Windows":
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            return Path(local_app_data) / "Google" / "Chrome" / "User Data"
        return Path.home() / "AppData" / "Local" / "Google" / "Chrome" / "User Data"
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support" / "Google" / "Chrome"
    return Path.home() / ".config" / "google-chrome"
PYTHON_BIN = resolve_python_executable(sys.executable)
RUNTIME_STATE_PATH = runtime_state_path()
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
    manifest_ok = f"chrome-extension://{expected_extension_id}/" in origins
    if not manifest_ok:
        return False
    if platform.system() != "Windows":
        return True
    registry = windows_registry_entries()
    target = str(path)
    return any(value == target for value in registry.values())


def native_host_registration(expected_extension_id: str) -> dict[str, object]:
    path = host_manifest_path()
    payload = {}
    origins: list[str] = []
    if path.exists():
        try:
            payload = json.loads(path.read_text())
            origins = payload.get("allowed_origins", [])
        except Exception:  # noqa: BLE001
            payload = {}
    result: dict[str, object] = {
        "manifest_path": str(path),
        "manifest_exists": path.exists(),
        "manifest_matches_extension": f"chrome-extension://{expected_extension_id}/" in origins,
    }
    if platform.system() == "Windows":
        registry = windows_registry_entries()
        result["registry_entries"] = registry
        result["registry_points_to_manifest"] = any(value == str(path) for value in registry.values())
    return result


def chrome_profiles() -> list[Path]:
    root = chrome_root()
    if not root.exists():
        return []
    candidates = []
    for child in root.iterdir():
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


def runtime_extension_confirmation() -> dict[str, object]:
    if not RUNTIME_STATE_PATH.exists():
        return {}
    try:
        payload = json.loads(RUNTIME_STATE_PATH.read_text())
    except Exception:  # noqa: BLE001
        return {}
    return payload if isinstance(payload, dict) else {}


def state_for(extension_ok: bool, host_ok: bool) -> str:
    if not extension_ok:
        return "not_installed"
    if not host_ok:
        return "extension_installed"
    return "ready_to_record"


def dependency_status() -> dict[str, object]:
    whisper_installed = False
    quoted_python = shlex.quote(PYTHON_BIN)
    whisper_hint = f"{quoted_python} -m pip uninstall -y whisper && {quoted_python} -m pip install openai-whisper"
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
            "ffmpeg": None
            if ffmpeg_available
            else "choco install ffmpeg" if platform.system() == "Windows" else "brew install ffmpeg",
        },
    }


def main() -> int:
    migrate_legacy_state()
    expected_extension_id = extension_id()
    extension_ok, profile = extension_installed(expected_extension_id)
    host_ok = host_ready(expected_extension_id)
    runtime_state = runtime_extension_confirmation()
    if not extension_ok and host_ok and runtime_state.get("extension_confirmed") is True:
        extension_ok = True
        profile = "runtime-confirmed"
    preferences = read_preferences()
    preferred_language = preferences.get("transcription", {}).get("preferred_language")

    payload = {
        "state": state_for(extension_ok, host_ok),
        "extension_id": expected_extension_id,
        "extension_dir": str(project_root() / "chrome-extension"),
        "native_host_manifest": str(host_manifest_path()),
        "extension_installed": extension_ok,
        "native_host_ready": host_ok,
        "native_host_registration": native_host_registration(expected_extension_id),
        "chrome_profile": profile,
        "runtime_state": runtime_state,
        "dependencies": dependency_status(),
        "preferences": preferences,
        "needs_language_setup": not bool(preferred_language),
    }
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
