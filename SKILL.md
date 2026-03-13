name: ui-commander
description: Capture a frontend bug reproduction inside the user's existing Chrome session, or resume from an existing UI Commander session URL, then turn the session into structured artifacts for any local coding agent to inspect. Use this skill when the user wants to demonstrate a bug by clicking through the real app, narrating what should happen, handing the resulting session to an agent for analysis, or simply pasting text like `使用ui commander分析 http://127.0.0.1:47321/sessions/<session-id>/live` or `使用ui commander分析并直接修复 http://127.0.0.1:47321/sessions/<session-id>/live`.
---

# UI Commander

Use this skill when the user wants to show a frontend bug in their normal Chrome session instead of describing it in text, or when the user already has a UI Commander session URL and wants the agent to continue from that recorded session. Also trigger it when the user pastes a ready-made prompt such as `使用ui commander分析 <session-url>` or `使用ui commander分析并直接修复 <session-url>`.

This skill is designed to work across local coding-agent hosts such as Codex, Claude Code, OpenCode, and similar environments. The default path should stay host-agnostic: use the current conversation, current workspace, and local helper scripts. Treat any detached background runner as optional and platform-specific.

The skill has one job: convert a narrated browser reproduction into structured session artifacts.

This skill is stateful. On normal triggers, default to direct start instead of running a readiness checklist first. Do not start by telling the user to run commands. Prefer to run local helper scripts yourself and only ask the user for Chrome UI actions. If recording fails to start or stop, diagnose and repair the bridge at that point.

In command examples below, `<python-bin>` means the user's available Python 3 executable for this skill. Usually that is `python3`, but it may also be a venv path or another machine-specific interpreter path.

Default to a fresh recording on every new trigger. Ignore any previously recorded session in the same IDE thread unless the user explicitly asks to reuse or analyze that earlier recording.

## Workflow

1. If the user already provided a UI Commander session URL or session id, resolve that session immediately and continue from its artifacts. Do not ask the user to record again unless they explicitly want a fresh repro.
2. Otherwise, default the target project to the current workspace. Only override it when the user explicitly wants to send the session to a different repo.
3. Keep saved transcription preferences as-is by default. Only ask for narration language when it is clearly missing and will block understanding later.
4. Do not ask about transcription models by default. Only change models when the current transcript quality is poor or the user explicitly asks. When the user chooses a stronger model, persist that model so future sessions keep using it afterwards.
5. Enter blocking watch mode before the user records. This is the default and only primary interaction mode for this skill.
6. When watch mode starts, bind the current workspace as the active project root for the upcoming session.
7. Once recording can begin, send one short bold reminder in the IDE chat. Keep it visually prominent and concise, and always adapt the shortcuts to the user's platform. Example on macOS: `**现在请切到 Chrome，按 Option+S 开始，按 Option+E 结束。**` Example on Windows or Linux: `**现在请切到 Chrome，按 Alt+S 开始，按 Alt+E 结束。**`
8. Tell the user to focus the target Chrome tab, then use the platform-appropriate shortcuts to record: `Option+S` and `Option+E` on macOS, `Alt+S` and `Alt+E` on Windows or Linux.
9. If start or stop fails, then run local diagnosis and repair: use `scripts/status.py` to inspect readiness and `scripts/setup.py` to repair the bridge when needed.
10. Wait only for the next newly created finalized session in the current conversation. Do not reuse an older session just because its files changed or the conversation was reopened.
11. Use the current conversation to analyze and, when appropriate, apply code changes. Do not rely on a detached background task or any platform-specific CLI runner as the primary path.

## Existing Session URLs

When the user provides a localhost UI Commander URL such as `http://127.0.0.1:47321/sessions/<session-id>/live`, or gives a raw session id, skip watch mode and resolve it directly:

```bash
<python-bin> <skill-dir>/scripts/session_locator.py "<session-url-or-id>"
```

This returns the resolved session directory, `summary.json`, review info, and artifact paths so the current conversation can continue immediately from that session.

If the resolved session includes `intent_resolution.json` with `status=pending_host_fusion`, do not call an external API from the local companion. Instead, generate the host-fusion prompt from `intent_evidence.json`, use the current host conversation to resolve the intent from that evidence bundle, then persist the structured result with:

```bash
<python-bin> <skill-dir>/scripts/intent_resolution.py prompt --session <session-id>
```

Treat that generated prompt as the primary source of truth for the fusion step. Do not handcraft the JSON from unrelated files first when the evidence bundle exists.

Then persist the structured result with:

```bash
<python-bin> <skill-dir>/scripts/intent_resolution.py write --session <session-id> --input <json-file-or-stdin>
```

Use blocking watch mode on every normal trigger:
- run `<python-bin> <skill-dir>/scripts/watch_next_session.py --after-session <latest-known-session-id>`
- this temporarily suppresses background `auto_run` while waiting for the next finalized session
- it also binds the current workspace as the active project root, so the raw session is grouped under that project instead of `unassigned`
- after the next session arrives, continue in the current conversation using that session's artifacts
- if the user asked for direct code changes, do the edits in the current conversation instead of waiting for the background orchestrator

## Step 1: Start directly

If the user already supplied a session URL or session id, do not start watch mode. Resolve that session first with `scripts/session_locator.py`, then continue at artifact review.

On normal triggers, do not run `scripts/status.py` first. Go straight into watch mode and ask the user to record.

Update transcription preferences only when needed:

```bash
<python-bin> <skill-dir>/scripts/preferences.py set --language zh --model small
```

Override the default target project and fallback orchestrator mode with:

```bash
<python-bin> <skill-dir>/scripts/preferences.py set --project-root <current-workspace> --orchestrator on --orchestrator-mode apply --auto-run off
```

Use blocking watch mode on every normal trigger:

```bash
<python-bin> <skill-dir>/scripts/watch_next_session.py --after-session <latest-known-session-id>
```

This temporarily suppresses background `auto_run` while waiting for the next finalized session and binds the current workspace as the active project root.

## Step 2: Diagnose only on failure

If the user reports that recording cannot start or stop, or if the bridge clearly fails during startup, run:

```bash
<python-bin> <skill-dir>/scripts/status.py
```

Interpret states like this:

- `not_installed`
  The extension is not visible in Chrome profiles yet. Run `<python-bin> <skill-dir>/scripts/setup.py --open` yourself, then tell the user to open `chrome://extensions`, enable Developer mode, click `Load unpacked`, and select `<skill-dir>/chrome-extension`.
- `extension_installed`
  The extension is installed, but the native host is not ready. Run `<python-bin> <skill-dir>/scripts/setup.py --no-open` yourself. Do not repeat install instructions; just tell the user the bridge has been refreshed and they can record again.
- `ready_to_record`
  The local bridge is ready. Continue directly to recording.

Only fall back to asking the user to run terminal commands if the setup script fails and you cannot recover automatically.

Also inspect `dependencies.transcription_ready` only when diagnosis is already happening, or when the user explicitly expects spoken narration to become text. If false, either install the missing dependency yourself when appropriate or explicitly warn that the current recording will not produce `transcript.txt`.

Also inspect `preferences.transcription` only when diagnosis is already happening or when the current transcript quality is poor:
- the default transcription model is `small`
- if `preferred_language` is empty, ask once and save it
- do not proactively offer model switching on every run; only escalate when recognition quality is poor
- if the user says "switch to medium" or if the current model clearly performs poorly, save the stronger model before the next recording and keep using it afterwards

Also inspect `preferences.orchestrator` only when diagnosis is already happening or when the user explicitly asks to change background behavior:
- `project_root` defaults to `auto`, which means the current workspace
- default `mode` should stay `apply`
- default `auto_run` should stay `off`, because the current conversation is expected to continue from watch mode
- only enable background `auto_run` if the user explicitly wants a detached background runner instead of in-conversation continuation

## Step 3: Prepare the bridge

When setup is needed, run:

```bash
<python-bin> <skill-dir>/scripts/setup.py --no-open
```

Only use `--open` for a genuine first-time install or when the user explicitly asks to reopen the Chrome setup flow.

This script checks dependencies, registers the Chrome Native Messaging host, opens `chrome://extensions`, and opens the unpacked extension directory in Finder.

The extension talks to a local native messaging host. That host is short-lived: it starts when Chrome opens a native messaging connection, writes session data, finalizes artifacts, and exits when the session is done.

## Step 4: Run a session

Recording is controlled by shortcuts while Chrome is focused:
- press `Option+S` once to start recording
- wait for the page cue `UI Commander is recording. Start speaking now.`
- reproduce the bug in the real app
- narrate the expected behavior and the actual behavior
- press `Option+E` to stop and wait for the completion cue

Clicking the extension icon should not open a workflow popup anymore. It only serves as an installed indicator and can show a short hint cue on the page with the current shortcuts.

The extension captures:
- interaction events
- pointer trajectories
- periodic keyframe screenshots
- DOM target summaries
- key screenshots
- URL and route changes
- console and runtime exceptions
- network requests, responses, and loading failures
- microphone narration from the local companion, using the current macOS default input device

The native host writes raw session directories under `/tmp/ui-commander/sessions/`, grouped by project when a workspace is known. Long-lived preferences and runtime state stay under `~/.ui-commander/`.

## Step 5: Finalize artifacts

If needed, run finalization manually:

```bash
<python-bin> <skill-dir>/scripts/companion.py finalize --session <session-id>
```

Read the latest session summary from the newest shared session directory:

```text
/tmp/ui-commander/sessions/<project-slug>/<session-id>/summary.json
```

Or locate the newest session with:

```bash
<python-bin> <skill-dir>/scripts/latest_session.py
```

For the user-facing review bundle, run:

```bash
<python-bin> <skill-dir>/scripts/session_review.py
```

The local companion now starts a lightweight localhost session server and opens a live review page automatically after recording finalization, so the user can immediately inspect the trajectory overlay, transcript, and downstream progress without returning to chat first.

For blocking watch mode inside the current host conversation, always wait for the next session with:

```bash
<python-bin> <skill-dir>/scripts/watch_next_session.py --after-session <latest-known-session-id>
```

Use this as the default behavior so the current conversation keeps showing progress and then continues directly into analysis or code changes after the user finishes recording.

If a detached fallback run is explicitly enabled, the local orchestrator writes:
- `agent-request.json`
- `agent-status.json`
- `agent-result.md`
- `agent-review.html`

under the session directory and, when configured, invokes a detached downstream runner automatically. The localhost live review page is the primary user-facing progress view; `review.html` and `agent-review.html` remain as file-based fallbacks, but they are no longer the primary control path for normal triggers.

If `ffmpeg` and `whisper` are installed, finalization will also attempt to transcribe `audio/mic.wav` into `transcript.txt` and `segments.json`. The default transcription model is `small`. The companion uses the user's saved preferred language first, then learned and system language hints, and only falls back to automatic language detection when needed.

## Step 6: Understand the requested fixes

Read:
- `summary.json`
- `interaction_timeline.json`
- `focus_regions.json`
- `referential_mentions.json`
- `intent_evidence.json`
- `intent_resolution.json`
- `focus_regions/`
- `console_logs.jsonl`
- `network_logs.jsonl`
- `transcript.txt`
- `segments.json`
- `screenshots/`

If `summary.json` contains `extension.reload_required=true`, tell the user plainly that Chrome is still using an older unpacked extension build than the current skill files, and ask them to reload the extension in `chrome://extensions` before trusting the next recording.

Use the timeline as the primary source of truth for click or input workflows. Use `focus_regions.json` when the user mostly pointed, hovered, or drew circles instead of clicking. Use `referential_mentions.json` when the transcript contains phrases like "this", "that", "这个", or "这两个"; it links those phrases to nearby pointer hotspots by time. For each focus region, prefer the generated overlay and crop images in `focus_regions/` over raw bbox guessing.

If `intent_resolution.json` is already `resolved`, prefer it as the highest-level intent summary. If it is `pending_host_fusion`, first run `scripts/intent_resolution.py prompt --session <session-id>`, use that evidence-driven prompt to resolve the user's intent in the current conversation, and write the result back before summarizing.

Then summarize your understanding back to the user in a short numbered list before editing code.

Before any code edits, always show the user:
- at least one trajectory overlay image from `review.overlay_images`
- the recognized transcript from `review.transcript`

Do this even if the transcript is poor, so the user can confirm or correct it.

Example:

> 1. Replace the blue CTA button with a green button and stronger contrast.
> 2. Reduce the card title font size in the hero section.
> 3. The repro only fails after the second click because the modal state resets on navigation.

If the recording is ambiguous, stop and clarify before patching.

## Step 7: Apply fixes

Once the requested changes are clear:

1. Search the project for the relevant component or page.
2. Apply the requested frontend changes.
3. Run the narrowest useful verification available.
4. Report the changed files and any remaining ambiguity.

## Operating notes

- Prefer the user's real browser session over a fresh automated profile so cookies and login state stay intact.
- Treat the session directory as the stable contract. Different agents may consume it later.
- If microphone capture is unavailable, the extension can still collect steps and screenshots. Ask the user for a short text summary rather than guessing.
- Keep changes scoped to what was shown in the session.
