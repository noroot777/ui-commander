#!/opt/homebrew/opt/python@3.11/libexec/bin/python
"""Install the screen-commander native messaging host manifest for Chrome."""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path


HOST_NAME = "dev.fjh.screen_commander"


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

    chrome_extension_id = extension_id()
    manifest = {
        "name": HOST_NAME,
        "description": "Screen Commander native messaging host",
        "path": str(project_root() / "scripts" / "native_host_entry.sh"),
        "type": "stdio",
        "allowed_origins": [f"chrome-extension://{chrome_extension_id}/"],
    }

    target_path = target_dir / f"{HOST_NAME}.json"
    target_path.write_text(json.dumps(manifest, indent=2) + "\n")

    print(f"Wrote native host manifest to {target_path}")
    print(f"Expected extension id: {chrome_extension_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
