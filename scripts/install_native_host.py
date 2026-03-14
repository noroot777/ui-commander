#!/usr/bin/env python3
"""Install the ui-commander native messaging host manifest for Chrome."""

from __future__ import annotations

import base64
import hashlib
import json
import platform
import sys
from pathlib import Path

from python_runtime import resolve_python_executable
from state_paths import ensure_state_root, python_bin_path, state_root

try:
    import winreg
except ImportError:  # pragma: no cover - Windows only
    winreg = None

HOST_NAME = "dev.codex.ui_commander"
LEGACY_HOST_NAMES = {"dev.codex.screen_commander"}


def manifest_dir() -> Path:
    system = platform.system()
    if system == "Windows":
        return state_root() / "native-messaging-hosts"
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support" / "Google" / "Chrome" / "NativeMessagingHosts"
    return Path.home() / ".config" / "google-chrome" / "NativeMessagingHosts"


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def legacy_host_entry_paths() -> set[str]:
    return {
        str(project_root() / "scripts" / "native_host_entry.sh"),
        str(project_root() / "scripts" / "native_host_entry.cmd"),
        str(project_root().parent / "screen-commander" / "scripts" / "native_host_entry.sh"),
        str(Path.home() / ".codex" / "skills" / "screen-commander" / "scripts" / "native_host_entry.sh"),
    }


def host_entry_path() -> Path:
    suffix = ".cmd" if platform.system() == "Windows" else ".sh"
    return project_root() / "scripts" / f"native_host_entry{suffix}"


def register_windows_manifest(manifest_path: Path) -> None:
    if winreg is None:
        raise RuntimeError("winreg is unavailable on this platform")
    for key_root in windows_registry_key_paths():
        key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, fr"{key_root}\{HOST_NAME}")
        with key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, str(manifest_path))


def windows_registry_key_paths() -> tuple[str, ...]:
    return (
        r"Software\Google\Chrome\NativeMessagingHosts",
        r"Software\WOW6432Node\Google\Chrome\NativeMessagingHosts",
    )


def windows_registry_entries() -> dict[str, str | None]:
    entries: dict[str, str | None] = {}
    if winreg is None:
        return entries
    for key_root in windows_registry_key_paths():
        full_key = fr"{key_root}\{HOST_NAME}"
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, full_key)
        except FileNotFoundError:
            entries[full_key] = None
            continue
        with key:
            try:
                value, _value_type = winreg.QueryValueEx(key, "")
            except FileNotFoundError:
                value = None
        entries[full_key] = value
    return entries


def extension_id_from_key(key_b64: str) -> str:
    digest = hashlib.sha256(base64.b64decode(key_b64)).hexdigest()[:32]
    return "".join(chr(ord("a") + int(char, 16)) for char in digest)


def extension_id() -> str:
    manifest = json.loads((project_root() / "chrome-extension" / "manifest.json").read_text())
    key = manifest.get("key")
    if not key:
        raise RuntimeError("chrome-extension/manifest.json is missing a stable key")
    return extension_id_from_key(key)


def main() -> int:
    target_dir = manifest_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    ensure_state_root()

    chrome_extension_id = extension_id()
    resolved_python = resolve_python_executable(sys.executable)
    host_entry = host_entry_path()
    host_entry_str = str(host_entry)

    # Remove older manifests for this same installed skill, including the
    # previous Screen Commander host name and install paths.
    legacy_paths = legacy_host_entry_paths()
    for manifest_path in target_dir.glob("*.json"):
        try:
            installed_manifest = json.loads(manifest_path.read_text())
        except Exception:  # noqa: BLE001
            continue
        installed_name = str(installed_manifest.get("name") or "")
        installed_path = str(installed_manifest.get("path") or "")
        if installed_name == HOST_NAME and installed_path == host_entry_str:
            continue
        if installed_name in LEGACY_HOST_NAMES or installed_path in legacy_paths or installed_path == host_entry_str:
            manifest_path.unlink()

    manifest = {
        "name": HOST_NAME,
        "description": "UI Commander native messaging host",
        "path": host_entry_str,
        "type": "stdio",
        "allowed_origins": [f"chrome-extension://{chrome_extension_id}/"],
    }

    target_path = target_dir / f"{HOST_NAME}.json"
    target_path.write_text(json.dumps(manifest, indent=2) + "\n")
    if platform.system() == "Windows":
        register_windows_manifest(target_path)
    python_bin_path().write_text(resolved_python + "\n")

    print(f"Wrote native host manifest to {target_path}")
    print(f"Expected extension id: {chrome_extension_id}")
    print(f"Recorded python executable: {resolved_python}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
