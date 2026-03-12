#!/usr/bin/env python3
"""Host-mediated intent fusion helpers for screen-commander sessions."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


INTENT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "overall_summary": {"type": "string"},
        "resolved_intents": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "segment_indexes": {
                        "type": "array",
                        "items": {"type": "integer"},
                    },
                    "target_region_ids": {
                        "type": "array",
                        "items": {"type": "integer"},
                    },
                    "intent": {"type": "string"},
                    "scope": {"type": "string"},
                    "confidence": {"type": "number"},
                    "reason": {"type": "string"},
                },
                "required": [
                    "segment_indexes",
                    "target_region_ids",
                    "intent",
                    "scope",
                    "confidence",
                    "reason",
                ],
            },
        },
        "ambiguities": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "segment_indexes": {
                        "type": "array",
                        "items": {"type": "integer"},
                    },
                    "question": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["segment_indexes", "question", "reason"],
            },
        },
    },
    "required": ["overall_summary", "resolved_intents", "ambiguities"],
}

FUSION_INSTRUCTIONS = """You resolve user intent from browser session artifacts.

Use the evidence bundle and the provided region images to recover what the user likely wants changed in the UI.

Rules:
- Prefer evidence over guesswork.
- One utterance may refer to multiple disjoint UI regions. Return all relevant region ids when that is the best fit.
- If a DOM target looks polluted by the recorder cue, such as "Start recording" or "开始录制", trust the pointer path and image more than that target label.
- If the evidence is ambiguous, put the uncertainty into ambiguities instead of inventing certainty.
- Keep intents concise and implementation-oriented.
- Return JSON only.
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def compute_evidence_hash(payload: dict[str, object]) -> str:
    stable_payload = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(stable_payload.encode("utf-8")).hexdigest()


def _candidate_region_ids(referential_mentions: list[dict], focus_regions: list[dict], max_regions: int) -> list[int]:
    ordered: list[int] = []
    for mention in referential_mentions:
        candidates = mention.get("region_candidates", []) if isinstance(mention.get("region_candidates"), list) else []
        for candidate in candidates:
            region_id = candidate.get("region_id")
            if isinstance(region_id, int) and region_id not in ordered:
                ordered.append(region_id)
    if len(ordered) >= max_regions:
        return ordered[:max_regions]
    for region in focus_regions:
        region_id = region.get("region_id")
        if isinstance(region_id, int) and region_id not in ordered:
            ordered.append(region_id)
        if len(ordered) >= max_regions:
            break
    return ordered[:max_regions]


def _compact_target(target: object) -> dict[str, object] | None:
    if not isinstance(target, dict):
        return None
    return {
        "tag": target.get("tag"),
        "text": target.get("text"),
        "selector": target.get("selector"),
        "role": target.get("role"),
        "name": target.get("name"),
        "rect": target.get("rect"),
    }


def _compact_region(region: dict) -> dict[str, object]:
    artifacts = region.get("artifacts", {}) if isinstance(region.get("artifacts"), dict) else {}
    return {
        "region_id": region.get("region_id"),
        "gesture": region.get("gesture"),
        "attention_score": region.get("attention_score"),
        "click_count": region.get("click_count"),
        "start_time": region.get("start_time"),
        "end_time": region.get("end_time"),
        "bbox": region.get("bbox"),
        "centroid": region.get("centroid"),
        "target": _compact_target(region.get("target")),
        "artifacts": {
            "overlay": artifacts.get("overlay"),
            "crop": artifacts.get("crop"),
            "keyframe": artifacts.get("keyframe"),
        },
    }


def build_intent_evidence(
    *,
    session_id: str,
    transcript: str,
    segments: list[dict],
    referential_mentions: list[dict],
    focus_regions: list[dict],
    timeline: list[dict],
    console_logs: list[dict],
    network_logs: list[dict],
    max_regions: int,
) -> dict[str, object]:
    selected_ids = _candidate_region_ids(referential_mentions, focus_regions, max_regions=max_regions)
    selected_regions = [
        _compact_region(region)
        for region in focus_regions
        if isinstance(region.get("region_id"), int) and int(region["region_id"]) in selected_ids
    ]
    selected_regions.sort(key=lambda item: selected_ids.index(int(item["region_id"])))
    evidence = {
        "session_id": session_id,
        "transcript": transcript,
        "segments": [
            {
                "segment_index": segment.get("segment_index"),
                "text": segment.get("text"),
                "start_time": segment.get("start_time"),
                "end_time": segment.get("end_time"),
                "absolute_start_time_ms": segment.get("absolute_start_time_ms"),
                "absolute_end_time_ms": segment.get("absolute_end_time_ms"),
                "referential_terms": segment.get("referential_terms", []),
                "best_region_id": segment.get("best_region_id"),
                "region_candidate_ids": segment.get("region_candidate_ids", []),
            }
            for segment in segments
            if str(segment.get("text") or "").strip()
        ],
        "referential_mentions": [
            {
                "segment_index": mention.get("segment_index"),
                "text": mention.get("text"),
                "terms": mention.get("terms", []),
                "start_time": mention.get("start_time"),
                "end_time": mention.get("end_time"),
                "best_region_id": mention.get("best_region_id"),
                "region_candidates": [
                    {
                        "region_id": candidate.get("region_id"),
                        "gesture": candidate.get("gesture"),
                        "attention_score": candidate.get("attention_score"),
                        "overlap_ms": candidate.get("overlap_ms"),
                        "time_distance_ms": candidate.get("time_distance_ms"),
                        "target": _compact_target(candidate.get("target")),
                    }
                    for candidate in mention.get("region_candidates", [])
                    if isinstance(candidate, dict)
                ],
            }
            for mention in referential_mentions
        ],
        "selected_focus_regions": selected_regions,
        "timeline_excerpt": [
            {
                "step_id": item.get("step_id"),
                "time": item.get("time"),
                "type": item.get("type"),
                "target": _compact_target(item.get("target")),
                "x": item.get("x"),
                "y": item.get("y"),
                "navigationKind": item.get("navigationKind"),
            }
            for item in timeline[:12]
        ],
        "console_entry_count": len(console_logs),
        "network_entry_count": len(network_logs),
    }
    evidence["evidence_hash"] = compute_evidence_hash(evidence)
    return evidence


def _response_text(response_payload: dict) -> str:
    output_text = response_payload.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()

    parts: list[str] = []
    for item in response_payload.get("output", []):
        if not isinstance(item, dict):
            continue
        content = item.get("content", [])
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            text = block.get("text")
            if isinstance(text, str) and text.strip():
                parts.append(text.strip())
    return "\n".join(parts).strip()


def _strip_json_fence(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        return "\n".join(lines).strip()
    return text


def _normalize_resolution(payload: dict) -> dict[str, object]:
    overall_summary = str(payload.get("overall_summary") or "").strip()
    resolved_intents = []
    for item in payload.get("resolved_intents", []):
        if not isinstance(item, dict):
            continue
        segment_indexes = [
            int(value)
            for value in item.get("segment_indexes", [])
            if isinstance(value, int)
        ]
        target_region_ids = [
            int(value)
            for value in item.get("target_region_ids", [])
            if isinstance(value, int)
        ]
        resolved_intents.append(
            {
                "segment_indexes": segment_indexes,
                "target_region_ids": target_region_ids,
                "intent": str(item.get("intent") or "").strip(),
                "scope": str(item.get("scope") or "").strip(),
                "confidence": max(0.0, min(1.0, float(item.get("confidence") or 0.0))),
                "reason": str(item.get("reason") or "").strip(),
            }
        )

    ambiguities = []
    for item in payload.get("ambiguities", []):
        if not isinstance(item, dict):
            continue
        segment_indexes = [
            int(value)
            for value in item.get("segment_indexes", [])
            if isinstance(value, int)
        ]
        ambiguities.append(
            {
                "segment_indexes": segment_indexes,
                "question": str(item.get("question") or "").strip(),
                "reason": str(item.get("reason") or "").strip(),
            }
        )

    return {
        "overall_summary": overall_summary,
        "resolved_intents": resolved_intents,
        "ambiguities": ambiguities,
    }


def default_intent_resolution(
    *,
    status: str,
    model: str,
    provider: str,
    reason: str,
    evidence_hash: str = "",
) -> dict[str, object]:
    return {
        "status": status,
        "provider": provider,
        "model": model,
        "generated_at": utc_now(),
        "reason": reason,
        "evidence_hash": evidence_hash,
        "overall_summary": "",
        "resolved_intents": [],
        "ambiguities": [],
    }


def prepare_intent_artifacts(
    *,
    session_id: str,
    transcript: str,
    segments: list[dict],
    referential_mentions: list[dict],
    focus_regions: list[dict],
    timeline: list[dict],
    console_logs: list[dict],
    network_logs: list[dict],
    preferences: dict,
) -> dict[str, object]:
    llm_preferences = preferences.get("llm_intent", {}) if isinstance(preferences.get("llm_intent"), dict) else {}
    enabled = bool(llm_preferences.get("enabled", True))
    provider = str(llm_preferences.get("provider") or "host-thread").strip() or "host-thread"
    model = str(llm_preferences.get("model") or "gpt-5-mini").strip() or "gpt-5-mini"
    include_images = bool(llm_preferences.get("include_images", True))
    max_regions = int(llm_preferences.get("max_regions", 3) or 3)
    evidence = build_intent_evidence(
        session_id=session_id,
        transcript=transcript,
        segments=segments,
        referential_mentions=referential_mentions,
        focus_regions=focus_regions,
        timeline=timeline,
        console_logs=console_logs,
        network_logs=network_logs,
        max_regions=max(1, min(max_regions, 8)),
    )
    evidence_hash = str(evidence.get("evidence_hash") or "")
    evidence["host_fusion"] = {
        "provider": provider,
        "model": model,
        "include_images": include_images,
        "instructions": FUSION_INSTRUCTIONS,
        "response_schema": INTENT_SCHEMA,
    }

    if not enabled:
        return {
            "evidence": evidence,
            "resolution": default_intent_resolution(
                status="skipped",
                provider=provider,
                model=model,
                reason="llm intent fusion disabled",
                evidence_hash=evidence_hash,
            ),
        }

    if not transcript.strip():
        return {
            "evidence": evidence,
            "resolution": default_intent_resolution(
                status="skipped",
                provider=provider,
                model=model,
                reason="no transcript available",
                evidence_hash=evidence_hash,
            ),
        }

    return {
        "evidence": evidence,
        "resolution": default_intent_resolution(
            status="pending_host_fusion",
            provider=provider,
            model=model,
            reason="awaiting host thread fusion",
            evidence_hash=evidence_hash,
        ),
    }


def normalize_intent_resolution(
    payload: dict,
    *,
    model: str,
    provider: str,
    status: str = "resolved",
    reason: str = "",
    evidence_hash: str = "",
) -> dict[str, object]:
    normalized = _normalize_resolution(payload)
    return {
        "status": status,
        "provider": provider,
        "model": model,
        "generated_at": utc_now(),
        "reason": reason,
        "evidence_hash": evidence_hash,
        **normalized,
    }


def preserve_resolved_resolution(existing_resolution: object, *, evidence_hash: str = "") -> dict[str, object] | None:
    if not isinstance(existing_resolution, dict):
        return None
    if str(existing_resolution.get("status") or "").strip() != "resolved":
        return None
    has_content = bool(str(existing_resolution.get("overall_summary") or "").strip())
    resolved_intents = existing_resolution.get("resolved_intents")
    ambiguities = existing_resolution.get("ambiguities")
    if isinstance(resolved_intents, list) and resolved_intents:
        has_content = True
    if isinstance(ambiguities, list) and ambiguities:
        has_content = True
    if not has_content:
        return None
    preserved = dict(existing_resolution)
    if evidence_hash and not str(preserved.get("evidence_hash") or "").strip():
        preserved["evidence_hash"] = evidence_hash
    elif evidence_hash and str(preserved.get("evidence_hash") or "").strip() != evidence_hash:
        preserved["current_evidence_hash"] = evidence_hash
    return preserved


def build_host_fusion_prompt(evidence: dict[str, object]) -> str:
    schema = json.dumps(INTENT_SCHEMA, indent=2, ensure_ascii=True)
    bundle = json.dumps(evidence, indent=2, ensure_ascii=True)
    return (
        FUSION_INSTRUCTIONS.strip()
        + "\n\nUse the evidence bundle below as the primary source of truth for the resolution."
        + "\nDo not handcraft the answer from unrelated files first when this bundle is available."
        + "\n\nReturn JSON matching this schema exactly:\n"
        + schema
        + "\n\nEvidence bundle:\n"
        + bundle
    )
