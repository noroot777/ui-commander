<div align="center">

# 🎬 UI Commander

**Show your frontend bugs to AI — don't just describe them.**

A skill for AI coding agents — record bug reproductions in your real Chrome browser,<br/>
narrate what's expected vs. what's broken, and let the agent analyze or fix it directly.

[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Chrome Extension](https://img.shields.io/badge/Chrome-MV3_Extension-4285F4?logo=googlechrome&logoColor=white)](https://developer.chrome.com/docs/extensions/mv3/)
[![Platform](https://img.shields.io/badge/Platform-macOS-000000?logo=apple&logoColor=white)](https://www.apple.com/macos/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

**English** | **[中文](README.zh-CN.md)**

</div>

---

## What Is This?

UI Commander is a **skill (plugin) for AI coding agents**.

Some frontend bugs are nearly impossible to describe in text — they hide in hover interactions, appear only during specific operation sequences, or require seeing the exact visual context to understand. UI Commander lets you skip the "type out the problem" step. Instead, reproduce the bug in your real browser while narrating what should happen vs. what actually happens. After recording, it automatically generates structured session artifacts that the agent can read, analyze, and even use to fix your code — all within the current conversation.

> **It bridges the gap from "real browser interaction → structured bug context → agent-driven fix."**

### Core Capabilities

| Capability | Description |
|-----------|-------------|
| 🖱️ **Interaction Capture** | Records clicks, hovers, scrolling, and pointer trajectories on the real page |
| 🎤 **Voice Transcription** | Microphone audio automatically transcribed via Whisper |
| 📸 **Smart Screenshots** | Key interaction screenshots + automatic keyframes every 900ms |
| 🔍 **Focus Regions** | Auto-detects pointer hotspots, generates cropped and trajectory-overlay images |
| 🌐 **Network & Logs** | Captures console output, runtime exceptions, network requests & responses |
| 🧠 **Intent Fusion** | Cross-aligns voice, pointer, and screenshots to understand references like "this" and "that button" |
| 🔗 **Agent Handoff** | Outputs standardized artifacts so the agent continues analysis or code changes in-thread |

---

## Installation

After cloning this repo into your skill directory, the agent will automatically handle environment checks and Native Host registration on first use. The only manual step is **loading the Chrome extension**:

1. Open `chrome://extensions`
2. Enable **Developer mode**
3. Click **Load unpacked** and select the `chrome-extension/` directory in this project

### Requirements

- macOS (current version optimized for macOS)
- Python 3.10+
- Google Chrome
- ffmpeg (audio processing, `brew install ffmpeg`)
- openai-whisper (voice transcription, `pip install openai-whisper`)

> If any dependency is missing, the agent will detect and prompt on first run.

### Voice Transcription (Whisper)

Voice transcription uses [openai-whisper](https://github.com/openai/whisper). The default model is **`small`**, balancing speed and accuracy.

**Set your recording language on first use** — just tell the agent in conversation (e.g., "set recording language to Chinese"). The setting persists across sessions.

**Switch model size:** If transcription accuracy isn't sufficient, ask the agent to switch to a larger model:

| Model | Speed | Accuracy | Use Case |
|-------|-------|----------|----------|
| `small` (default) | ⚡ Fast | Good enough | Most recording scenarios |
| `medium` | 🔄 Moderate | Higher | Mixed languages or heavy accents |
| `large` | 🐢 Slower | Highest | When precise transcription is needed |

For example: "switch whisper to medium" or "use the large model for transcription". The selected model persists for future recordings.

> First-time model downloads may take a while.

**Switch recording language:** Change anytime in conversation, e.g., "switch recording language to English" or "change transcription language to Japanese".

---

## Two Usage Modes

### Mode 1: Record Directly in Browser (Recommended)

With the extension installed, simply click the extension icon or use the keyboard shortcut to record. After recording, a review page opens automatically — click the copy button on that page and paste it to the agent:

```
use ui commander to analyze http://127.0.0.1:47321/sessions/20260313-143022-a1b2c3/live
```

### Mode 2: Start from Agent

Trigger the skill in conversation, e.g. `use ui commander, I want to record a bug`:

1. Agent enters watch mode, waiting for a new recording
2. You'll see a bold prompt: **Switch to Chrome now. Press Option+S to start, Option+E to stop.**
3. Switch to Chrome and focus the target page
4. Press **`Option+S`** to start recording (an on-page cue will appear)
5. Reproduce the bug on the real page while **narrating** expected vs. actual behavior
6. Press **`Option+E`** to stop recording
7. Agent automatically reads the session artifacts and continues analysis or fixes in-thread

> You don't need to "write the problem correctly" — just "make it happen."

---

## Workflow

```
You reproduce in Chrome              UI Commander captures in background
┌─────────────────────┐        ┌──────────────────────────┐
│  Open the real page  │        │  Interaction events       │
│  Option+S to start   │───────▶│  + pointer trajectories   │
│  Narrate as you go   │        │  Periodic keyframe shots  │
│  Option+E to stop    │        │  Mic → Whisper transcript │
└─────────────────────┘        │  Console / Network logs   │
                               └──────────┬───────────────┘
                                          │
                                          ▼
                               ┌──────────────────────────┐
                               │  Structured Session       │
                               │  ├─ summary.json          │
                               │  ├─ interaction_timeline  │
                               │  ├─ focus_regions         │
                               │  ├─ transcript.txt        │
                               │  ├─ screenshots/          │
                               │  └─ intent_resolution     │
                               └──────────┬───────────────┘
                                          │
                                          ▼
                               ┌──────────────────────────┐
                               │  Coding Agent continues   │
                               │  Analyze → Locate code    │
                               │  → Fix or suggest changes │
                               └──────────────────────────┘
```

---

## How to Trigger

Once installed as a skill, just **mention it in natural language** in your conversation with the AI agent. No manual commands needed — the agent handles environment setup, recording watch, and artifact parsing automatically.

### 🗣️ Name It Directly

| Example |
|---------|
| `use ui commander` |
| `start ui-commander` |
| `use ui commander to record a frontend bug` |
| `启动 ui commander` |
| `使用 ui commander` |

### 💬 Describe Your Intent (Auto-trigger)

When your description clearly involves "demonstrating / recording a frontend issue in the browser", the skill activates automatically:

| Example |
|---------|
| `I have a frontend bug, let me show you` |
| `I want to demonstrate this bug` |
| `record a frontend bug` |
| `let me reproduce this web issue` |
| `录一个前端 bug` |

### 🔗 Pass an Existing Session

If you already have a recorded session, paste the URL or session id — the agent skips recording and continues from the existing session:

| Example | Behavior |
|---------|----------|
| `use ui commander to analyze http://127.0.0.1:47321/sessions/<id>/live` | Analyze from existing session |
| `use ui commander to analyze and fix http://127.0.0.1:47321/sessions/<id>/live` | Directly fix code from existing session |
| Paste a raw session id | Agent auto-locates the matching session |

> When "fix" is included, the agent enters code modification mode rather than analysis-only.

---

## Recording Tips

You don't need to sound like documentation — **just speak naturally**:

| ✅ Do | ❌ Don't Need To |
|:------|:-----------------|
| Point your mouse at the area you're describing | Write a detailed bug report |
| Say "I clicked this button, expected a modal to appear" | Memorize CSS selectors |
| Say "this is wrong" when something unexpected happens | Prepare reproduction steps in advance |
| Use the mouse to circle similar elements for the agent | Recite component names or file paths |

> UI Commander automatically aligns your pointer trajectory with deictic references like "this" and "here" in your narration, producing structured context.

---

## Keyboard Shortcuts

| Action | macOS | Windows / Linux |
|--------|-------|-----------------|
| Start recording | `Option + S` | `Alt + S` |
| Stop recording | `Option + E` | `Alt + E` |

> Must be used while Chrome is focused. An on-page cue appears when recording starts — begin narrating then.

---

## Session Artifacts

Each recording automatically produces a set of structured artifacts for agent parsing:

<details>
<summary><b>📂 Full Artifact List</b></summary>

| File | Description |
|------|-------------|
| `summary.json` | Session summary — agent's primary entry point |
| `session.json` | Session metadata and lifecycle state |
| `events.jsonl` | Raw browser events in timestamp order |
| `interaction_timeline.json` | Reduced list of high-value interaction steps |
| `focus_regions.json` | Pointer hotspots, hovers, and circle-like gestures |
| `focus_regions/` | Trajectory overlay and cropped region images |
| `screenshots/` | Key interaction screenshots |
| `screenshots/keyframes/` | Periodic keyframes at 900ms intervals |
| `audio/mic.wav` | Raw microphone recording |
| `transcript.txt` | Whisper voice transcription |
| `segments.json` | Transcript segments with timeline alignment and focus region associations |
| `referential_mentions.json` | Maps deictic words ("this", "here") to nearby pointer hotspots |
| `intent_evidence.json` | Compact evidence bundle for intent fusion |
| `intent_resolution.json` | Fused user intent, ambiguities, and target regions |
| `console_logs.jsonl` | Console output and runtime exceptions |
| `network_logs.jsonl` | Network requests, responses, and loading failures |
| `review.html` | Local review page (auto-opens after recording) |

</details>

---

## Architecture

```
┌─────────────────────────────────────────────────┐
│                  Chrome Browser                  │
│  ┌─────────────────────────────────────────────┐ │
│  │       UI Commander Extension (MV3)          │ │
│  │  background.js ← content.js ← offscreen.js │ │
│  └──────────────────┬──────────────────────────┘ │
└─────────────────────┼───────────────────────────┘
                      │ Native Messaging
                      ▼
┌─────────────────────────────────────────────────┐
│         Local Native Host Companion              │
│  companion.py                                    │
│  ├─ Receives browser event stream                │
│  ├─ Audio recording (ffmpeg + system mic)        │
│  ├─ Voice transcription (openai-whisper)         │
│  ├─ Focus region analysis + screenshot processing│
│  ├─ Intent fusion                                │
│  └─ Session artifact output                      │
└──────────────────┬──────────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────────┐
│        Structured Session Artifacts              │
└──────────────────┬──────────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────────┐
│ Current Agent Host (Codex / Claude / OpenCode)  │
│  Read artifacts → Analyze → Locate code → Fix   │
└─────────────────────────────────────────────────┘
```

- **Chrome Extension** — Manifest V3, captures interactions, screenshots, console, and network events via the Debugger API
- **Native Messaging Host** — Communication bridge between Chrome and the local Python process
- **Companion Process** — Core engine: audio recording, Whisper transcription, screenshot processing, focus analysis, artifact generation
- **Session Server** — Local HTTP service that auto-starts after recording, serving the live review page

---

## Multi-language Support

Both UI prompts and voice transcription support multiple languages:

| Language | UI Prompts | Voice Transcription |
|----------|-----------|---------------------|
| 🇨🇳 中文 | ✅ | ✅ |
| 🇺🇸 English | ✅ | ✅ |
| 🇯🇵 日本語 | ✅ | ✅ |
| 🇰🇷 한국어 | ✅ | ✅ |

Set your recording language on first use — it persists afterwards. Switch anytime in conversation:

- "set recording language to Chinese"
- "switch transcription language to English"
- "change recording language to Japanese"

---

## License

[MIT](LICENSE)
