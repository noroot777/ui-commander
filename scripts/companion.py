#!/opt/homebrew/opt/python@3.11/libexec/bin/python
"""Native messaging companion for screen-commander."""

from __future__ import annotations

import argparse
import base64
import html
import importlib
import importlib.util
import json
import locale
import os
import re
import shutil
import struct
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

try:
    from PIL import Image, ImageDraw
except Exception:  # noqa: BLE001
    Image = None
    ImageDraw = None

from preferences_store import read_preferences, normalize_language_tag


PROJECT_ROOT = Path(__file__).resolve().parent.parent
ROOT = PROJECT_ROOT / ".screen-commander" / "sessions"
LOG_PATH = PROJECT_ROOT / ".screen-commander" / "native-host.log"
LANGUAGE_PROFILE_PATH = PROJECT_ROOT / ".screen-commander" / "language-profile.json"
SERVER_INFO_PATH = PROJECT_ROOT / ".screen-commander" / "session-server.json"
RUNTIME_STATE_PATH = PROJECT_ROOT / ".screen-commander" / "runtime-state.json"
COMMON_COMMAND_PATHS = {
    "ffmpeg": [
        "/opt/homebrew/bin/ffmpeg",
        "/usr/local/bin/ffmpeg",
    ],
}
ACTIVE_AUDIO_RECORDERS: dict[str, dict[str, object]] = {}
SCRIPT_PATTERNS = {
    "zh": {
        "primary": re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]"),
        "secondary": re.compile(r"[\u3000-\u303f]"),
        "unexpected": re.compile(r"[\u3040-\u30ff\uac00-\ud7afA-Za-z]"),
    },
    "ja": {
        "primary": re.compile(r"[\u3040-\u30ff]"),
        "secondary": re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]"),
        "unexpected": re.compile(r"[\uac00-\ud7afA-Za-z]"),
    },
    "ko": {
        "primary": re.compile(r"[\uac00-\ud7af]"),
        "secondary": re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]"),
        "unexpected": re.compile(r"[\u3040-\u30ffA-Za-z]"),
    },
    "en": {
        "primary": re.compile(r"[A-Za-z]"),
        "secondary": re.compile(r"[0-9]"),
        "unexpected": re.compile(r"[\u3040-\u30ff\uac00-\ud7af\u3400-\u4dbf\u4e00-\u9fff]"),
    },
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def log_line(message: str) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(f"{utc_now()} {message}\n")

def read_language_profile() -> dict:
    if not LANGUAGE_PROFILE_PATH.exists():
        return {}
    try:
        payload = json.loads(LANGUAGE_PROFILE_PATH.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    return payload if isinstance(payload, dict) else {}


def write_language_profile(payload: dict) -> None:
    LANGUAGE_PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    LANGUAGE_PROFILE_PATH.write_text(
        json.dumps(payload, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )


def read_runtime_state() -> dict:
    if not RUNTIME_STATE_PATH.exists():
        return {}
    try:
        payload = json.loads(RUNTIME_STATE_PATH.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    return payload if isinstance(payload, dict) else {}


def write_runtime_state(payload: dict) -> None:
    RUNTIME_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    RUNTIME_STATE_PATH.write_text(
        json.dumps(payload, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )


def mark_extension_confirmed(session_id: str, url: str | None = None, title: str | None = None) -> None:
    state = read_runtime_state()
    state.update(
        {
            "extension_confirmed": True,
            "last_confirmed_session_id": session_id,
            "last_confirmed_at": utc_now(),
            "last_confirmed_url": url,
            "last_confirmed_title": title,
        }
    )
    write_runtime_state(state)


def macos_preferred_languages() -> list[str]:
    try:
        result = subprocess.run(
            ["defaults", "read", "-g", "AppleLanguages"],
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception:  # noqa: BLE001
        return []
    return re.findall(r'"([^"]+)"', result.stdout)


def build_language_candidates() -> tuple[list[str], dict[str, object]]:
    preferences = read_preferences()
    manual_language = normalize_language_tag(
        preferences.get("transcription", {}).get("preferred_language")
        if isinstance(preferences.get("transcription"), dict)
        else None
    )
    profile = read_language_profile()
    profile_counts = profile.get("counts", {}) if isinstance(profile.get("counts"), dict) else {}
    sorted_profile = sorted(
        ((str(language), int(count)) for language, count in profile_counts.items()),
        key=lambda item: item[1],
        reverse=True,
    )
    remembered = [language for language, count in sorted_profile if count > 0]
    preferred_language = normalize_language_tag(profile.get("preferred_language"))
    preferred_count = int(profile_counts.get(preferred_language, 0)) if preferred_language else 0

    system_candidates: list[str] = []
    for tag in macos_preferred_languages():
        normalized = normalize_language_tag(tag)
        if normalized:
            system_candidates.append(normalized)

    locale_info = locale.getlocale()
    locale_tag = locale_info[0] if locale_info else None
    normalized_locale = normalize_language_tag(locale_tag)
    if normalized_locale:
        system_candidates.append(normalized_locale)

    system_primary = system_candidates[0] if system_candidates else None
    trusted_preferred = preferred_language
    if trusted_preferred and system_primary and trusted_preferred != system_primary and preferred_count < 4:
        trusted_preferred = None

    ordered_candidates: list[str] = []
    for candidate in [manual_language, trusted_preferred, *system_candidates, *remembered]:
        if candidate and candidate not in ordered_candidates:
            ordered_candidates.append(candidate)

    candidates = ordered_candidates[:1]

    evidence = {
        "manual_preferred_language": manual_language,
        "preferred_language": preferred_language,
        "trusted_preferred_language": trusted_preferred,
        "preferred_language_count": preferred_count,
        "remembered_languages": remembered,
        "system_languages": system_candidates,
        "system_primary_language": system_primary,
        "all_candidates": ordered_candidates,
    }
    return candidates, evidence


def prepare_audio_for_transcription(audio_path: Path) -> tuple[Path, dict[str, object]]:
    preferences = read_preferences()
    vad_enabled = bool(preferences.get("transcription", {}).get("vad_enabled", True))
    metadata = {
        "enabled": vad_enabled,
        "source_audio": str(audio_path),
        "prepared_audio": str(audio_path),
        "used": False,
    }
    if not vad_enabled:
        return audio_path, metadata

    ffmpeg_path = find_command("ffmpeg")
    if ffmpeg_path is None:
        metadata["error"] = "ffmpeg not available"
        return audio_path, metadata

    prepared_path = audio_path.with_name(f"{audio_path.stem}.vad.wav")
    command = [
        ffmpeg_path,
        "-y",
        "-i",
        str(audio_path),
        "-af",
        "silenceremove=start_periods=1:start_silence=0.2:start_threshold=-45dB:"
        "stop_periods=-1:stop_silence=0.3:stop_threshold=-45dB",
        "-ac",
        "1",
        "-ar",
        "16000",
        str(prepared_path),
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode == 0 and prepared_path.exists() and prepared_path.stat().st_size > 0:
        metadata["prepared_audio"] = str(prepared_path)
        metadata["used"] = True
        return prepared_path, metadata

    metadata["error"] = (result.stderr or "").strip()[-240:]
    return audio_path, metadata


def score_transcript_for_language(text: str, language: str | None) -> float:
    cleaned = "".join(character for character in text if not character.isspace())
    if not cleaned:
        return 0.0
    if language not in SCRIPT_PATTERNS:
        return float(len(cleaned))

    patterns = SCRIPT_PATTERNS[language]
    primary = len(patterns["primary"].findall(cleaned))
    secondary = len(patterns["secondary"].findall(cleaned))
    unexpected = len(patterns["unexpected"].findall(cleaned))
    total = len(cleaned)
    length_bonus = min(total, 80)
    return (
        length_bonus
        + (primary / total) * 60
        + (secondary / total) * 20
        - (unexpected / total) * 70
    )


def select_best_transcription_attempt(attempts: list[dict]) -> dict:
    best = max(attempts, key=lambda attempt: attempt["score"])
    auto_attempt = next((attempt for attempt in attempts if attempt["requested_language"] is None), None)
    if auto_attempt and auto_attempt["score"] >= best["score"] + 8:
        return auto_attempt
    return best


def update_language_profile(language: str | None, score: float) -> None:
    normalized = normalize_language_tag(language)
    if not normalized or score < 20:
        return
    profile = read_language_profile()
    counts = profile.get("counts", {}) if isinstance(profile.get("counts"), dict) else {}
    system_candidates = []
    for tag in macos_preferred_languages():
        candidate = normalize_language_tag(tag)
        if candidate:
            system_candidates.append(candidate)
    system_primary = system_candidates[0] if system_candidates else None
    existing_count = int(counts.get(normalized, 0))
    if system_primary and normalized != system_primary and existing_count < 3:
        return
    counts[normalized] = int(counts.get(normalized, 0)) + 1
    preferred_language = max(counts.items(), key=lambda item: item[1])[0]
    write_language_profile(
        {
            "preferred_language": preferred_language,
            "counts": counts,
            "updated_at": utc_now(),
        }
    )


def session_dir(session_id: str) -> Path:
    return ROOT / session_id


def ensure_session(session_id: str) -> Path:
    path = session_dir(session_id)
    (path / "screenshots").mkdir(parents=True, exist_ok=True)
    (path / "audio").mkdir(parents=True, exist_ok=True)
    return path


def read_json(path: Path, default: object) -> object:
    if not path.exists():
        return default
    return json.loads(path.read_text())


def write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n")


def try_open_local_file(path: Path) -> bool:
    try:
        subprocess.run(["open", str(path)], check=False, capture_output=True)
        return True
    except Exception:  # noqa: BLE001
        return False


def try_open_url(url: str) -> bool:
    try:
        subprocess.run(["open", url], check=False, capture_output=True)
        return True
    except Exception:  # noqa: BLE001
        return False


def read_server_info() -> dict[str, object]:
    payload = read_json(SERVER_INFO_PATH, {})
    return payload if isinstance(payload, dict) else {}


def live_server_healthy(base_url: str | None) -> bool:
    if not base_url:
        return False
    try:
        with urlopen(f"{base_url.rstrip('/')}/health", timeout=1.5) as response:  # noqa: S310
            return response.status == 200
    except (URLError, OSError, ValueError):
        return False


def ensure_live_server(session_id: str) -> dict[str, object]:
    existing = read_server_info()
    base_url = existing.get("base_url")
    if isinstance(base_url, str) and live_server_healthy(base_url):
        return {
            **existing,
            "live_review_url": f"{base_url.rstrip('/')}/sessions/{session_id}/live",
            "reused": True,
        }

    server_script = PROJECT_ROOT / "scripts" / "session_server.py"
    try:
        subprocess.Popen(
            [sys.executable, str(server_script), "run"],
            cwd=PROJECT_ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception as exc:  # noqa: BLE001
        log_line(f"session_server_launch_error session_id={session_id} error={exc!r}")
        return {"started": False, "error": str(exc)}

    for _ in range(20):
        time.sleep(0.25)
        payload = read_server_info()
        candidate_base_url = payload.get("base_url")
        if isinstance(candidate_base_url, str) and live_server_healthy(candidate_base_url):
            return {
                **payload,
                "started": True,
                "live_review_url": f"{candidate_base_url.rstrip('/')}/sessions/{session_id}/live",
            }

    return {"started": False, "error": "session server did not become healthy in time"}


def launch_orchestrator(session_id: str) -> dict[str, object]:
    orchestrator_script = PROJECT_ROOT / "scripts" / "orchestrator.py"
    status_path = session_dir(session_id) / "agent-status.json"
    agent_review_path = session_dir(session_id) / "agent-review.html"
    try:
        subprocess.Popen(
            [sys.executable, str(orchestrator_script), "run", "--session", session_id],
            cwd=PROJECT_ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return {
            "triggered": True,
            "status_path": str(status_path),
            "agent_review_html": str(agent_review_path),
        }
    except Exception as exc:  # noqa: BLE001
        log_line(f"orchestrator_launch_error session_id={session_id} error={exc!r}")
        return {
            "triggered": False,
            "status_path": str(status_path),
            "agent_review_html": str(agent_review_path),
            "error": str(exc),
        }


def generate_review_html(session_path: Path, summary: dict) -> Path:
    review = summary.get("review", {}) if isinstance(summary.get("review"), dict) else {}
    transcript = str(review.get("transcript") or "")
    overlay_images = [str(item) for item in review.get("overlay_images", []) if item]
    crop_images = [str(item) for item in review.get("crop_images", []) if item]
    keyframes = [str(item) for item in review.get("keyframes", []) if item]
    transcription = summary.get("transcription", {}) if isinstance(summary.get("transcription"), dict) else {}
    model_name = str(transcription.get("model") or "unknown")
    selected_language = str(transcription.get("selected_language") or "auto")
    transcript_status = str(summary.get("transcript_status") or "unknown")

    image_cards = []
    for label, items in (
        ("Trajectory Overlays", overlay_images),
        ("Focus Crops", crop_images),
        ("Keyframes", keyframes),
    ):
        if not items:
            continue
        figures = "\n".join(
            (
                '<figure class="image-card">'
                f'<img src="{html.escape(Path(item).name)}" alt="{html.escape(label)}">'
                f'<figcaption>{html.escape(Path(item).name)}</figcaption>'
                "</figure>"
            )
            for item in items
            if Path(item).exists()
        )
        if figures:
            image_cards.append(
                f"<section><h2>{html.escape(label)}</h2><div class=\"image-grid\">{figures}</div></section>"
            )

    transcript_html = html.escape(transcript) if transcript else "No transcript was produced."
    page = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Screen Commander Review</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f6f1e8;
      --panel: #fffdf8;
      --ink: #1f2a24;
      --muted: #5f6b62;
      --line: #dccfb9;
      --accent: #12684c;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Iowan Old Style", "Palatino Linotype", serif;
      background:
        radial-gradient(circle at top right, rgba(18, 104, 76, 0.08), transparent 28rem),
        linear-gradient(180deg, #f9f5ee, var(--bg));
      color: var(--ink);
    }}
    main {{
      max-width: 1100px;
      margin: 0 auto;
      padding: 32px 24px 64px;
    }}
    h1, h2 {{ margin: 0 0 12px; }}
    p {{ margin: 0; }}
    .hero, section {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 20px;
      box-shadow: 0 14px 40px rgba(52, 44, 28, 0.08);
      margin-bottom: 20px;
    }}
    .meta {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 12px;
      margin-top: 16px;
    }}
    .meta-card {{
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 12px;
      background: rgba(18, 104, 76, 0.03);
    }}
    .label {{
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--muted);
      margin-bottom: 6px;
    }}
    .value {{
      font-size: 16px;
      font-weight: 600;
    }}
    .transcript {{
      white-space: pre-wrap;
      line-height: 1.6;
      font-size: 18px;
    }}
    .image-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
      gap: 16px;
    }}
    .image-card {{
      margin: 0;
      border: 1px solid var(--line);
      border-radius: 14px;
      overflow: hidden;
      background: #fff;
    }}
    .image-card img {{
      display: block;
      width: 100%;
      height: auto;
      background: #efe8da;
    }}
    figcaption {{
      padding: 10px 12px 12px;
      color: var(--muted);
      font-size: 13px;
    }}
    .hint {{
      color: var(--muted);
      margin-top: 10px;
      font-size: 14px;
    }}
  </style>
</head>
<body>
  <main>
    <section class="hero">
      <h1>Screen Commander Review</h1>
      <p class="hint">Review the trajectory overlays and transcript before asking an agent to patch code.</p>
      <div class="meta">
        <div class="meta-card">
          <div class="label">Session</div>
          <div class="value">{html.escape(str(summary.get("session_id") or session_path.name))}</div>
        </div>
        <div class="meta-card">
          <div class="label">Transcript Status</div>
          <div class="value">{html.escape(transcript_status)}</div>
        </div>
        <div class="meta-card">
          <div class="label">Model</div>
          <div class="value">{html.escape(model_name)}</div>
        </div>
        <div class="meta-card">
          <div class="label">Language</div>
          <div class="value">{html.escape(selected_language)}</div>
        </div>
      </div>
    </section>
    <section>
      <h2>Recognized Transcript</h2>
      <p class="transcript">{transcript_html}</p>
    </section>
    {"".join(image_cards)}
  </main>
</body>
</html>
"""
    review_path = session_path / "review.html"
    review_path.write_text(page, encoding="utf-8")
    return review_path


def append_jsonl(path: Path, payload: object) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=True) + "\n")


def start_session(payload: dict) -> dict:
    log_line(f"start_session url={payload.get('url')!r} title={payload.get('title')!r}")
    session_id = payload.get("session_id") or datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    path = ensure_session(session_id)
    meta = {
        "session_id": session_id,
        "created_at": utc_now(),
        "status": "recording",
        "url": payload.get("url"),
        "title": payload.get("title"),
    }
    write_json(path / "session.json", meta)
    mark_extension_confirmed(session_id, payload.get("url"), payload.get("title"))
    audio = start_native_audio_capture(session_id)
    if audio.get("ok"):
        append_jsonl(
            path / "events.jsonl",
            {
                "id": f"native-audio-start-{current_time_ms()}",
                "time": current_time_ms(),
                "type": "audio_status",
                "url": None,
                "title": None,
                "target": None,
                "value": f"native_recording:{audio.get('device_name')}:{audio.get('device_index')}",
                "screenshot": None,
            },
        )
    return {
        "ok": True,
        "session_id": session_id,
        "path": str(path),
        "native_audio": {
            "enabled": bool(audio.get("ok")),
            "device_name": audio.get("device_name"),
            "device_index": audio.get("device_index"),
        },
    }


def append_event(payload: dict) -> dict:
    session_id = payload["session_id"]
    log_line(f"append_event session_id={session_id} type={payload['event'].get('type')!r}")
    path = ensure_session(session_id)
    append_jsonl(path / "events.jsonl", payload["event"])
    return {"ok": True}


def append_log(payload: dict, name: str) -> dict:
    session_id = payload["session_id"]
    log_line(f"append_log session_id={session_id} name={name}")
    path = ensure_session(session_id)
    append_jsonl(path / f"{name}.jsonl", payload["entry"])
    return {"ok": True}


def write_artifact(payload: dict) -> dict:
    session_id = payload["session_id"]
    log_line(f"write_artifact session_id={session_id} path={payload.get('path')!r}")
    relative_path = payload["path"]
    data = payload["data"]
    encoding = payload.get("encoding", "base64")
    path = ensure_session(session_id) / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)

    if encoding == "base64":
        path.write_bytes(base64.b64decode(data))
    elif encoding == "utf8":
        path.write_text(data, encoding="utf-8")
    else:
        raise ValueError(f"unsupported encoding: {encoding}")

    return {"ok": True, "path": str(path)}


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def nearby_entries(entries: list[dict], event_time: int | None, window_ms: int) -> list[dict]:
    if event_time is None:
        return []
    return [
        entry
        for entry in entries
        if isinstance(entry.get("time"), int) and abs(entry["time"] - event_time) <= window_ms
    ]


def find_command(name: str) -> str | None:
    path = shutil.which(name)
    if path:
        return path
    for candidate in COMMON_COMMAND_PATHS.get(name, []):
        if Path(candidate).exists():
            return candidate
    return None


def dependency_status() -> dict[str, object]:
    whisper_installed = False
    whisper_spec = importlib.util.find_spec("whisper")
    if whisper_spec is not None:
        try:
            whisper = importlib.import_module("whisper")
            whisper_installed = hasattr(whisper, "load_model")
        except Exception:  # noqa: BLE001
            whisper_installed = False
    ffmpeg_available = find_command("ffmpeg") is not None
    return {
        "whisper_installed": whisper_installed,
        "ffmpeg_available": ffmpeg_available,
        "transcription_ready": whisper_installed and ffmpeg_available,
    }


def current_time_ms() -> int:
    return int(datetime.now().timestamp() * 1000)


def detect_default_input_name() -> str | None:
    try:
        result = subprocess.run(
            ["system_profiler", "SPAudioDataType"],
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception:  # noqa: BLE001
        return None

    current_device = None
    for raw_line in result.stdout.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped:
            continue
        if line.startswith("        ") and stripped.endswith(":") and not stripped.startswith("Default "):
            current_device = stripped[:-1]
            continue
        if "Default Input Device: Yes" in stripped:
            return current_device
    return None


def list_avfoundation_audio_devices(ffmpeg_path: str) -> list[dict[str, object]]:
    result = subprocess.run(
        [ffmpeg_path, "-f", "avfoundation", "-list_devices", "true", "-i", ""],
        capture_output=True,
        text=True,
        check=False,
    )
    devices = []
    in_audio_section = False
    for line in result.stderr.splitlines():
        if "AVFoundation audio devices:" in line:
            in_audio_section = True
            continue
        if not in_audio_section:
            continue
        match = re.search(r"\[(\d+)\]\s+(.*)$", line)
        if match:
            devices.append({
                "index": int(match.group(1)),
                "name": match.group(2).strip(),
            })
    return devices


def choose_audio_device(ffmpeg_path: str) -> dict[str, object] | None:
    devices = list_avfoundation_audio_devices(ffmpeg_path)
    if not devices:
        return None
    default_name = detect_default_input_name()
    if default_name:
        for device in devices:
            if str(device["name"]) == default_name:
                return device
    return devices[0]


def start_native_audio_capture(session_id: str) -> dict[str, object]:
    ffmpeg_path = find_command("ffmpeg")
    if ffmpeg_path is None:
        return {"ok": False, "error": "ffmpeg not available"}

    path = ensure_session(session_id)
    audio_path = path / "audio" / "mic.wav"
    if audio_path.exists():
        audio_path.unlink()

    device = choose_audio_device(ffmpeg_path)
    if device is None:
        return {"ok": False, "error": "no avfoundation audio device found"}

    process = subprocess.Popen(
        [
            ffmpeg_path,
            "-y",
            "-f",
            "avfoundation",
            "-i",
            f":{device['index']}",
            "-ac",
            "1",
            "-ar",
            "16000",
            str(audio_path),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    ACTIVE_AUDIO_RECORDERS[session_id] = {
        "process": process,
        "path": audio_path,
        "device_name": str(device["name"]),
        "device_index": int(device["index"]),
    }
    log_line(f"native_audio_start session_id={session_id} device={device['name']!r} index={device['index']}")
    return {
        "ok": True,
        "path": str(audio_path),
        "device_name": str(device["name"]),
        "device_index": int(device["index"]),
    }


def stop_native_audio_capture(session_id: str) -> dict[str, object]:
    recorder = ACTIVE_AUDIO_RECORDERS.pop(session_id, None)
    if recorder is None:
        return {"ok": True, "audio": None, "size": 0}

    process = recorder["process"]
    audio_path = recorder["path"]
    try:
        if process.stdin:
            process.stdin.write("q\n")
            process.stdin.flush()
            process.stdin.close()
        process.wait(timeout=5)
    except Exception:  # noqa: BLE001
        process.terminate()
        try:
            process.wait(timeout=2)
        except Exception:  # noqa: BLE001
            process.kill()

    size = audio_path.stat().st_size if audio_path.exists() else 0
    log_line(f"native_audio_stop session_id={session_id} size={size}")
    return {
        "ok": True,
        "audio": str(audio_path) if audio_path.exists() and size > 0 else None,
        "size": size,
        "device_name": recorder["device_name"],
        "device_index": recorder["device_index"],
    }


def transcribe_audio(audio_path: Path) -> tuple[str, list[dict], dict]:
    whisper_spec = importlib.util.find_spec("whisper")
    if whisper_spec is None:
        return "", [], {
            "selected_language": None,
            "detected_language": None,
            "selection_mode": "unavailable",
            "candidate_languages": [],
            "attempts": [],
            "language_evidence": {},
        }
    ffmpeg_path = find_command("ffmpeg")
    if ffmpeg_path is None:
        return "", [], {
            "selected_language": None,
            "detected_language": None,
            "selection_mode": "missing_ffmpeg",
            "candidate_languages": [],
            "attempts": [],
            "language_evidence": {},
        }
    ffmpeg_dir = str(Path(ffmpeg_path).parent)
    current_path = os.environ.get("PATH", "")
    if ffmpeg_dir not in current_path.split(":"):
        os.environ["PATH"] = f"{ffmpeg_dir}:{current_path}" if current_path else ffmpeg_dir

    whisper = importlib.import_module("whisper")
    if not hasattr(whisper, "load_model"):
        origin = getattr(whisper, "__file__", "unknown")
        raise RuntimeError(
            f"Installed whisper module is not the OpenAI transcription package: {origin}"
        )
    preferences = read_preferences()
    transcription_preferences = preferences.get("transcription", {})
    model_name = str(transcription_preferences.get("model") or "small")
    prepared_audio_path, vad_metadata = prepare_audio_for_transcription(audio_path)
    model = whisper.load_model(model_name)
    candidate_languages, evidence = build_language_candidates()
    attempts: list[dict] = []
    for candidate in [*candidate_languages, None]:
        options = {
            "verbose": False,
            "temperature": 0,
            "condition_on_previous_text": False,
            "fp16": False,
        }
        if candidate:
            options["language"] = candidate
        result = model.transcribe(str(prepared_audio_path), **options)
        text = (result.get("text") or "").strip()
        detected_language = normalize_language_tag(result.get("language"))
        score = score_transcript_for_language(text, candidate or detected_language)
        attempts.append(
            {
                "requested_language": candidate,
                "detected_language": detected_language,
                "score": round(score, 2),
                "text_length": len(text),
                "text_preview": text[:120],
                "result": result,
            }
        )

    best_attempt = select_best_transcription_attempt(attempts)
    result = best_attempt["result"]
    transcript = (result.get("text") or "").strip()
    segments = [
        {
            "start_time": round(segment.get("start", 0.0), 2),
            "end_time": round(segment.get("end", 0.0), 2),
            "text": (segment.get("text") or "").strip(),
        }
        for segment in result.get("segments", [])
    ]
    selected_language = normalize_language_tag(best_attempt["requested_language"] or best_attempt["detected_language"])
    update_language_profile(selected_language, float(best_attempt["score"]))
    metadata = {
        "model": model_name,
        "audio_input": str(prepared_audio_path),
        "vad": vad_metadata,
        "selected_language": selected_language,
        "detected_language": normalize_language_tag(result.get("language")),
        "selection_mode": "hinted" if best_attempt["requested_language"] else "auto",
        "candidate_languages": candidate_languages,
        "language_evidence": evidence,
        "attempts": [
            {
                "requested_language": attempt["requested_language"],
                "detected_language": attempt["detected_language"],
                "score": attempt["score"],
                "text_length": attempt["text_length"],
                "text_preview": attempt["text_preview"],
            }
            for attempt in attempts
        ],
    }
    return transcript, segments, metadata


def keyframe_events(events: list[dict]) -> list[dict]:
    return [
        event
        for event in events
        if event.get("type") == "screenshot_keyframe" and isinstance(event.get("screenshot"), str)
    ]


def nearest_keyframe(events: list[dict], target_time: int) -> dict | None:
    candidates = keyframe_events(events)
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda event: abs(int(event.get("time", 0)) - target_time),
    )


def render_focus_region_artifacts(
    session_path: Path,
    region_id: int,
    group: list[dict],
    bbox: dict[str, int],
    keyframe_event: dict | None,
) -> dict[str, str | None]:
    artifacts = {
        "keyframe": None,
        "overlay": None,
        "crop": None,
    }
    if keyframe_event is None:
        return artifacts

    keyframe_relative = str(keyframe_event.get("screenshot") or "")
    if not keyframe_relative:
        return artifacts
    artifacts["keyframe"] = str(session_path / keyframe_relative)

    if Image is None or ImageDraw is None:
        return artifacts

    keyframe_path = session_path / keyframe_relative
    if not keyframe_path.exists():
        return artifacts

    viewport = group[-1].get("viewport") if isinstance(group[-1].get("viewport"), dict) else {}
    viewport_width = max(int(viewport.get("width", 0) or 0), 1)
    viewport_height = max(int(viewport.get("height", 0) or 0), 1)

    with Image.open(keyframe_path) as source:
        overlay = source.convert("RGBA")
        scale_x = overlay.width / viewport_width if viewport_width else 1.0
        scale_y = overlay.height / viewport_height if viewport_height else 1.0

        draw = ImageDraw.Draw(overlay)
        points = []
        for event in group:
            x = event.get("x")
            y = event.get("y")
            if not isinstance(x, int) or not isinstance(y, int):
                continue
            points.append((round(x * scale_x), round(y * scale_y)))

        if len(points) >= 2:
            draw.line(points, fill=(255, 94, 58, 255), width=max(4, round(3 * scale_x)))
        for point in points[:: max(1, len(points) // 12 or 1)]:
            r = max(4, round(4 * scale_x))
            draw.ellipse((point[0] - r, point[1] - r, point[0] + r, point[1] + r), fill=(255, 228, 92, 230))

        scaled_bbox = (
            round(bbox["x_min"] * scale_x),
            round(bbox["y_min"] * scale_y),
            round(bbox["x_max"] * scale_x),
            round(bbox["y_max"] * scale_y),
        )
        draw.rounded_rectangle(
            scaled_bbox,
            radius=max(10, round(10 * scale_x)),
            outline=(0, 226, 150, 255),
            width=max(4, round(3 * scale_x)),
        )

        focus_dir = session_path / "focus_regions"
        focus_dir.mkdir(parents=True, exist_ok=True)
        overlay_path = focus_dir / f"region-{region_id}-overlay.png"
        overlay.convert("RGB").save(overlay_path)
        artifacts["overlay"] = str(overlay_path)

        pad_x = max(round(28 * scale_x), 24)
        pad_y = max(round(28 * scale_y), 24)
        crop_box = (
            max(0, scaled_bbox[0] - pad_x),
            max(0, scaled_bbox[1] - pad_y),
            min(overlay.width, scaled_bbox[2] + pad_x),
            min(overlay.height, scaled_bbox[3] + pad_y),
        )
        crop_path = focus_dir / f"region-{region_id}-crop.png"
        overlay.crop(crop_box).convert("RGB").save(crop_path)
        artifacts["crop"] = str(crop_path)

    return artifacts


def build_focus_regions(session_path: Path, events: list[dict]) -> list[dict]:
    stop_requested_time = min(
        (
            int(event.get("time", 0))
            for event in events
            if event.get("type") == "stop_requested" and isinstance(event.get("time"), int)
        ),
        default=None,
    )
    move_events = [
        event
        for event in events
        if event.get("type") == "mousemove"
        and (stop_requested_time is None or int(event.get("time", 0)) <= stop_requested_time)
    ]
    if not move_events:
        return []

    groups: list[list[dict]] = []
    current: list[dict] = []
    for event in move_events:
      if not current:
          current = [event]
          continue
      previous = current[-1]
      if int(event.get("time", 0)) - int(previous.get("time", 0)) <= 700:
          current.append(event)
      else:
          if len(current) >= 4:
              groups.append(current)
          current = [event]
    if len(current) >= 4:
        groups.append(current)

    focus_regions = []
    region_id = 1
    for group in groups:
        xs = [event.get("x") for event in group if isinstance(event.get("x"), int)]
        ys = [event.get("y") for event in group if isinstance(event.get("y"), int)]
        if len(xs) < 4 or len(ys) < 4:
            continue
        x_min = min(xs)
        x_max = max(xs)
        y_min = min(ys)
        y_max = max(ys)
        width = max(x_max - x_min, 1)
        height = max(y_max - y_min, 1)
        duration_ms = int(group[-1]["time"]) - int(group[0]["time"])
        path_length = 0.0
        for previous, current_event in zip(group, group[1:]):
            dx = int(current_event["x"]) - int(previous["x"])
            dy = int(current_event["y"]) - int(previous["y"])
            path_length += (dx * dx + dy * dy) ** 0.5
        start_end_dx = int(group[-1]["x"]) - int(group[0]["x"])
        start_end_dy = int(group[-1]["y"]) - int(group[0]["y"])
        start_end_distance = (start_end_dx * start_end_dx + start_end_dy * start_end_dy) ** 0.5
        region_size = max(width, height)
        if duration_ms >= 900 and start_end_distance <= max(24.0, region_size * 0.45) and path_length >= region_size * 3:
            gesture = "circle_like"
        elif duration_ms >= 700 and width <= 140 and height <= 140:
            gesture = "hover"
        else:
            gesture = "pointer_path"
        midpoint_time = int((int(group[0]["time"]) + int(group[-1]["time"])) / 2)
        artifacts = render_focus_region_artifacts(
            session_path=session_path,
            region_id=region_id,
            group=group,
            bbox={
                "x_min": x_min,
                "y_min": y_min,
                "x_max": x_max,
                "y_max": y_max,
            },
            keyframe_event=nearest_keyframe(events, midpoint_time),
        )
        focus_regions.append(
            {
                "region_id": region_id,
                "start_time": group[0]["time"],
                "end_time": group[-1]["time"],
                "duration_ms": duration_ms,
                "sample_count": len(group),
                "gesture": gesture,
                "centroid": {
                    "x": round(sum(xs) / len(xs), 1),
                    "y": round(sum(ys) / len(ys), 1),
                },
                "bbox": {
                    "x_min": x_min,
                    "y_min": y_min,
                    "x_max": x_max,
                    "y_max": y_max,
                    "width": width,
                    "height": height,
                },
                "target": group[-1].get("target"),
                "artifacts": artifacts,
                "path_points": [
                    {
                        "time": event.get("time"),
                        "x": event.get("x"),
                        "y": event.get("y"),
                    }
                    for event in group
                ],
            }
        )
        region_id += 1

    return focus_regions


def build_timeline(events: list[dict]) -> list[dict]:
    steps = []
    step_id = 1
    for event in events:
        if event.get("type") not in {"click", "dblclick", "input", "change", "submit", "navigation", "scroll", "keydown"}:
            continue
        steps.append(
            {
                "step_id": step_id,
                "time": event.get("time"),
                "type": event.get("type"),
                "url": event.get("url"),
                "target": event.get("target"),
                "value": event.get("value"),
                "key": event.get("key"),
                "x": event.get("x"),
                "y": event.get("y"),
                "navigationKind": event.get("navigationKind"),
                "screenshot": event.get("screenshot"),
            }
        )
        step_id += 1
    return steps


def finalize_session(payload: dict) -> dict:
    session_id = payload["session_id"]
    log_line(f"finalize_session session_id={session_id}")
    path = ensure_session(session_id)
    native_audio = stop_native_audio_capture(session_id)
    if native_audio.get("audio"):
        append_jsonl(
            path / "events.jsonl",
            {
                "id": f"native-audio-stop-{current_time_ms()}",
                "time": current_time_ms(),
                "type": "audio_status",
                "url": None,
                "title": None,
                "target": None,
                "value": f"native_saved:{native_audio.get('size', 0)}:{native_audio.get('device_name')}:{native_audio.get('device_index')}",
                "screenshot": None,
            },
        )
    events_path = path / "events.jsonl"
    events = load_jsonl(events_path)
    console_logs = load_jsonl(path / "console_logs.jsonl")
    network_logs = load_jsonl(path / "network_logs.jsonl")
    dependencies = dependency_status()

    timeline = build_timeline(events)
    focus_regions = build_focus_regions(path, events)
    for item in timeline:
        nearby_console = nearby_entries(console_logs, item.get("time"), 2000)
        nearby_network = nearby_entries(network_logs, item.get("time"), 2000)
        item["console"] = {
            "count": len(nearby_console),
            "errors": [entry for entry in nearby_console if entry.get("type") == "exception"],
        }
        item["network"] = {
            "count": len(nearby_network),
            "failures": [entry for entry in nearby_network if entry.get("type") == "loadingFailed"],
        }
    write_json(path / "interaction_timeline.json", timeline)
    write_json(path / "focus_regions.json", focus_regions)

    transcript = payload.get("transcript", "").strip()
    segments = payload.get("segments", [])
    transcription = {
        "selected_language": None,
        "detected_language": None,
        "selection_mode": "not_requested",
        "candidate_languages": [],
        "language_evidence": {},
        "attempts": [],
    }

    wav_audio_path = path / "audio" / "mic.wav"
    webm_audio_path = path / "audio" / "mic.webm"
    audio_path = wav_audio_path if wav_audio_path.exists() and wav_audio_path.stat().st_size > 0 else webm_audio_path
    transcript_status = "not_requested"
    if audio_path.exists() and not transcript:
        if dependencies["transcription_ready"]:
            try:
                transcript, segments, transcription = transcribe_audio(audio_path)
                transcript_status = "transcribed" if transcript else "audio_present_but_empty"
            except Exception as exc:  # noqa: BLE001
                log_line(f"transcription_error session_id={session_id} error={exc!r}")
                transcript_status = "transcription_error"
        else:
            transcript_status = "missing_dependencies"
    elif audio_path.exists():
        transcript_status = "provided"
    else:
        transcript_status = "no_audio"

    if transcript:
        (path / "transcript.txt").write_text(transcript + "\n", encoding="utf-8")

    write_json(path / "segments.json", segments)

    meta = read_json(path / "session.json", {})
    if isinstance(meta, dict):
        meta["status"] = "completed"
        meta["completed_at"] = utc_now()
        write_json(path / "session.json", meta)

    summary = {
        "session_id": session_id,
        "status": "completed",
        "event_count": len(events),
        "step_count": len(timeline),
        "focus_region_count": len(focus_regions),
        "console_entry_count": len(console_logs),
        "network_entry_count": len(network_logs),
        "has_transcript": bool(transcript),
        "transcript_status": transcript_status,
        "transcription": transcription,
        "dependencies": dependencies,
        "review": {
            "transcript": transcript,
            "overlay_images": [
                item.get("artifacts", {}).get("overlay")
                for item in focus_regions
                if item.get("artifacts", {}).get("overlay")
            ],
            "crop_images": [
                item.get("artifacts", {}).get("crop")
                for item in focus_regions
                if item.get("artifacts", {}).get("crop")
            ],
            "keyframes": [
                item.get("artifacts", {}).get("keyframe")
                for item in focus_regions
                if item.get("artifacts", {}).get("keyframe")
            ],
        },
        "artifacts": {
            "session": str(path / "session.json"),
            "timeline": str(path / "interaction_timeline.json"),
            "focus_regions": str(path / "focus_regions.json"),
            "focus_regions_dir": str(path / "focus_regions"),
            "events": str(events_path),
            "console_logs": str(path / "console_logs.jsonl"),
            "network_logs": str(path / "network_logs.jsonl"),
            "audio": str(audio_path),
            "transcript": str(path / "transcript.txt"),
            "segments": str(path / "segments.json"),
            "screenshots_dir": str(path / "screenshots"),
        },
    }
    review_html_path = generate_review_html(path, summary)
    summary["review"]["html"] = str(review_html_path)
    summary["artifacts"]["review_html"] = str(review_html_path)
    live_server = ensure_live_server(session_id)
    summary["live_review"] = live_server
    orchestrator = launch_orchestrator(session_id)
    summary["orchestrator"] = orchestrator
    summary["artifacts"]["agent_review_html"] = str(path / "agent-review.html")
    write_json(path / "summary.json", summary)
    live_review_url = live_server.get("live_review_url") if isinstance(live_server, dict) else None
    review_opened = try_open_url(live_review_url) if isinstance(live_review_url, str) else try_open_local_file(review_html_path)
    return {
        "ok": True,
        "summary_path": str(path / "summary.json"),
        "review_html": str(review_html_path),
        "live_review_url": live_review_url,
        "review_opened": review_opened,
        "orchestrator": orchestrator,
    }


def handle_message(message: dict) -> dict:
    command = message.get("command")
    log_line(f"handle_message command={command!r}")
    payload = message.get("payload", {})
    if command == "ping":
        return {"ok": True, "message": "pong"}
    if command == "start_session":
        return start_session(payload)
    if command == "append_event":
        return append_event(payload)
    if command == "append_console":
        return append_log(payload, "console_logs")
    if command == "append_network":
        return append_log(payload, "network_logs")
    if command == "write_artifact":
        return write_artifact(payload)
    if command == "finalize_session":
        return finalize_session(payload)
    return {"ok": False, "error": f"unknown command: {command}"}


def read_native_message() -> dict | None:
    raw_length = sys.stdin.buffer.read(4)
    if len(raw_length) == 0:
        return None
    message_length = struct.unpack("<I", raw_length)[0]
    data = sys.stdin.buffer.read(message_length).decode("utf-8")
    return json.loads(data)


def write_native_message(payload: dict) -> None:
    encoded = json.dumps(payload).encode("utf-8")
    try:
        sys.stdout.buffer.write(struct.pack("<I", len(encoded)))
        sys.stdout.buffer.write(encoded)
        sys.stdout.buffer.flush()
    except BrokenPipeError:
        log_line("native_host stdout closed")
        raise


def run_native_host() -> int:
    log_line("native_host ready")
    while True:
        message = read_native_message()
        if message is None:
            log_line("native_host stdin closed")
            return 0
        try:
            response = handle_message(message)
        except Exception as exc:  # noqa: BLE001
            log_line(f"native_host error={exc!r}")
            response = {"ok": False, "error": str(exc)}
        try:
            write_native_message(response)
        except BrokenPipeError:
            return 0


def run_finalize(session_id: str) -> int:
    response = finalize_session({"session_id": session_id})
    print(json.dumps(response, indent=2))
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("native-host")

    finalize = subparsers.add_parser("finalize")
    finalize.add_argument("--session", required=True)

    return parser.parse_args()


def main() -> int:
    ROOT.mkdir(parents=True, exist_ok=True)
    args = parse_args()
    if args.command == "native-host":
        return run_native_host()
    if args.command == "finalize":
        return run_finalize(args.session)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
