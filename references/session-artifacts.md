# Session Artifacts

Read this file only when you need the exact session contract.

Each session lives under:

```text
.screen-commander/sessions/<session-id>/
```

Agents may also receive a localhost live review URL such as:

```text
http://127.0.0.1:<port>/sessions/<session-id>/live
```

When that happens, extract `<session-id>` from the URL and resolve the matching local session directory before reading artifacts.

The live review page itself may provide copy buttons that generate trigger strings like:

```text
使用screen commander分析 http://127.0.0.1:<port>/sessions/<session-id>/live
使用screen commander分析并直接修复 http://127.0.0.1:<port>/sessions/<session-id>/live
```

Treat either pasted string the same as a direct session URL, while preserving the stronger "直接修复" intent from the user's message.

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
- `segments.json` - transcript segments, including absolute timeline alignment and nearby focus-region ids when available
- `referential_mentions.json` - phrases like "this", "that", "这个", or "这两个" with their time range and best nearby pointer hotspots
- `screenshots/` - screenshots keyed by event id plus periodic keyframes under `screenshots/keyframes/`
- `summary.json` - quick entry point for agents
- `summary.json.extension` - recorded extension version, current skill extension version, and whether the user needs to reload the unpacked Chrome extension
- `live_review` in `summary.json` - localhost live review server info and URL for the current session when available
- `review.html` - auto-opened local review page with transcript and trajectory images
- `agent-request.json` - orchestrator payload handed to a downstream agent
- `agent-status.json` - orchestrator execution status
- `agent-result.md` - final agent output when orchestration is enabled

Timeline items are intended to be the first artifact an agent reads for click-heavy reproductions. For pointer-only reproductions, read `focus_regions.json` immediately after `summary.json`, then inspect the matching files in `focus_regions/`. If the transcript uses deictic language such as "this area" or "these two buttons", read `referential_mentions.json` next to see which pointer hotspot was active around that phrase.
