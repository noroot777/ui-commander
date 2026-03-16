#!/usr/bin/env python3
"""Native messaging companion for ui-commander."""

from __future__ import annotations

import argparse
import base64
import html
import importlib
import importlib.util
import json
import locale
import os
import platform
import signal
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

from intent_fusion import prepare_intent_artifacts, preserve_resolved_resolution
from preferences_store import read_preferences, normalize_language_tag
from runtime_state import read_runtime_state, write_runtime_state
from state_paths import (
    all_session_dirs,
    latest_session_dir,
    language_profile_path,
    locate_session_dir,
    migrate_legacy_state,
    native_host_log_path,
    project_slug,
    runtime_state_path,
    session_path,
    sessions_dir,
    server_info_path,
)


PROJECT_ROOT = Path(__file__).resolve().parent.parent
ROOT = sessions_dir()
LOG_PATH = native_host_log_path()
LANGUAGE_PROFILE_PATH = language_profile_path()
SERVER_INFO_PATH = server_info_path()
RUNTIME_STATE_PATH = runtime_state_path()
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
DEICTIC_PATTERNS = {
    "zh": re.compile(r"这个地方|这一块|这两个|这个|这里|这边|这块|那个地方|那两个|那个|那里|那边"),
    "en": re.compile(r"\b(this|these|that|those|here|there)\b", re.IGNORECASE),
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def log_line(message: str) -> None:
    migrate_legacy_state()
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


def prepare_audio_for_transcription(audio_path: Path) -> Path:
    return audio_path


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


def select_best_transcription_attempt(
    attempts: list[dict],
    preferred_language: str | None = None,
) -> dict:
    if preferred_language:
        preferred_attempt = next(
            (
                attempt
                for attempt in attempts
                if attempt["requested_language"] == preferred_language
                and (attempt.get("result", {}).get("text") or "").strip()
            ),
            None,
        )
        if preferred_attempt:
            return preferred_attempt

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
    return session_path(session_id)


def session_project_root() -> str | None:
    runtime_state = read_runtime_state()
    active_project_root = runtime_state.get("active_project_root")
    if isinstance(active_project_root, str):
        value = active_project_root.strip()
        if value and value != "auto":
            return value
    preferences = read_preferences()
    orchestrator = preferences.get("orchestrator", {}) if isinstance(preferences.get("orchestrator"), dict) else {}
    project_root = orchestrator.get("project_root")
    if isinstance(project_root, str):
        value = project_root.strip()
        return value or None
    return None


def ensure_session(session_id: str, project_root: str | None = None) -> Path:
    path = session_path(session_id, project_root=project_root)
    (path / "screenshots").mkdir(parents=True, exist_ok=True)
    (path / "audio").mkdir(parents=True, exist_ok=True)
    return path


def read_json(path: Path, default: object) -> object:
    if not path.exists():
        return default
    return json.loads(path.read_text())


def write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n")


def current_skill_extension_version() -> str | None:
    manifest = read_json(PROJECT_ROOT / "chrome-extension" / "manifest.json", {})
    if not isinstance(manifest, dict):
        return None
    version = manifest.get("version")
    if not isinstance(version, str):
        return None
    value = version.strip()
    return value or None


def extension_version_status(recorded_version: object) -> dict[str, object]:
    recorded = recorded_version.strip() if isinstance(recorded_version, str) else None
    expected = current_skill_extension_version()
    return {
        "recorded_version": recorded,
        "expected_version": expected,
        "reload_required": bool(recorded and expected and recorded != expected),
        "known": bool(recorded),
    }


def event_time_ms(event: dict) -> int:
    return int(event.get("time", 0))


def point_distance(first: tuple[float, float], second: tuple[float, float]) -> float:
    dx = first[0] - second[0]
    dy = first[1] - second[1]
    return (dx * dx + dy * dy) ** 0.5


def target_signature(target: object) -> str | None:
    if not isinstance(target, dict):
        return None
    return "|".join(
        [
            str(target.get("selector") or ""),
            str(target.get("text") or ""),
            str(target.get("tag") or ""),
            str(target.get("name") or ""),
        ]
    )


def target_center(target: object) -> tuple[float, float] | None:
    if not isinstance(target, dict):
        return None
    rect = target.get("rect")
    if not isinstance(rect, dict):
        return None
    width = rect.get("width")
    height = rect.get("height")
    x = rect.get("x")
    y = rect.get("y")
    if not all(isinstance(value, (int, float)) for value in (x, y, width, height)):
        return None
    return (float(x) + float(width) / 2.0, float(y) + float(height) / 2.0)


def event_is_extension_cue(event: dict) -> bool:
    target = event.get("target")
    if not isinstance(target, dict):
        return False
    if bool(target.get("screenCommanderCue")):
        return True
    text = str(target.get("text") or "")
    return (
        ("开始录制" in text and "结束录制" in text)
        or ("Start speaking now" in text and "stop recording" in text.lower())
    )


def choose_region_target(events: list[dict]) -> dict | None:
    weighted_targets: dict[str, dict[str, object]] = {}
    fallback_target = None
    for index, event in enumerate(events):
        target = event.get("target")
        if not isinstance(target, dict):
            continue
        fallback_target = target
        signature = target_signature(target)
        if not signature:
            continue
        next_time = event_time_ms(events[index + 1]) if index + 1 < len(events) else event_time_ms(event) + 120
        dwell_ms = max(80, min(800, next_time - event_time_ms(event)))
        weight = dwell_ms
        if event.get("type") in {"click", "dblclick"}:
            weight += 1200
        bucket = weighted_targets.setdefault(signature, {"target": target, "weight": 0})
        bucket["weight"] = int(bucket["weight"]) + weight
        chosen = bucket["target"]
        chosen_text = str(chosen.get("text") or "")
        target_text = str(target.get("text") or "")
        if len(target_text) > len(chosen_text):
            bucket["target"] = target
    if not weighted_targets:
        return fallback_target
    best = max(weighted_targets.values(), key=lambda item: int(item["weight"]))
    return best.get("target") if isinstance(best.get("target"), dict) else fallback_target


def bbox_from_events(events: list[dict], target: dict | None = None) -> dict[str, int] | None:
    xs = [event.get("x") for event in events if isinstance(event.get("x"), int)]
    ys = [event.get("y") for event in events if isinstance(event.get("y"), int)]
    if not xs or not ys:
        return None
    x_min = min(xs)
    x_max = max(xs)
    y_min = min(ys)
    y_max = max(ys)
    if isinstance(target, dict) and isinstance(target.get("rect"), dict):
        rect = target["rect"]
        rect_x = rect.get("x")
        rect_y = rect.get("y")
        rect_width = rect.get("width")
        rect_height = rect.get("height")
        if all(isinstance(value, (int, float)) for value in (rect_x, rect_y, rect_width, rect_height)):
            x_min = min(x_min, round(float(rect_x)))
            y_min = min(y_min, round(float(rect_y)))
            x_max = max(x_max, round(float(rect_x) + float(rect_width)))
            y_max = max(y_max, round(float(rect_y) + float(rect_height)))
    return {
        "x_min": int(x_min),
        "y_min": int(y_min),
        "x_max": int(x_max),
        "y_max": int(y_max),
        "width": max(int(x_max) - int(x_min), 1),
        "height": max(int(y_max) - int(y_min), 1),
    }


def focus_region_score(gesture: str, duration_ms: int, sample_count: int, click_count: int) -> int:
    score = duration_ms + sample_count * 90 + click_count * 900
    if gesture == "circle_like":
        score += 800
    elif gesture == "click_focus":
        score += 1200
    elif gesture == "hover":
        score += 450
    return score


def gesture_priority(gesture: str) -> int:
    order = {
        "click_focus": 4,
        "circle_like": 3,
        "hover": 2,
        "pointer_focus": 1,
    }
    return order.get(gesture, 0)


def bbox_area(bbox: dict[str, int] | None) -> int:
    if not isinstance(bbox, dict):
        return 0
    return max(int(bbox.get("width", 0) or 0), 0) * max(int(bbox.get("height", 0) or 0), 0)


def bbox_overlap_area(first: dict[str, int] | None, second: dict[str, int] | None) -> int:
    if not isinstance(first, dict) or not isinstance(second, dict):
        return 0
    left = max(int(first.get("x_min", 0)), int(second.get("x_min", 0)))
    top = max(int(first.get("y_min", 0)), int(second.get("y_min", 0)))
    right = min(int(first.get("x_max", 0)), int(second.get("x_max", 0)))
    bottom = min(int(first.get("y_max", 0)), int(second.get("y_max", 0)))
    if right <= left or bottom <= top:
        return 0
    return (right - left) * (bottom - top)


def bbox_containment_ratio(container: dict[str, int] | None, candidate: dict[str, int] | None) -> float:
    candidate_area = bbox_area(candidate)
    if candidate_area <= 0:
        return 0.0
    return bbox_overlap_area(container, candidate) / candidate_area


def region_time_gap_ms(first: dict, second: dict) -> int:
    return max(
        0,
        max(int(first.get("start_time", 0)), int(second.get("start_time", 0)))
        - min(int(first.get("end_time", 0)), int(second.get("end_time", 0))),
    )


def region_centroid_distance(first: dict, second: dict) -> float:
    first_centroid = first.get("centroid", {}) if isinstance(first.get("centroid"), dict) else {}
    second_centroid = second.get("centroid", {}) if isinstance(second.get("centroid"), dict) else {}
    return point_distance(
        (float(first_centroid.get("x") or 0.0), float(first_centroid.get("y") or 0.0)),
        (float(second_centroid.get("x") or 0.0), float(second_centroid.get("y") or 0.0)),
    )


def choose_target_from_regions(regions: list[dict]) -> dict | None:
    weighted_targets: dict[str, dict[str, object]] = {}
    fallback_target = None
    for region in regions:
        target = region.get("target")
        if not isinstance(target, dict):
            continue
        fallback_target = target
        signature = target_signature(target)
        if not signature:
            continue
        weight = int(region.get("attention_score", 0) or 0) + int(region.get("click_count", 0) or 0) * 900
        bucket = weighted_targets.setdefault(signature, {"target": target, "weight": 0})
        bucket["weight"] = int(bucket["weight"]) + max(weight, 1)
        chosen = bucket["target"]
        chosen_text = str(chosen.get("text") or "")
        target_text = str(target.get("text") or "")
        if len(target_text) > len(chosen_text):
            bucket["target"] = target
    if not weighted_targets:
        return fallback_target
    best = max(weighted_targets.values(), key=lambda item: int(item["weight"]))
    return best.get("target") if isinstance(best.get("target"), dict) else fallback_target


def render_focus_region_from_points(
    session_path: Path,
    region_id: int,
    path_points: list[dict],
    bbox: dict[str, int],
    viewport: dict | None,
    events: list[dict],
    midpoint_time: int,
) -> dict[str, str | None]:
    render_events = [
        {
            "time": point.get("time"),
            "x": point.get("x"),
            "y": point.get("y"),
            "viewport": viewport,
        }
        for point in path_points
        if isinstance(point.get("x"), int) and isinstance(point.get("y"), int)
    ]
    return render_focus_region_artifacts(
        session_path=session_path,
        region_id=region_id,
        group=render_events,
        bbox={
            "x_min": bbox["x_min"],
            "y_min": bbox["y_min"],
            "x_max": bbox["x_max"],
            "y_max": bbox["y_max"],
        },
        keyframe_event=nearest_keyframe(events, midpoint_time),
    )


def build_region_from_merge(session_path: Path, region_id: int, regions: list[dict], events: list[dict]) -> dict:
    ordered_regions = sorted(regions, key=lambda item: int(item.get("start_time", 0)))
    ordered_points = sorted(
        [
            point
            for region in ordered_regions
            for point in region.get("path_points", [])
            if isinstance(point, dict) and isinstance(point.get("time"), int)
        ],
        key=lambda item: int(item.get("time", 0)),
    )
    start_time = min(int(region.get("start_time", 0)) for region in ordered_regions)
    end_time = max(int(region.get("end_time", 0)) for region in ordered_regions)
    duration_ms = max(0, end_time - start_time)
    click_count = sum(int(region.get("click_count", 0) or 0) for region in ordered_regions)
    bbox = {
        "x_min": min(int(region.get("bbox", {}).get("x_min", 0)) for region in ordered_regions),
        "y_min": min(int(region.get("bbox", {}).get("y_min", 0)) for region in ordered_regions),
        "x_max": max(int(region.get("bbox", {}).get("x_max", 0)) for region in ordered_regions),
        "y_max": max(int(region.get("bbox", {}).get("y_max", 0)) for region in ordered_regions),
    }
    bbox["width"] = max(bbox["x_max"] - bbox["x_min"], 1)
    bbox["height"] = max(bbox["y_max"] - bbox["y_min"], 1)
    xs = [int(point["x"]) for point in ordered_points if isinstance(point.get("x"), int)]
    ys = [int(point["y"]) for point in ordered_points if isinstance(point.get("y"), int)]
    gesture = max(
        (str(region.get("gesture") or "pointer_focus") for region in ordered_regions),
        key=gesture_priority,
    )
    viewport = next(
        (
            region.get("viewport")
            for region in sorted(ordered_regions, key=lambda item: -int(item.get("attention_score", 0) or 0))
            if isinstance(region.get("viewport"), dict)
        ),
        None,
    )
    attention_score = focus_region_score(gesture, duration_ms, len(ordered_points), click_count)
    artifacts = render_focus_region_from_points(
        session_path=session_path,
        region_id=region_id,
        path_points=ordered_points,
        bbox=bbox,
        viewport=viewport,
        events=events,
        midpoint_time=int((start_time + end_time) / 2),
    )
    return {
        "region_id": region_id,
        "start_time": start_time,
        "end_time": end_time,
        "duration_ms": duration_ms,
        "sample_count": len(ordered_points),
        "gesture": gesture,
        "attention_score": attention_score,
        "click_count": click_count,
        "centroid": {
            "x": round(sum(xs) / len(xs), 1) if xs else 0.0,
            "y": round(sum(ys) / len(ys), 1) if ys else 0.0,
        },
        "bbox": bbox,
        "target": choose_target_from_regions(ordered_regions),
        "viewport": viewport,
        "artifacts": artifacts,
        "path_points": ordered_points,
    }


def should_merge_focus_regions(first: dict, second: dict) -> bool:
    first_bbox = first.get("bbox")
    second_bbox = second.get("bbox")
    containment = max(
        bbox_containment_ratio(first_bbox, second_bbox),
        bbox_containment_ratio(second_bbox, first_bbox),
    )
    overlap_ratio = 0.0
    smallest_area = min(bbox_area(first_bbox), bbox_area(second_bbox))
    if smallest_area > 0:
        overlap_ratio = bbox_overlap_area(first_bbox, second_bbox) / smallest_area
    time_gap_ms = region_time_gap_ms(first, second)
    centroid_distance = region_centroid_distance(first, second)
    first_signature = target_signature(first.get("target"))
    second_signature = target_signature(second.get("target"))
    same_signature = bool(first_signature and second_signature and first_signature == second_signature)
    first_selector = str((first.get("target") or {}).get("selector") or "")
    second_selector = str((second.get("target") or {}).get("selector") or "")
    same_selector = bool(first_selector and second_selector and first_selector == second_selector)
    max_attention = max(int(first.get("attention_score", 0) or 0), int(second.get("attention_score", 0) or 0))
    min_attention = min(int(first.get("attention_score", 0) or 0), int(second.get("attention_score", 0) or 0))
    shorter_duration_ms = min(int(first.get("duration_ms", 0) or 0), int(second.get("duration_ms", 0) or 0))
    click_count = int(first.get("click_count", 0) or 0) + int(second.get("click_count", 0) or 0)

    if same_signature and containment >= 0.7 and time_gap_ms <= 7000 and click_count == 0:
        return True
    if same_signature and overlap_ratio >= 0.55 and centroid_distance <= 220 and time_gap_ms <= 3000:
        return True
    if same_selector and first_selector == "canvas" and overlap_ratio >= 0.95 and centroid_distance <= 40 and time_gap_ms <= 3000:
        return True
    if containment >= 0.88 and centroid_distance <= 120 and time_gap_ms <= 7000 and min_attention * 2 <= max_attention and shorter_duration_ms <= 2500 and click_count == 0:
        return True
    return False


def merge_focus_regions(session_path: Path, focus_regions: list[dict], events: list[dict]) -> list[dict]:
    if len(focus_regions) <= 1:
        return focus_regions

    ordered = sorted(focus_regions, key=lambda item: int(item.get("start_time", 0)))
    groups: list[list[dict]] = []
    consumed: set[int] = set()
    for index, region in enumerate(ordered):
        region_id = int(region.get("region_id", index + 1))
        if region_id in consumed:
            continue
        group = [region]
        consumed.add(region_id)
        changed = True
        while changed:
            changed = False
            for candidate in ordered:
                candidate_id = int(candidate.get("region_id", 0))
                if candidate_id in consumed:
                    continue
                if any(should_merge_focus_regions(member, candidate) for member in group):
                    group.append(candidate)
                    consumed.add(candidate_id)
                    changed = True
        groups.append(group)

    merged_regions = [
        build_region_from_merge(session_path, region_id=index + 1, regions=group, events=events)
        for index, group in enumerate(groups)
    ]
    merged_regions.sort(
        key=lambda item: (
            -int(item.get("attention_score", 0)),
            int(item.get("start_time", 0)),
        )
    )
    for index, region in enumerate(merged_regions, start=1):
        region["region_id"] = index
    for region in merged_regions:
        bbox = region.get("bbox")
        path_points = region.get("path_points", [])
        viewport = region.get("viewport") if isinstance(region.get("viewport"), dict) else None
        if not isinstance(bbox, dict):
            continue
        region["artifacts"] = render_focus_region_from_points(
            session_path=session_path,
            region_id=int(region.get("region_id", 0) or 0),
            path_points=path_points,
            bbox=bbox,
            viewport=viewport,
            events=events,
            midpoint_time=int((int(region.get("start_time", 0)) + int(region.get("end_time", 0))) / 2),
        )
    return merged_regions


def cleanup_focus_region_artifacts(session_path: Path, focus_regions: list[dict]) -> None:
    focus_dir = session_path / "focus_regions"
    if not focus_dir.exists():
        return
    keep_names = {
        Path(path).name
        for region in focus_regions
        for path in (
            (region.get("artifacts", {}) or {}).get("overlay"),
            (region.get("artifacts", {}) or {}).get("crop"),
        )
        if isinstance(path, str)
    }
    for artifact in focus_dir.glob("region-*.png"):
        if artifact.name not in keep_names:
            artifact.unlink(missing_ok=True)


def make_focus_region(session_path: Path, region_id: int, region_events: list[dict], events: list[dict], gesture: str) -> dict | None:
    if not region_events:
        return None
    target = choose_region_target(region_events)
    bbox = bbox_from_events(region_events, target=target)
    if bbox is None:
        return None
    xs = [int(event["x"]) for event in region_events if isinstance(event.get("x"), int)]
    ys = [int(event["y"]) for event in region_events if isinstance(event.get("y"), int)]
    if not xs or not ys:
        return None
    start_time = event_time_ms(region_events[0])
    end_time = event_time_ms(region_events[-1])
    duration_ms = max(0, end_time - start_time)
    click_count = sum(1 for event in region_events if event.get("type") in {"click", "dblclick"})
    score = focus_region_score(gesture, duration_ms, len(region_events), click_count)
    viewport = region_events[-1].get("viewport") if isinstance(region_events[-1].get("viewport"), dict) else None
    midpoint_time = int((start_time + end_time) / 2)
    artifacts = render_focus_region_artifacts(
        session_path=session_path,
        region_id=region_id,
        group=region_events,
        bbox={
            "x_min": bbox["x_min"],
            "y_min": bbox["y_min"],
            "x_max": bbox["x_max"],
            "y_max": bbox["y_max"],
        },
        keyframe_event=nearest_keyframe(events, midpoint_time),
    )
    return {
        "region_id": region_id,
        "start_time": start_time,
        "end_time": end_time,
        "duration_ms": duration_ms,
        "sample_count": len(region_events),
        "gesture": gesture,
        "attention_score": score,
        "click_count": click_count,
        "centroid": {
            "x": round(sum(xs) / len(xs), 1),
            "y": round(sum(ys) / len(ys), 1),
        },
        "bbox": bbox,
        "target": target,
        "viewport": viewport,
        "artifacts": artifacts,
        "path_points": [
            {
                "time": event.get("time"),
                "x": event.get("x"),
                "y": event.get("y"),
            }
            for event in region_events
            if isinstance(event.get("x"), int) and isinstance(event.get("y"), int)
        ],
    }


def build_move_focus_windows(move_events: list[dict]) -> list[list[dict]]:
    windows: list[list[dict]] = []
    index = 0
    while index < len(move_events):
        window = [move_events[index]]
        x_values = [int(move_events[index]["x"])]
        y_values = [int(move_events[index]["y"])]
        end = index
        while end + 1 < len(move_events):
            candidate = move_events[end + 1]
            if event_time_ms(candidate) - event_time_ms(move_events[end]) > 520:
                break
            next_x = candidate.get("x")
            next_y = candidate.get("y")
            if not isinstance(next_x, int) or not isinstance(next_y, int):
                break
            trial_xs = [*x_values, next_x]
            trial_ys = [*y_values, next_y]
            width = max(trial_xs) - min(trial_xs)
            height = max(trial_ys) - min(trial_ys)
            duration_ms = event_time_ms(candidate) - event_time_ms(window[0])
            max_size = 220 if duration_ms >= 900 else 170
            if width > max_size or height > max_size:
                break
            window.append(candidate)
            x_values = trial_xs
            y_values = trial_ys
            end += 1
        duration_ms = event_time_ms(window[-1]) - event_time_ms(window[0])
        if len(window) >= 4 and duration_ms >= 420:
            windows.append(window)
            index = end + 1
            continue
        index += 1
    return windows


def classify_move_focus_window(group: list[dict]) -> str:
    xs = [int(event["x"]) for event in group if isinstance(event.get("x"), int)]
    ys = [int(event["y"]) for event in group if isinstance(event.get("y"), int)]
    if len(xs) < 4 or len(ys) < 4:
        return "pointer_focus"
    width = max(xs) - min(xs)
    height = max(ys) - min(ys)
    duration_ms = event_time_ms(group[-1]) - event_time_ms(group[0])
    path_length = 0.0
    for previous, current_event in zip(group, group[1:]):
        dx = int(current_event["x"]) - int(previous["x"])
        dy = int(current_event["y"]) - int(previous["y"])
        path_length += (dx * dx + dy * dy) ** 0.5
    start_end_dx = int(group[-1]["x"]) - int(group[0]["x"])
    start_end_dy = int(group[-1]["y"]) - int(group[0]["y"])
    start_end_distance = (start_end_dx * start_end_dx + start_end_dy * start_end_dy) ** 0.5
    region_size = max(width, height, 1)
    if duration_ms >= 900 and start_end_distance <= max(24.0, region_size * 0.5) and path_length >= region_size * 2.4:
        return "circle_like"
    if duration_ms >= 650 and width <= 140 and height <= 140:
        return "hover"
    return "pointer_focus"


def attach_click_regions(focus_regions: list[dict], click_events: list[dict], session_path: Path, events: list[dict], next_region_id: int) -> tuple[list[dict], int]:
    for event in click_events:
        click_point = (
            float(event.get("x") or 0),
            float(event.get("y") or 0),
        )
        best_region = None
        best_distance = None
        for region in focus_regions:
            centroid = region.get("centroid", {})
            if not isinstance(centroid, dict):
                continue
            centroid_point = (
                float(centroid.get("x") or 0),
                float(centroid.get("y") or 0),
            )
            spatial_distance = point_distance(click_point, centroid_point)
            time_distance = min(
                abs(event_time_ms(event) - int(region.get("start_time", 0))),
                abs(event_time_ms(event) - int(region.get("end_time", 0))),
            )
            if spatial_distance > 120 or time_distance > 1400:
                continue
            combined = spatial_distance + (time_distance / 25.0)
            if best_distance is None or combined < best_distance:
                best_distance = combined
                best_region = region

        if best_region is not None:
            best_region["click_count"] = int(best_region.get("click_count", 0)) + 1
            best_region["attention_score"] = int(best_region.get("attention_score", 0)) + 900
            if isinstance(event.get("target"), dict):
                best_region["target"] = event["target"]
            bbox = best_region.get("bbox")
            if isinstance(bbox, dict) and isinstance(event.get("x"), int) and isinstance(event.get("y"), int):
                bbox["x_min"] = min(int(bbox["x_min"]), int(event["x"]))
                bbox["x_max"] = max(int(bbox["x_max"]), int(event["x"]))
                bbox["y_min"] = min(int(bbox["y_min"]), int(event["y"]))
                bbox["y_max"] = max(int(bbox["y_max"]), int(event["y"]))
                bbox["width"] = max(int(bbox["x_max"]) - int(bbox["x_min"]), 1)
                bbox["height"] = max(int(bbox["y_max"]) - int(bbox["y_min"]), 1)
            if isinstance(best_region.get("path_points"), list):
                best_region["path_points"].append(
                    {"time": event.get("time"), "x": event.get("x"), "y": event.get("y")}
                )
            best_region["start_time"] = min(int(best_region.get("start_time", event_time_ms(event))), event_time_ms(event))
            best_region["end_time"] = max(int(best_region.get("end_time", event_time_ms(event))), event_time_ms(event))
            best_region["duration_ms"] = int(best_region["end_time"]) - int(best_region["start_time"])
            continue

        new_region = make_focus_region(
            session_path=session_path,
            region_id=next_region_id,
            region_events=[event],
            events=events,
            gesture="click_focus",
        )
        if new_region is not None:
            focus_regions.append(new_region)
            next_region_id += 1
    return focus_regions, next_region_id


def extract_referential_terms(text: str, language: str | None) -> list[str]:
    normalized_language = normalize_language_tag(language)
    pattern = DEICTIC_PATTERNS.get(normalized_language or "")
    if pattern is None:
        pattern = DEICTIC_PATTERNS.get("en")
    if pattern is None:
        return []
    matches: list[str] = []
    for match in pattern.finditer(text):
        token = match.group(0)
        if token not in matches:
            matches.append(token)
    return matches


def aligned_transcript_segments(segments: list[dict], events: list[dict], language: str | None) -> list[dict]:
    anchor_event = next(
        (
            event
            for event in events
            if event.get("type") in {"session_started", "content_script_status", "page_ready"}
            and isinstance(event.get("time"), int)
        ),
        None,
    )
    anchor_time_ms = event_time_ms(anchor_event) if anchor_event else min((event_time_ms(event) for event in events), default=0)
    aligned: list[dict] = []
    for index, segment in enumerate(segments):
        start_time = float(segment.get("start_time", 0.0))
        end_time = float(segment.get("end_time", start_time))
        text = str(segment.get("text") or "").strip()
        absolute_start_time_ms = anchor_time_ms + round(start_time * 1000)
        absolute_end_time_ms = anchor_time_ms + round(end_time * 1000)
        aligned.append(
            {
                **segment,
                "segment_index": index,
                "text": text,
                "absolute_start_time_ms": absolute_start_time_ms,
                "absolute_end_time_ms": absolute_end_time_ms,
                "referential_terms": extract_referential_terms(text, language),
            }
        )
    return aligned


def build_referential_mentions(segments: list[dict], focus_regions: list[dict]) -> list[dict]:
    mentions: list[dict] = []
    for segment in segments:
        terms = [str(item) for item in segment.get("referential_terms", []) if item]
        if not terms:
            continue
        window_start = int(segment.get("absolute_start_time_ms", 0)) - 900
        window_end = int(segment.get("absolute_end_time_ms", 0)) + 900
        candidates = []
        for region in focus_regions:
            region_start = int(region.get("start_time", 0))
            region_end = int(region.get("end_time", 0))
            overlap_ms = max(0, min(region_end, window_end) - max(region_start, window_start))
            time_distance_ms = 0
            if overlap_ms == 0:
                if region_end < window_start:
                    time_distance_ms = window_start - region_end
                elif region_start > window_end:
                    time_distance_ms = region_start - window_end
            if overlap_ms == 0 and time_distance_ms > 2200:
                continue
            candidates.append(
                {
                    "region_id": region.get("region_id"),
                    "gesture": region.get("gesture"),
                    "attention_score": region.get("attention_score"),
                    "overlap_ms": overlap_ms,
                    "time_distance_ms": time_distance_ms,
                    "target": region.get("target"),
                    "bbox": region.get("bbox"),
                    "centroid": region.get("centroid"),
                }
            )
        candidates.sort(
            key=lambda item: (
                -int(item.get("overlap_ms", 0)),
                int(item.get("time_distance_ms", 0)),
                -int(item.get("attention_score", 0) or 0),
            )
        )
        mentions.append(
            {
                "segment_index": segment.get("segment_index"),
                "text": segment.get("text"),
                "terms": terms,
                "start_time": segment.get("start_time"),
                "end_time": segment.get("end_time"),
                "absolute_start_time_ms": segment.get("absolute_start_time_ms"),
                "absolute_end_time_ms": segment.get("absolute_end_time_ms"),
                "best_region_id": candidates[0]["region_id"] if candidates else None,
                "region_candidates": candidates[:3],
            }
        )
    return mentions


def try_open_local_file(path: Path) -> bool:
    try:
        if sys.platform == "darwin":
            subprocess.run(["open", str(path)], check=False, capture_output=True)
        elif os.name == "nt":
            os.startfile(str(path))
        else:
            subprocess.run(["xdg-open", str(path)], check=False, capture_output=True)
        return True
    except Exception:  # noqa: BLE001
        return False


def try_open_url(url: str) -> bool:
    try:
        if sys.platform == "darwin":
            subprocess.run(["open", url], check=False, capture_output=True)
        elif os.name == "nt":
            os.startfile(url)
        else:
            subprocess.run(["xdg-open", url], check=False, capture_output=True)
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
    server_script = PROJECT_ROOT / "scripts" / "session_server.py"
    expected_script_mtime_ns = server_script.stat().st_mtime_ns if server_script.exists() else None
    existing_script_mtime_ns = existing.get("script_mtime_ns")
    server_is_current = (
        isinstance(existing_script_mtime_ns, int)
        and expected_script_mtime_ns is not None
        and existing_script_mtime_ns == expected_script_mtime_ns
    )

    if isinstance(base_url, str) and live_server_healthy(base_url) and server_is_current:
        return {
            **existing,
            "live_review_url": f"{base_url.rstrip('/')}/sessions/{session_id}/live",
            "reused": True,
        }

    stale_pid = existing.get("pid")
    if isinstance(stale_pid, int):
        try:
            os.kill(stale_pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        except PermissionError:
            pass
        except OSError:
            pass

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
    referential_mentions = [
        item for item in review.get("referential_mentions", []) if isinstance(item, dict)
    ]
    transcription = summary.get("transcription", {}) if isinstance(summary.get("transcription"), dict) else {}
    llm_intent = summary.get("llm_intent", {}) if isinstance(summary.get("llm_intent"), dict) else {}
    model_name = str(transcription.get("model") or "unknown")
    selected_language = str(transcription.get("selected_language") or "auto")
    transcript_status = str(summary.get("transcript_status") or "unknown")
    llm_status = str(llm_intent.get("status") or "not_run")
    llm_model = str(llm_intent.get("model") or "n/a")

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

    mention_cards = []
    for mention in referential_mentions:
        terms = ", ".join(html.escape(str(item)) for item in mention.get("terms", []) if item)
        candidates = mention.get("region_candidates", []) if isinstance(mention.get("region_candidates"), list) else []
        best_candidate = candidates[0] if candidates and isinstance(candidates[0], dict) else {}
        target = best_candidate.get("target") if isinstance(best_candidate, dict) else {}
        target_label = ""
        if isinstance(target, dict):
            target_label = html.escape(str(target.get("text") or target.get("selector") or target.get("tag") or ""))
        detail_parts = []
        if terms:
            detail_parts.append(f"Terms: {terms}")
        if mention.get("best_region_id") is not None:
            detail_parts.append(f"Region #{html.escape(str(mention.get('best_region_id')))}")
        if target_label:
            detail_parts.append(f"Target: {target_label}")
        mention_cards.append(
            "<article class=\"mention-card\">"
            f"<div class=\"mention-time\">{html.escape(str(mention.get('start_time')))}s - {html.escape(str(mention.get('end_time')))}s</div>"
            f"<div class=\"mention-text\">{html.escape(str(mention.get('text') or ''))}</div>"
            f"<div class=\"mention-meta\">{' | '.join(detail_parts)}</div>"
            "</article>"
        )

    transcript_html = html.escape(transcript) if transcript else "No transcript was produced."
    referential_section = (
        "<section><h2>Referential Mentions</h2><div class=\"mention-list\">"
        + "".join(mention_cards)
        + "</div></section>"
        if mention_cards
        else ""
    )
    resolved_intents = [
        item for item in llm_intent.get("resolved_intents", []) if isinstance(item, dict)
    ]
    ambiguity_items = [
        item for item in llm_intent.get("ambiguities", []) if isinstance(item, dict)
    ]
    intent_cards = []
    for item in resolved_intents:
        region_ids = ", ".join(str(region_id) for region_id in item.get("target_region_ids", []) if isinstance(region_id, int))
        segment_indexes = ", ".join(str(index) for index in item.get("segment_indexes", []) if isinstance(index, int))
        detail_parts = []
        if segment_indexes:
            detail_parts.append(f"Segments: {segment_indexes}")
        if region_ids:
            detail_parts.append(f"Regions: {region_ids}")
        confidence = item.get("confidence")
        if isinstance(confidence, (int, float)):
            detail_parts.append(f"Confidence: {round(float(confidence), 2)}")
        intent_cards.append(
            "<article class=\"mention-card\">"
            f"<div class=\"mention-text\">{html.escape(str(item.get('intent') or ''))}</div>"
            f"<div class=\"mention-meta\">{html.escape(str(item.get('scope') or ''))}</div>"
            f"<div class=\"mention-meta\">{' | '.join(detail_parts)}</div>"
            f"<div class=\"mention-meta\">{html.escape(str(item.get('reason') or ''))}</div>"
            "</article>"
        )
    ambiguity_cards = []
    for item in ambiguity_items:
        segment_indexes = ", ".join(str(index) for index in item.get("segment_indexes", []) if isinstance(index, int))
        detail_parts = []
        if segment_indexes:
            detail_parts.append(f"Segments: {segment_indexes}")
        ambiguity_cards.append(
            "<article class=\"mention-card\">"
            f"<div class=\"mention-text\">{html.escape(str(item.get('question') or ''))}</div>"
            f"<div class=\"mention-meta\">{' | '.join(detail_parts)}</div>"
            f"<div class=\"mention-meta\">{html.escape(str(item.get('reason') or ''))}</div>"
            "</article>"
        )
    llm_reason = html.escape(str(llm_intent.get("reason") or ""))
    llm_summary = html.escape(str(llm_intent.get("overall_summary") or ""))
    llm_section = (
        "<section><h2>LLM Intent Fusion</h2>"
        f"<p class=\"hint\">Status: {html.escape(llm_status)} | Model: {html.escape(llm_model)}</p>"
        + (f"<p class=\"transcript\">{llm_summary}</p>" if llm_summary else "")
        + (f"<p class=\"hint\">{llm_reason}</p>" if llm_reason else "")
        + ("<div class=\"mention-list\">" + "".join(intent_cards) + "</div>" if intent_cards else "")
        + ("<h2>Open Questions</h2><div class=\"mention-list\">" + "".join(ambiguity_cards) + "</div>" if ambiguity_cards else "")
        + "</section>"
    )
    page = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>UI Commander Review</title>
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
    .mention-list {{
      display: grid;
      gap: 12px;
    }}
    .mention-card {{
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 14px;
      background: rgba(18, 104, 76, 0.03);
    }}
    .mention-time {{
      color: var(--muted);
      font-size: 12px;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      margin-bottom: 8px;
    }}
    .mention-text {{
      font-size: 16px;
      font-weight: 600;
      margin-bottom: 6px;
    }}
    .mention-meta {{
      font-size: 13px;
      color: var(--muted);
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
      <h1>UI Commander Review</h1>
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
        <div class="meta-card">
          <div class="label">LLM Intent</div>
          <div class="value">{html.escape(llm_status)}</div>
        </div>
      </div>
    </section>
    <section>
      <h2>Recognized Transcript</h2>
      <p class="transcript">{transcript_html}</p>
    </section>
    {llm_section}
    {referential_section}
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
    current_project_root = session_project_root()
    path = ensure_session(session_id, project_root=current_project_root)
    extension = extension_version_status(payload.get("extension_version"))
    meta = {
        "session_id": session_id,
        "created_at": utc_now(),
        "status": "recording",
        "url": payload.get("url"),
        "title": payload.get("title"),
        "project_root": current_project_root or "auto",
        "project_slug": project_slug(current_project_root),
        "extension": extension,
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
        "extension": extension,
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


def list_dshow_audio_devices(ffmpeg_path: str) -> list[dict[str, object]]:
    result = subprocess.run(
        [ffmpeg_path, "-list_devices", "true", "-f", "dshow", "-i", "dummy"],
        capture_output=True,
        text=True,
        check=False,
    )
    devices = []
    in_audio_section = False
    for line in result.stderr.splitlines():
        if "DirectShow audio devices" in line:
            in_audio_section = True
            continue
        if not in_audio_section:
            continue
        if "DirectShow video devices" in line:
            break
        if "Alternative name" in line:
            continue
        match = re.search(r'"([^"]+)"', line)
        if match:
            devices.append({
                "index": len(devices),
                "name": match.group(1).strip(),
            })
    return devices


def choose_audio_device(ffmpeg_path: str) -> dict[str, object] | None:
    system = platform.system()
    devices: list[dict[str, object]]
    if system == "Darwin":
        devices = list_avfoundation_audio_devices(ffmpeg_path)
    elif system == "Windows":
        devices = list_dshow_audio_devices(ffmpeg_path)
    else:
        return None
    if not devices:
        return None
    if system == "Darwin":
        default_name = detect_default_input_name()
        if default_name:
            for device in devices:
                if str(device["name"]) == default_name:
                    return device
    if system == "Windows":
        ranked_devices = sorted(
            devices,
            key=lambda device: (
                -int("microphone" in str(device["name"]).lower() or "mic" in str(device["name"]).lower()),
                -int("array" in str(device["name"]).lower() or "input" in str(device["name"]).lower()),
                int("stereo mix" in str(device["name"]).lower() or "virtual" in str(device["name"]).lower()),
                int(device["index"]),
            ),
        )
        return ranked_devices[0]
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
        return {"ok": False, "error": "no supported audio input device found"}

    system = platform.system()
    if system == "Darwin":
        input_format = "avfoundation"
        input_spec = f":{device['index']}"
    elif system == "Windows":
        input_format = "dshow"
        input_spec = f"audio={device['name']}"
    else:
        return {"ok": False, "error": f"native audio capture is not supported on {system}"}

    process = subprocess.Popen(
        [
            ffmpeg_path,
            "-y",
            "-f",
            input_format,
            "-i",
            input_spec,
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
    if ffmpeg_dir not in current_path.split(os.pathsep):
        os.environ["PATH"] = f"{ffmpeg_dir}{os.pathsep}{current_path}" if current_path else ffmpeg_dir

    whisper = importlib.import_module("whisper")
    if not hasattr(whisper, "load_model"):
        origin = getattr(whisper, "__file__", "unknown")
        raise RuntimeError(
            f"Installed whisper module is not the OpenAI transcription package: {origin}"
        )
    preferences = read_preferences()
    transcription_preferences = preferences.get("transcription", {})
    model_name = str(transcription_preferences.get("model") or "small")
    prepared_audio_path = prepare_audio_for_transcription(audio_path)
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

    preferred_candidate = normalize_language_tag(
        evidence.get("manual_preferred_language") or evidence.get("trusted_preferred_language")
    )
    best_attempt = select_best_transcription_attempt(attempts, preferred_language=preferred_candidate)
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
    pointer_events = [
        event
        for event in events
        if event.get("type") in {"mousemove", "click", "dblclick"}
        and not event_is_extension_cue(event)
        and (stop_requested_time is None or int(event.get("time", 0)) <= stop_requested_time)
    ]
    move_events = [event for event in pointer_events if event.get("type") == "mousemove"]
    click_events = [event for event in pointer_events if event.get("type") in {"click", "dblclick"}]
    if not move_events and not click_events:
        return []

    focus_regions = []
    region_id = 1
    for group in build_move_focus_windows(move_events):
        region = make_focus_region(
            session_path=session_path,
            region_id=region_id,
            region_events=group,
            events=events,
            gesture=classify_move_focus_window(group),
        )
        if region is None:
            continue
        focus_regions.append(region)
        region_id += 1

    focus_regions, region_id = attach_click_regions(
        focus_regions=focus_regions,
        click_events=click_events,
        session_path=session_path,
        events=events,
        next_region_id=region_id,
    )
    focus_regions = merge_focus_regions(session_path, focus_regions, events)
    cleanup_focus_region_artifacts(session_path, focus_regions)

    focus_regions.sort(
        key=lambda item: (
            -int(item.get("attention_score", 0)),
            int(item.get("start_time", 0)),
        )
    )
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

    aligned_segments = aligned_transcript_segments(
        segments=segments,
        events=events,
        language=transcription.get("selected_language") if isinstance(transcription, dict) else None,
    )
    referential_mentions = build_referential_mentions(aligned_segments, focus_regions)
    mentions_by_segment = {
        int(item.get("segment_index", -1)): item
        for item in referential_mentions
        if isinstance(item.get("segment_index"), int)
    }
    enriched_segments = []
    for segment in aligned_segments:
        mention = mentions_by_segment.get(int(segment.get("segment_index", -1)))
        enriched_segment = dict(segment)
        if mention:
            enriched_segment["best_region_id"] = mention.get("best_region_id")
            enriched_segment["region_candidate_ids"] = [
                candidate.get("region_id")
                for candidate in mention.get("region_candidates", [])
                if candidate.get("region_id") is not None
            ]
        enriched_segments.append(enriched_segment)

    if transcript:
        (path / "transcript.txt").write_text(transcript + "\n", encoding="utf-8")

    write_json(path / "segments.json", enriched_segments)
    write_json(path / "referential_mentions.json", referential_mentions)
    preferences = read_preferences()
    llm_artifacts = prepare_intent_artifacts(
        session_id=session_id,
        transcript=transcript,
        segments=enriched_segments,
        referential_mentions=referential_mentions,
        focus_regions=focus_regions,
        timeline=timeline,
        console_logs=console_logs,
        network_logs=network_logs,
        preferences=preferences,
    )
    llm_evidence = llm_artifacts.get("evidence", {}) if isinstance(llm_artifacts.get("evidence"), dict) else {}
    llm_intent = llm_artifacts.get("resolution", {}) if isinstance(llm_artifacts.get("resolution"), dict) else {}
    existing_intent = read_json(path / "intent_resolution.json", {})
    preserved_intent = preserve_resolved_resolution(
        existing_intent,
        evidence_hash=str(llm_evidence.get("evidence_hash") or ""),
    )
    if preserved_intent:
        llm_intent = preserved_intent
        log_line(
            "finalize_session preserve_resolved_intent "
            f"session_id={session_id} evidence_hash={llm_evidence.get('evidence_hash')!r}"
        )
    write_json(path / "intent_evidence.json", llm_evidence)
    write_json(path / "intent_resolution.json", llm_intent)

    meta = read_json(path / "session.json", {})
    if isinstance(meta, dict):
        meta["status"] = "completed"
        meta["completed_at"] = utc_now()
        meta["extension"] = extension_version_status(meta.get("extension", {}).get("recorded_version") if isinstance(meta.get("extension"), dict) else None)
        write_json(path / "session.json", meta)

    extension = meta.get("extension", {}) if isinstance(meta, dict) and isinstance(meta.get("extension"), dict) else extension_version_status(None)

    summary = {
        "session_id": session_id,
        "status": "completed",
        "event_count": len(events),
        "step_count": len(timeline),
        "focus_region_count": len(focus_regions),
        "referential_mention_count": len(referential_mentions),
        "console_entry_count": len(console_logs),
        "network_entry_count": len(network_logs),
        "has_transcript": bool(transcript),
        "transcript_status": transcript_status,
        "transcription": transcription,
        "llm_intent_status": str(llm_intent.get("status") or "not_run"),
        "llm_resolved_intent_count": len(llm_intent.get("resolved_intents", [])) if isinstance(llm_intent.get("resolved_intents"), list) else 0,
        "llm_intent": llm_intent,
        "dependencies": dependencies,
        "extension": extension,
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
            "referential_mentions": referential_mentions,
            "intent_resolution": llm_intent,
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
            "referential_mentions": str(path / "referential_mentions.json"),
            "intent_evidence": str(path / "intent_evidence.json"),
            "intent_resolution": str(path / "intent_resolution.json"),
            "screenshots_dir": str(path / "screenshots"),
        },
    }
    review_html_path = generate_review_html(path, summary)
    summary["review"]["html"] = str(review_html_path)
    summary["artifacts"]["review_html"] = str(review_html_path)
    # Persist the core review bundle before optional follow-on work so sessions remain usable
    # even if the live server or orchestrator step is slow or fails.
    write_json(path / "summary.json", summary)
    review_opened = try_open_local_file(review_html_path)
    log_line(f"finalize_session review_ready session_id={session_id} opened={review_opened}")
    log_line(f"finalize_session ensure_live_server_start session_id={session_id}")
    live_server = ensure_live_server(session_id)
    log_line(
        "finalize_session ensure_live_server_done "
        f"session_id={session_id} started={live_server.get('started') if isinstance(live_server, dict) else None} "
        f"reused={live_server.get('reused') if isinstance(live_server, dict) else None} "
        f"error={live_server.get('error') if isinstance(live_server, dict) else None}"
    )
    summary["live_review"] = live_server
    log_line(f"finalize_session launch_orchestrator_start session_id={session_id}")
    orchestrator = launch_orchestrator(session_id)
    log_line(
        "finalize_session launch_orchestrator_done "
        f"session_id={session_id} triggered={orchestrator.get('triggered') if isinstance(orchestrator, dict) else None} "
        f"error={orchestrator.get('error') if isinstance(orchestrator, dict) else None}"
    )
    summary["orchestrator"] = orchestrator
    summary["artifacts"]["agent_review_html"] = str(path / "agent-review.html")
    write_json(path / "summary.json", summary)
    live_review_url = live_server.get("live_review_url") if isinstance(live_server, dict) else None
    if isinstance(live_review_url, str):
        review_opened = try_open_url(live_review_url) or review_opened
    log_line(f"finalize_session complete session_id={session_id} review_opened={review_opened}")
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
    if command == "get_preferences":
        return {"ok": True, "preferences": read_preferences()}
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


def ensure_native_host_binary_stdio() -> None:
    if os.name != "nt":
        return
    import msvcrt

    msvcrt.setmode(sys.stdin.fileno(), os.O_BINARY)
    msvcrt.setmode(sys.stdout.fileno(), os.O_BINARY)


def run_native_host() -> int:
    ensure_native_host_binary_stdio()
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
