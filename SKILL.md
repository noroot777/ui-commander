name: screen-commander
description: Capture a frontend bug reproduction inside the user's existing Chrome session, then turn the session into structured artifacts for any local coding agent to inspect. Use this skill when the user wants to demonstrate a bug by clicking through the real app, narrating what should happen, and handing the resulting session to an agent for analysis or code changes.
---

# Screen Commander

Use this skill when the user wants to show a frontend bug in their normal Chrome session instead of describing it in text.

The skill has one job: convert a narrated browser reproduction into structured session artifacts.

This skill is stateful. On every trigger, check local readiness first and adapt your response. Do not start by telling the user to run commands. Prefer to run local helper scripts yourself and only ask the user for Chrome UI actions.

## Workflow

1. Run `/opt/homebrew/opt/python@3.11/libexec/bin/python <skill-dir>/scripts/status.py`.
2. If state is `not_installed`, run local setup yourself and guide the user to load the unpacked extension in Chrome.
3. If state is `extension_installed`, run local setup yourself so the native host is ready, then tell the user the bridge is ready.
4. If state is `ready_to_record`, inspect dependency status and saved transcription preferences.
5. Default the target project to the current workspace. Only override it when the user explicitly wants to send the session to a different repo.
6. If no preferred narration language has been saved yet, ask the user what language they usually narrate in and persist it before recording.
7. Do not ask about transcription models by default. Only change models when the current transcript quality is poor or the user explicitly asks. When the user chooses a stronger model, persist that model so future sessions keep using it until the user changes it again.
8. Enter blocking watch mode before the user records. This is the default and only primary interaction mode for this skill.
9. Tell the user to focus the target Chrome tab, press `Option+S` to start recording, reproduce the bug, then press `Option+E` to stop.
10. Wait for the next finalized session in the current thread, then continue from those artifacts in the same thread.
11. Use the current thread to analyze and, when appropriate, apply code changes. Do not rely on a separate background Codex task as the primary path.

Use blocking watch mode on every normal trigger:
- run `/opt/homebrew/opt/python@3.11/libexec/bin/python <skill-dir>/scripts/watch_next_session.py --after-session <latest-known-session-id>`
- this temporarily suppresses background `auto_run` while waiting for the next finalized session
- after the next session arrives, continue in the current thread using that session's artifacts
- if the user asked for direct code changes, do the edits in the current thread instead of waiting for the background orchestrator

## Step 1: Check readiness

Run:

```bash
/opt/homebrew/opt/python@3.11/libexec/bin/python <skill-dir>/scripts/status.py
```

Update transcription preferences with:

```bash
/opt/homebrew/opt/python@3.11/libexec/bin/python <skill-dir>/scripts/preferences.py set --language zh --model small --vad on
```

Override the default target project and fallback orchestrator mode with:

```bash
/opt/homebrew/opt/python@3.11/libexec/bin/python <skill-dir>/scripts/preferences.py set --project-root <current-workspace> --orchestrator on --orchestrator-mode apply --auto-run off
```

Interpret states like this:

- `not_installed`
  The extension is not visible in Chrome profiles yet. Run `/opt/homebrew/opt/python@3.11/libexec/bin/python <skill-dir>/scripts/setup.py` yourself, then tell the user to open `chrome://extensions`, enable Developer mode, click `Load unpacked`, and select `<skill-dir>/chrome-extension`.
- `extension_installed`
  The extension is installed, but the native host is not ready. Run `/opt/homebrew/opt/python@3.11/libexec/bin/python <skill-dir>/scripts/setup.py` yourself. Then tell the user to try the extension again.
- `ready_to_record`
  The local bridge is ready. Continue directly to recording.

Only fall back to asking the user to run terminal commands if the setup script fails and you cannot recover automatically.

Also inspect `dependencies.transcription_ready`. If false and the user expects spoken narration to become text, either install the missing dependency yourself when appropriate or explicitly warn that the current recording will not produce `transcript.txt`.

Also inspect `preferences.transcription`:
- the default transcription model is `small`
- if `preferred_language` is empty, ask once and save it
- do not proactively offer model switching on every run; only escalate when recognition quality is poor
- if the user says "switch to medium" or if the current model clearly performs poorly, save the stronger model before the next recording and keep using it afterwards
- `vad_enabled` controls the built-in silence trimming step before Whisper runs

Also inspect `preferences.orchestrator`:
- `project_root` defaults to `auto`, which means the current workspace
- default `mode` should stay `apply`
- default `auto_run` should stay `off`, because the current thread is expected to continue from watch mode
- only enable background `auto_run` if the user explicitly wants a detached background Codex CLI task instead of in-thread continuation

## Step 2: Prepare the bridge

When setup is needed, run:

```bash
/opt/homebrew/opt/python@3.11/libexec/bin/python <skill-dir>/scripts/setup.py
```

This script checks dependencies, registers the Chrome Native Messaging host, opens `chrome://extensions`, and opens the unpacked extension directory in Finder.

The extension talks to the local native host `dev.fjh.screen_commander`. The host is short-lived: it starts when Chrome opens a native messaging connection, writes session data, finalizes artifacts, and exits when the session is done.

## Step 3: Run a session

Recording is controlled by shortcuts while Chrome is focused:
- press `Option+S` once to start recording
- wait for the page cue `Screen Commander is recording. Start speaking now.`
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

The native host writes a session directory under `.screen-commander/sessions/`.

## Step 4: Finalize artifacts

If needed, run finalization manually:

```bash
/opt/homebrew/opt/python@3.11/libexec/bin/python <skill-dir>/scripts/companion.py finalize --session <session-id>
```

Read the latest session summary from:

```text
.screen-commander/sessions/<session-id>/summary.json
```

Or locate the newest session with:

```bash
/opt/homebrew/opt/python@3.11/libexec/bin/python <skill-dir>/scripts/latest_session.py
```

For the user-facing review bundle, run:

```bash
/opt/homebrew/opt/python@3.11/libexec/bin/python <skill-dir>/scripts/session_review.py
```

The local companion now starts a lightweight localhost session server and opens a live review page automatically after recording finalization, so the user can immediately inspect the trajectory overlay, transcript, and downstream progress without returning to chat first.

For blocking watch mode inside the current IDE thread, always wait for the next session with:

```bash
/opt/homebrew/opt/python@3.11/libexec/bin/python <skill-dir>/scripts/watch_next_session.py --after-session <latest-known-session-id>
```

Use this as the default behavior so the current thread keeps showing subtasks and then continues directly into analysis or code changes after the user finishes recording.

If a detached fallback run is explicitly enabled, the local orchestrator writes:
- `agent-request.json`
- `agent-status.json`
- `agent-result.md`
- `agent-review.html`

under the session directory and, when configured, invokes Codex CLI automatically. The localhost live review page is the primary user-facing progress view; `review.html` and `agent-review.html` remain as file-based fallbacks, but they are no longer the primary control path for normal triggers.

If `ffmpeg` and `whisper` are installed, finalization will also attempt to transcribe `audio/mic.wav` into `transcript.txt` and `segments.json`. The default transcription model is `small`. The companion uses the user's saved preferred language first, then learned and system language hints, and only falls back to automatic language detection when needed. It also applies a VAD-style silence trimming step before transcription unless the user has turned that off.

## Step 5: Understand the requested fixes

Read:
- `summary.json`
- `interaction_timeline.json`
- `focus_regions.json`
- `focus_regions/`
- `console_logs.jsonl`
- `network_logs.jsonl`
- `transcript.txt`
- `segments.json`
- `screenshots/`

Use the timeline as the primary source of truth for click or input workflows. Use `focus_regions.json` when the user mostly pointed, hovered, or drew circles instead of clicking. For each focus region, prefer the generated overlay and crop images in `focus_regions/` over raw bbox guessing.

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

## Step 6: Apply fixes

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
