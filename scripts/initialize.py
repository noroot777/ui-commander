#!/usr/bin/env python3
"""Initialize ui-commander after the skill files have been installed."""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

from preferences_store import update_preferences
from python_runtime import resolve_python_executable


PROJECT_ROOT = Path(__file__).resolve().parent.parent
PYTHON_BIN = resolve_python_executable(sys.executable)


def run_command(command: list[str], label: str, timeout: int = 1800) -> dict[str, object]:
    try:
        result = subprocess.run(
            command,
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        return {
            "label": label,
            "command": command,
            "ok": False,
            "error": str(exc),
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "label": label,
            "command": command,
            "ok": False,
            "error": f"timed out after {timeout}s",
            "stdout_tail": (exc.stdout or "")[-1200:],
            "stderr_tail": (exc.stderr or "")[-1200:],
        }
    return {
        "label": label,
        "command": command,
        "ok": result.returncode == 0,
        "returncode": result.returncode,
        "stdout_tail": result.stdout[-1200:],
        "stderr_tail": result.stderr[-1200:],
    }


def run_python_script(script_name: str, args: list[str], label: str, timeout: int = 1800) -> dict[str, object]:
    return run_command([PYTHON_BIN, str(PROJECT_ROOT / "scripts" / script_name), *args], label, timeout=timeout)


def load_status() -> dict[str, object]:
    result = run_python_script("status.py", [], "status", timeout=60)
    if not result.get("ok"):
        raise RuntimeError(f"Unable to read status: {result}")
    raw = str(result.get("stdout_tail") or "").strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:  # noqa: PERF203
        raise RuntimeError(f"Unable to parse status payload: {exc}: {raw}") from exc


def install_whisper() -> dict[str, object]:
    uninstall_result = run_command(
        [PYTHON_BIN, "-m", "pip", "uninstall", "-y", "whisper"],
        "remove_incompatible_whisper",
        timeout=300,
    )
    install_result = run_command(
        [PYTHON_BIN, "-m", "pip", "install", "openai-whisper"],
        "install_openai_whisper",
        timeout=1800,
    )
    return {
        "label": "install_transcription_python_package",
        "ok": bool(install_result.get("ok")),
        "steps": [uninstall_result, install_result],
    }


def install_ffmpeg() -> dict[str, object]:
    system = platform.system()
    if system == "Windows":
        if shutil.which("winget"):
            return run_command(
                [
                    "winget",
                    "install",
                    "--id",
                    "Gyan.FFmpeg",
                    "--exact",
                    "--accept-package-agreements",
                    "--accept-source-agreements",
                ],
                "install_ffmpeg_with_winget",
                timeout=1800,
            )
        if shutil.which("choco"):
            return run_command(["choco", "install", "ffmpeg", "-y"], "install_ffmpeg_with_choco", timeout=1800)
        return {
            "label": "install_ffmpeg",
            "ok": False,
            "error": "No supported Windows package manager found (winget or choco).",
        }
    if system == "Darwin":
        if shutil.which("brew"):
            return run_command(["brew", "install", "ffmpeg"], "install_ffmpeg_with_brew", timeout=1800)
        return {
            "label": "install_ffmpeg",
            "ok": False,
            "error": "Homebrew is not available.",
        }
    if system == "Linux" and hasattr(os, "geteuid") and os.geteuid() == 0:
        if shutil.which("apt-get"):
            update_result = run_command(["apt-get", "update"], "apt_update", timeout=1800)
            install_result = run_command(["apt-get", "install", "-y", "ffmpeg"], "install_ffmpeg_with_apt", timeout=1800)
            return {
                "label": "install_ffmpeg",
                "ok": bool(update_result.get("ok")) and bool(install_result.get("ok")),
                "steps": [update_result, install_result],
            }
        if shutil.which("dnf"):
            return run_command(["dnf", "install", "-y", "ffmpeg"], "install_ffmpeg_with_dnf", timeout=1800)
    return {
        "label": "install_ffmpeg",
        "ok": False,
        "error": "Automatic ffmpeg installation is not supported on this machine.",
    }


def build_next_steps(after: dict[str, object]) -> list[str]:
    next_steps: list[str] = []
    state = str(after.get("state") or "unknown")
    dependencies = after.get("dependencies", {})
    if state == "not_installed":
        extension_dir = after.get("extension_dir")
        next_steps.append(
            "Open chrome://extensions, enable Developer mode, click 'Load unpacked', and select "
            f"{extension_dir}."
        )
    elif state == "extension_installed":
        next_steps.append("The Chrome extension is present, but the Native Messaging bridge still needs attention.")
        if platform.system() == "Windows":
            next_steps.append(f"Run {PYTHON_BIN} {PROJECT_ROOT / 'scripts' / 'windows_native_host_diagnose.py'} if recording still fails.")
    if isinstance(dependencies, dict):
        hints = dependencies.get("install_hints", {})
        if not dependencies.get("whisper_installed"):
            next_steps.append(f"Speech transcription still needs openai-whisper. Hint: {hints.get('whisper')}")
        if not dependencies.get("ffmpeg_available"):
            next_steps.append(f"Audio processing still needs ffmpeg. Hint: {hints.get('ffmpeg')}")
    if after.get("needs_language_setup"):
        next_steps.append("Ask the user for their usual narration language, then save it before the first narrated recording.")
    return next_steps


def language_prompt(after: dict[str, object]) -> dict[str, str] | None:
    if not after.get("needs_language_setup"):
        return None
    return {
        "question": "What language do you usually use when narrating frontend bugs?",
        "hint": "Examples: zh, en, ja",
        "field": "preferred_language",
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--open", action="store_true", help="open Chrome extension setup UI when needed")
    parser.add_argument("--no-open", action="store_true", help="avoid opening Chrome during initialization")
    parser.add_argument("--skip-deps", action="store_true", help="skip installing optional transcription dependencies")
    parser.add_argument("--language", help="preferred narration language tag, such as zh, en, or ja")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    before = load_status()
    actions: list[dict[str, object]] = []

    if args.language:
        try:
            preferences = update_preferences(preferred_language=args.language)
            actions.append(
                {
                    "label": "set_preferred_language",
                    "ok": True,
                    "language": preferences.get("transcription", {}).get("preferred_language"),
                }
            )
        except ValueError as exc:
            actions.append(
                {
                    "label": "set_preferred_language",
                    "ok": False,
                    "error": str(exc),
                    "language": args.language,
                }
            )

    dependencies = before.get("dependencies", {})
    if isinstance(dependencies, dict) and not args.skip_deps:
        if not dependencies.get("whisper_installed"):
            actions.append(install_whisper())
        if not dependencies.get("ffmpeg_available"):
            actions.append(install_ffmpeg())

    state = str(before.get("state") or "unknown")
    if state != "ready_to_record" or args.open:
        setup_args = ["--open"] if args.open or state == "not_installed" else ["--no-open"]
        actions.append(run_python_script("setup.py", setup_args, "setup", timeout=600))

    after = load_status()
    recording_ready = str(after.get("state") or "") == "ready_to_record"
    after_dependencies = after.get("dependencies", {})
    language_configured = not bool(after.get("needs_language_setup"))
    transcription_ready = bool(
        isinstance(after_dependencies, dict) and after_dependencies.get("transcription_ready")
    )
    payload = {
        "ok": recording_ready,
        "recording_ready": recording_ready,
        "transcription_ready": transcription_ready,
        "language_configured": language_configured,
        "fully_initialized": recording_ready and transcription_ready and language_configured,
        "before": before,
        "actions": actions,
        "after": after,
        "language_prompt": language_prompt(after),
        "next_steps": build_next_steps(after),
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0 if recording_ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
