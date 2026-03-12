# Session Artifacts

Read this file only when you need the exact session contract.

Each session lives under:

```text
.screen-commander/sessions/<session-id>/
```

Core files:

- `session.json` - session metadata and lifecycle state
- `events.jsonl` - raw browser events in timestamp order
- `interaction_timeline.json` - reduced list of high-value interaction steps
- `focus_regions.json` - grouped pointer paths, hovers, and circle-like gestures
- `focus_regions/` - generated focus-region artifacts, including overlay images and cropped region shots when screenshots are available
- `console_logs.jsonl` - console output and runtime exceptions near the repro
- `network_logs.jsonl` - network requests, responses, and loading failures
- `audio/mic.wav` - microphone narration captured by the local companion
- `transcript.txt` - narration transcript when available
- `segments.json` - optional transcript segments
- `screenshots/` - screenshots keyed by event id plus periodic keyframes under `screenshots/keyframes/`
- `summary.json` - quick entry point for agents
- `live_review` in `summary.json` - localhost live review server info and URL for the current session when available
- `review.html` - auto-opened local review page with transcript and trajectory images
- `agent-request.json` - orchestrator payload handed to a downstream agent
- `agent-status.json` - orchestrator execution status
- `agent-result.md` - final agent output when orchestration is enabled

Timeline items are intended to be the first artifact an agent reads for click-heavy reproductions. For pointer-only reproductions, read `focus_regions.json` immediately after `summary.json`, then inspect the matching files in `focus_regions/`.
