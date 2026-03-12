#!/usr/bin/env python3
"""Inspect or update host-mediated intent resolution artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from companion import generate_review_html
from intent_fusion import build_host_fusion_prompt, normalize_intent_resolution
from preferences_store import read_preferences
from state_paths import locate_session_dir, migrate_legacy_state


def read_json(path: Path, default: object) -> object:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return default


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    show_parser = subparsers.add_parser("show")
    show_parser.add_argument("--session", required=True)

    prompt_parser = subparsers.add_parser("prompt")
    prompt_parser.add_argument("--session", required=True)

    write_parser = subparsers.add_parser("write")
    write_parser.add_argument("--session", required=True)
    write_parser.add_argument("--input", required=True, help="json file path or - for stdin")
    write_parser.add_argument("--status", default="resolved", help="resolved, skipped, error, or pending_host_fusion")
    write_parser.add_argument("--reason", default="", help="optional status reason")
    return parser.parse_args()


def locate_or_raise(session_id: str) -> Path:
    session_dir = locate_session_dir(session_id)
    if session_dir is None:
        raise FileNotFoundError(f"Session not found: {session_id}")
    return session_dir


def prompt_command_for(session_dir: Path) -> str:
    script_path = Path(__file__).resolve()
    return f"python3 {script_path} prompt --session {session_dir.name}"


def load_input(source: str) -> dict:
    if source == "-":
        import sys

        raw = sys.stdin.read()
    else:
        raw = Path(source).read_text(encoding="utf-8")
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("resolution input must be a JSON object")
    return payload


def sync_summary(session_dir: Path, resolution: dict) -> Path:
    summary_path = session_dir / "summary.json"
    summary = read_json(summary_path, {})
    if not isinstance(summary, dict):
        summary = {}
    summary["llm_intent_status"] = str(resolution.get("status") or "not_run")
    summary["llm_resolved_intent_count"] = len(resolution.get("resolved_intents", [])) if isinstance(resolution.get("resolved_intents"), list) else 0
    summary["llm_intent"] = resolution
    review = summary.get("review", {}) if isinstance(summary.get("review"), dict) else {}
    review["intent_resolution"] = resolution
    summary["review"] = review
    artifacts = summary.get("artifacts", {}) if isinstance(summary.get("artifacts"), dict) else {}
    artifacts["intent_resolution"] = str(session_dir / "intent_resolution.json")
    artifacts["intent_evidence"] = str(session_dir / "intent_evidence.json")
    summary["artifacts"] = artifacts
    write_json(summary_path, summary)
    review_path = generate_review_html(session_dir, summary)
    summary["review"]["html"] = str(review_path)
    summary["artifacts"]["review_html"] = str(review_path)
    write_json(summary_path, summary)
    return review_path


def main() -> int:
    migrate_legacy_state()
    args = parse_args()
    session_dir = locate_or_raise(args.session)
    evidence_path = session_dir / "intent_evidence.json"
    resolution_path = session_dir / "intent_resolution.json"

    if args.command == "show":
        evidence = read_json(evidence_path, {})
        payload = {
            "session_id": session_dir.name,
            "session_dir": str(session_dir),
            "intent_evidence": str(evidence_path),
            "intent_resolution": str(resolution_path),
            "host_fusion_prompt_command": prompt_command_for(session_dir),
            "host_fusion_evidence_hash": evidence.get("evidence_hash") if isinstance(evidence, dict) else None,
            "resolution": read_json(resolution_path, {}),
        }
        print(json.dumps(payload, indent=2, ensure_ascii=True))
        return 0

    if args.command == "prompt":
        evidence = read_json(evidence_path, {})
        if not isinstance(evidence, dict) or not evidence:
            raise FileNotFoundError(f"Intent evidence not found for session: {session_dir.name}")
        print(build_host_fusion_prompt(evidence))
        return 0

    payload = load_input(args.input)
    evidence = read_json(evidence_path, {})
    preferences = read_preferences()
    llm_preferences = preferences.get("llm_intent", {}) if isinstance(preferences.get("llm_intent"), dict) else {}
    provider = str(llm_preferences.get("provider") or "host-thread")
    model = str(llm_preferences.get("model") or "gpt-5-mini")
    evidence_hash = str(evidence.get("evidence_hash") or "") if isinstance(evidence, dict) else ""
    resolution = normalize_intent_resolution(
        payload,
        model=model,
        provider=provider,
        status=args.status,
        reason=args.reason,
        evidence_hash=evidence_hash,
    )
    write_json(resolution_path, resolution)
    review_path = sync_summary(session_dir, resolution)
    print(
        json.dumps(
            {
                "ok": True,
                "session_id": session_dir.name,
                "intent_resolution": str(resolution_path),
                "review_html": str(review_path),
            },
            indent=2,
            ensure_ascii=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
