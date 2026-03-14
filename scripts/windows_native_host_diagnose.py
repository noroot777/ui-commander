#!/usr/bin/env python3
"""Inspect Windows native messaging registration for UI Commander."""

from __future__ import annotations

import json
import platform
import struct
import subprocess
from pathlib import Path

from install_native_host import HOST_NAME, host_entry_path, manifest_dir, windows_registry_entries
from state_paths import native_host_log_path, python_bin_path


def tail_log_lines(path: Path, limit: int = 40) -> list[str]:
    if not path.exists():
        return []
    return path.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]


def smoke_test_host() -> dict[str, object]:
    if platform.system() != "Windows":
        return {"supported": False}

    command = ["cmd", "/c", str(host_entry_path())]
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except Exception as exc:  # noqa: BLE001
        return {"supported": True, "ok": False, "launch_error": str(exc)}

    request = json.dumps({"command": "get_preferences", "payload": {}}).encode("utf-8")
    response_payload: dict[str, object] = {"supported": True}
    try:
        assert process.stdin is not None
        assert process.stdout is not None
        process.stdin.write(struct.pack("<I", len(request)))
        process.stdin.write(request)
        process.stdin.flush()

        raw_length = process.stdout.read(4)
        if len(raw_length) != 4:
            response_payload["ok"] = False
            response_payload["error"] = "no valid native message header received"
        else:
            message_length = struct.unpack("<I", raw_length)[0]
            raw_body = process.stdout.read(message_length)
            response_payload["raw_response"] = raw_body.decode("utf-8", errors="replace")
            try:
                response_payload["response"] = json.loads(response_payload["raw_response"])
                response_payload["ok"] = True
            except Exception as exc:  # noqa: BLE001
                response_payload["ok"] = False
                response_payload["error"] = f"invalid json response: {exc}"
    except Exception as exc:  # noqa: BLE001
        response_payload["ok"] = False
        response_payload["error"] = str(exc)
    finally:
        try:
            if process.stdin:
                process.stdin.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            process.terminate()
        except Exception:  # noqa: BLE001
            pass
        try:
            stdout_data, stderr_data = process.communicate(timeout=2)
        except Exception:  # noqa: BLE001
            stdout_data, stderr_data = (b"", b"")
        response_payload["exit_code"] = process.returncode
        if stdout_data:
            response_payload["stdout_tail"] = stdout_data.decode("utf-8", errors="replace")[-500:]
        if stderr_data:
            response_payload["stderr_tail"] = stderr_data.decode("utf-8", errors="replace")[-500:]

    return response_payload


def main() -> int:
    log_path = native_host_log_path()
    stderr_log_path = log_path.with_name("native-host-stderr.log")
    python_hint_value = None
    if python_bin_path().exists():
        try:
            python_hint_value = python_bin_path().read_text(encoding="utf-8").strip() or None
        except Exception as exc:  # noqa: BLE001
            python_hint_value = f"<error: {exc}>"
    payload: dict[str, object] = {
        "platform": platform.system(),
        "host_name": HOST_NAME,
        "manifest_dir": str(manifest_dir()),
        "manifest_path": str(manifest_dir() / f"{HOST_NAME}.json"),
        "host_entry_path": str(host_entry_path()),
        "python_hint_path": str(python_bin_path()),
        "python_hint_exists": python_bin_path().exists(),
        "python_hint_value": python_hint_value,
        "native_host_log_path": str(log_path),
        "native_host_log_tail": tail_log_lines(log_path),
        "native_host_stderr_log_path": str(stderr_log_path),
        "native_host_stderr_log_tail": tail_log_lines(stderr_log_path),
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

    payload["smoke_test"] = smoke_test_host()

    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
