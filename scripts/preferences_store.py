#!/usr/bin/env python3
"""Persistent user preferences for ui-commander."""

from __future__ import annotations

import json

from state_paths import migrate_legacy_state, preferences_path

PREFERENCES_PATH = preferences_path()
DEFAULT_TRANSCRIPTION_MODEL = "small"
DEFAULT_LLM_MODEL = "gpt-5-mini"
SUPPORTED_TRANSCRIPTION_MODELS = (
    "tiny",
    "base",
    "small",
    "medium",
    "large-v3",
    "turbo",
)
LANGUAGE_ALIASES = {
    "zh": "zh",
    "zh-cn": "zh",
    "zh-hans": "zh",
    "zh-hans-cn": "zh",
    "zh-hant": "zh",
    "zh-hant-tw": "zh",
    "zh-tw": "zh",
    "en": "en",
    "en-us": "en",
    "en-gb": "en",
    "ja": "ja",
    "ja-jp": "ja",
    "ko": "ko",
    "ko-kr": "ko",
    "fr": "fr",
    "de": "de",
    "es": "es",
    "pt": "pt",
    "ru": "ru",
    "it": "it",
}


def normalize_language_tag(raw: str | None) -> str | None:
    if not raw:
        return None
    normalized = raw.strip().lower().replace("_", "-")
    if not normalized:
        return None
    if normalized in LANGUAGE_ALIASES:
        return LANGUAGE_ALIASES[normalized]
    base = normalized.split("-", 1)[0]
    return LANGUAGE_ALIASES.get(base)


def normalize_model_name(raw: str | None) -> str | None:
    if not raw:
        return None
    normalized = raw.strip().lower()
    if normalized == "large":
        normalized = "large-v3"
    return normalized if normalized in SUPPORTED_TRANSCRIPTION_MODELS else None


def normalize_llm_model_name(raw: str | None) -> str | None:
    if not raw:
        return None
    normalized = raw.strip()
    return normalized or None


def normalize_llm_provider(raw: str | None) -> str | None:
    if not raw:
        return None
    normalized = raw.strip().lower()
    return normalized if normalized in {"host-thread", "openai"} else None


def normalize_positive_int(raw: object, *, minimum: int, maximum: int) -> int | None:
    if raw is None or isinstance(raw, bool):
        return None
    try:
        value = int(raw)
    except Exception:  # noqa: BLE001
        return None
    if value < minimum or value > maximum:
        return None
    return value


def default_preferences() -> dict:
    return {
        "transcription": {
            "model": DEFAULT_TRANSCRIPTION_MODEL,
            "preferred_language": None,
        },
        "llm_intent": {
            "enabled": True,
            "provider": "host-thread",
            "model": DEFAULT_LLM_MODEL,
            "include_images": True,
            "max_regions": 3,
        },
        "orchestrator": {
            "enabled": True,
            "provider": "codex-cli",
            "mode": "apply",
            "project_root": "auto",
            "auto_run": False,
        },
    }


def read_preferences() -> dict:
    migrate_legacy_state()
    payload = default_preferences()
    if PREFERENCES_PATH.exists():
        try:
            stored = json.loads(PREFERENCES_PATH.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            stored = {}
        if isinstance(stored, dict):
            transcription = stored.get("transcription", {})
            if isinstance(transcription, dict):
                model = normalize_model_name(transcription.get("model"))
                language = normalize_language_tag(transcription.get("preferred_language"))
                if model:
                    payload["transcription"]["model"] = model
                payload["transcription"]["preferred_language"] = language
            llm_intent = stored.get("llm_intent", {})
            if isinstance(llm_intent, dict):
                enabled = llm_intent.get("enabled")
                provider = normalize_llm_provider(llm_intent.get("provider"))
                model = normalize_llm_model_name(llm_intent.get("model"))
                include_images = llm_intent.get("include_images")
                max_regions = normalize_positive_int(llm_intent.get("max_regions"), minimum=1, maximum=8)
                if isinstance(enabled, bool):
                    payload["llm_intent"]["enabled"] = enabled
                if provider:
                    payload["llm_intent"]["provider"] = provider
                if model:
                    payload["llm_intent"]["model"] = model
                if isinstance(include_images, bool):
                    payload["llm_intent"]["include_images"] = include_images
                if max_regions is not None:
                    payload["llm_intent"]["max_regions"] = max_regions
            orchestrator = stored.get("orchestrator", {})
            if isinstance(orchestrator, dict):
                enabled = orchestrator.get("enabled")
                provider = orchestrator.get("provider")
                mode = orchestrator.get("mode")
                project_root = orchestrator.get("project_root")
                auto_run = orchestrator.get("auto_run")
                if isinstance(enabled, bool):
                    payload["orchestrator"]["enabled"] = enabled
                if provider in {"codex-cli"}:
                    payload["orchestrator"]["provider"] = provider
                if mode in {"suggest", "apply"}:
                    payload["orchestrator"]["mode"] = mode
                if isinstance(project_root, str):
                    cleaned = project_root.strip()
                    payload["orchestrator"]["project_root"] = cleaned or "auto"
                if isinstance(auto_run, bool):
                    payload["orchestrator"]["auto_run"] = auto_run
    return payload


def write_preferences(payload: dict) -> dict:
    migrate_legacy_state()
    merged = default_preferences()
    transcription = payload.get("transcription", {}) if isinstance(payload, dict) else {}
    llm_intent = payload.get("llm_intent", {}) if isinstance(payload, dict) else {}
    orchestrator = payload.get("orchestrator", {}) if isinstance(payload, dict) else {}
    if isinstance(transcription, dict):
        model = normalize_model_name(transcription.get("model"))
        language = normalize_language_tag(transcription.get("preferred_language"))
        if model:
            merged["transcription"]["model"] = model
        merged["transcription"]["preferred_language"] = language
    if isinstance(llm_intent, dict):
        enabled = llm_intent.get("enabled")
        provider = normalize_llm_provider(llm_intent.get("provider"))
        model = normalize_llm_model_name(llm_intent.get("model"))
        include_images = llm_intent.get("include_images")
        max_regions = normalize_positive_int(llm_intent.get("max_regions"), minimum=1, maximum=8)
        if isinstance(enabled, bool):
            merged["llm_intent"]["enabled"] = enabled
        if provider:
            merged["llm_intent"]["provider"] = provider
        if model:
            merged["llm_intent"]["model"] = model
        if isinstance(include_images, bool):
            merged["llm_intent"]["include_images"] = include_images
        if max_regions is not None:
            merged["llm_intent"]["max_regions"] = max_regions
    if isinstance(orchestrator, dict):
        enabled = orchestrator.get("enabled")
        provider = orchestrator.get("provider")
        mode = orchestrator.get("mode")
        project_root = orchestrator.get("project_root")
        auto_run = orchestrator.get("auto_run")
        if isinstance(enabled, bool):
            merged["orchestrator"]["enabled"] = enabled
        if provider in {"codex-cli"}:
            merged["orchestrator"]["provider"] = provider
        if mode in {"suggest", "apply"}:
            merged["orchestrator"]["mode"] = mode
        if isinstance(project_root, str):
            merged["orchestrator"]["project_root"] = project_root.strip() or "auto"
        if isinstance(auto_run, bool):
            merged["orchestrator"]["auto_run"] = auto_run
    PREFERENCES_PATH.parent.mkdir(parents=True, exist_ok=True)
    PREFERENCES_PATH.write_text(
        json.dumps(merged, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    return merged


def update_preferences(
    *,
    model: str | None = None,
    preferred_language: str | None = None,
    llm_intent_enabled: bool | None = None,
    llm_intent_model: str | None = None,
    llm_intent_include_images: bool | None = None,
    llm_intent_max_regions: int | None = None,
    orchestrator_enabled: bool | None = None,
    orchestrator_mode: str | None = None,
    project_root: str | None = None,
    auto_run: bool | None = None,
) -> dict:
    payload = read_preferences()
    if model is not None:
        normalized_model = normalize_model_name(model)
        if normalized_model is None:
            raise ValueError(f"unsupported transcription model: {model}")
        payload["transcription"]["model"] = normalized_model
    if preferred_language is not None:
        normalized_language = normalize_language_tag(preferred_language)
        if normalized_language is None:
            raise ValueError(f"unsupported language tag: {preferred_language}")
        payload["transcription"]["preferred_language"] = normalized_language
    if llm_intent_enabled is not None:
        payload["llm_intent"]["enabled"] = bool(llm_intent_enabled)
    if llm_intent_model is not None:
        normalized_llm_model = normalize_llm_model_name(llm_intent_model)
        if normalized_llm_model is None:
            raise ValueError(f"unsupported llm model: {llm_intent_model}")
        payload["llm_intent"]["model"] = normalized_llm_model
    if llm_intent_include_images is not None:
        payload["llm_intent"]["include_images"] = bool(llm_intent_include_images)
    if llm_intent_max_regions is not None:
        normalized_llm_max_regions = normalize_positive_int(llm_intent_max_regions, minimum=1, maximum=8)
        if normalized_llm_max_regions is None:
            raise ValueError(f"unsupported llm max regions: {llm_intent_max_regions}")
        payload["llm_intent"]["max_regions"] = normalized_llm_max_regions
    if orchestrator_enabled is not None:
        payload["orchestrator"]["enabled"] = bool(orchestrator_enabled)
    if orchestrator_mode is not None:
        normalized_mode = orchestrator_mode.strip().lower()
        if normalized_mode not in {"suggest", "apply"}:
            raise ValueError(f"unsupported orchestrator mode: {orchestrator_mode}")
        payload["orchestrator"]["mode"] = normalized_mode
    if project_root is not None:
        payload["orchestrator"]["project_root"] = project_root.strip() or "auto"
    if auto_run is not None:
        payload["orchestrator"]["auto_run"] = bool(auto_run)
    return write_preferences(payload)
