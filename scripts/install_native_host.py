#!/usr/bin/env python3
"""Install the screen-commander native messaging host manifest for Chrome."""

from __future__ import annotations

import base64
import hashlib
import json
import sys
from pathlib import Path

from python_runtime import resolve_python_executable
from state_paths import ensure_state_root, python_bin_path

HOST_NAME = "dev.codex.screen_commander"


def manifest_dir() -> Path:
    return Path.home() / "Library" / "Application Support" / "Google" / "Chrome" / "NativeMessagingHosts"


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


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
    host_entry_path = str(project_root() / "scripts" / "native_host_entry.sh")

    # Remove older manifests for this same installed skill without encoding
    # any machine-specific or developer-specific host name in source.
    for manifest_path in target_dir.glob("*.json"):
        try:
            installed_manifest = json.loads(manifest_path.read_text())
        except Exception:  # noqa: BLE001
            continue
        if installed_manifest.get("path") != host_entry_path:
            continue
        if installed_manifest.get("name") == HOST_NAME:
            continue
        manifest_path.unlink()

    manifest = {
        "name": HOST_NAME,
        "description": "Screen Commander native messaging host",
        "path": host_entry_path,
        "type": "stdio",
        "allowed_origins": [f"chrome-extension://{chrome_extension_id}/"],
    }

    target_path = target_dir / f"{HOST_NAME}.json"
    target_path.write_text(json.dumps(manifest, indent=2) + "\n")
    python_bin_path().write_text(resolved_python + "\n")

    print(f"Wrote native host manifest to {target_path}")
    print(f"Expected extension id: {chrome_extension_id}")
    print(f"Recorded python executable: {resolved_python}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
