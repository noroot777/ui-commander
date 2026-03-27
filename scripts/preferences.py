#!/usr/bin/env python3
"""Inspect or update ui-commander preferences."""

from __future__ import annotations

import argparse
import json

from preferences_store import read_preferences, update_preferences


def parse_bool(raw: str | None) -> bool | None:
    if raw is None:
        return None
    normalized = raw.strip().lower()
    if normalized in {"on", "true", "1", "yes"}:
        return True
    if normalized in {"off", "false", "0", "no"}:
        return False
    raise ValueError(f"unsupported boolean value: {raw}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")

    set_parser = subparsers.add_parser("set")
    set_parser.add_argument("--recording-mode", help="default recording mode: standard or dynamic")
    set_parser.add_argument("--next-recording-mode", help="one-shot recording mode for the next session")
    set_parser.add_argument("--clear-next-recording-mode", action="store_true", help="clear one-shot recording mode")
    set_parser.add_argument("--model", help="transcription model name")
    set_parser.add_argument("--language", help="preferred language tag, such as zh or en")
    set_parser.add_argument("--llm", help="on or off")
    set_parser.add_argument("--llm-model", help="llm intent fusion model name")
    set_parser.add_argument("--llm-images", help="on or off")
    set_parser.add_argument("--llm-max-regions", type=int, help="max focus regions to send to llm")
    set_parser.add_argument("--orchestrator", help="on or off")
    set_parser.add_argument("--orchestrator-mode", help="suggest or apply")
    set_parser.add_argument("--project-root", help="target project root for automatic agent runs")
    set_parser.add_argument("--auto-run", help="on or off")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "set":
        payload = update_preferences(
            recording_mode=args.recording_mode,
            next_recording_mode=args.next_recording_mode,
            clear_next_recording_mode=args.clear_next_recording_mode,
            model=args.model,
            preferred_language=args.language,
            llm_intent_enabled=parse_bool(args.llm),
            llm_intent_model=args.llm_model,
            llm_intent_include_images=parse_bool(args.llm_images),
            llm_intent_max_regions=args.llm_max_regions,
            orchestrator_enabled=parse_bool(args.orchestrator),
            orchestrator_mode=args.orchestrator_mode,
            project_root=args.project_root,
            auto_run=parse_bool(args.auto_run),
        )
    else:
        payload = read_preferences()
    print(json.dumps(payload, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
