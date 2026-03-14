#!/usr/bin/env python3
"""Inspect Windows native messaging registration for UI Commander."""

from __future__ import annotations

import json
import platform
from pathlib import Path

from install_native_host import HOST_NAME, host_entry_path, manifest_dir, windows_registry_entries
from state_paths import python_bin_path


def main() -> int:
    payload: dict[str, object] = {
        "platform": platform.system(),
        "host_name": HOST_NAME,
        "manifest_dir": str(manifest_dir()),
        "manifest_path": str(manifest_dir() / f"{HOST_NAME}.json"),
        "host_entry_path": str(host_entry_path()),
        "python_hint_path": str(python_bin_path()),
        "python_hint_exists": python_bin_path().exists(),
    }
    manifest_path = Path(payload["manifest_path"])
    payload["manifest_exists"] = manifest_path.exists()
    if manifest_path.exists():
        try:
            payload["manifest"] = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            payload["manifest_error"] = str(exc)

    if platform.system() == "Windows":
        registry = windows_registry_entries()
        payload["registry_entries"] = registry
        payload["registry_points_to_manifest"] = any(value == str(manifest_path) for value in registry.values())
    else:
        payload["registry_entries"] = {}
        payload["registry_points_to_manifest"] = False

    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
