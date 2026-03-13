<div align="center">

# 🎬 UI Commander

**把前端 bug「演」给 AI 看，而不是「写」给它听。**

一个 AI coding agent 的 skill —— 在你的真实 Chrome 中录制 bug 复现，<br/>
边操作边语音讲解，自动生成结构化会话工件，agent 接过来继续分析甚至直接修复。

[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Chrome Extension](https://img.shields.io/badge/Chrome-MV3_Extension-4285F4?logo=googlechrome&logoColor=white)](https://developer.chrome.com/docs/extensions/mv3/)
[![Platform](https://img.shields.io/badge/Platform-macOS-000000?logo=apple&logoColor=white)](https://www.apple.com/macos/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

**[English](README.md)** | **中文**

</div>

---

## 这是什么？

UI Commander 是一个面向 AI coding agent 的 **skill（技能插件）**。

有些前端 bug，用文字很难描述清楚——它可能藏在一次悬停的交互里，或者只在某段特定操作流程中才会触发。UI Commander 让你跳过「打字描述问题」这一步，直接在真实浏览器中操作复现，同时用语音讲解期望行为和实际表现。录制结束后，它会自动生成一份结构化的会话工件，当前对话中的 agent 可以直接读取、分析，甚至在你的代码仓库里完成修复。

> **它是「真实操作 → 结构化 bug 上下文 → agent 自动修复」这条链路的桥梁。**

### 核心能力

| 能力 | 说明 |
|------|------|
| 🖱️ **交互捕获** | 记录真实页面上的点击、悬停、滚动和指针轨迹 |
| 🎤 **语音转写** | 麦克风语音自动通过 Whisper 转成文本 |
| 📸 **智能截图** | 关键交互点截图 + 900ms 间隔自动关键帧 |
| 🔍 **焦点区域** | 自动识别指针聚集区域，生成裁切图和叠加轨迹图 |
| 🌐 **网络与日志** | 捕获 console 输出、运行时异常、网络请求与响应 |
| 🧠 **意图融合** | 将语音、指针和截图交叉对齐，理解「这里」「那个按钮」等指代 |
| 🔗 **Agent 衔接** | 输出标准化工件，agent 在当前对话中直接继续分析或修改代码 |

---

## 安装

将此仓库克隆到你的 skill 目录后，首次使用时 agent 会自动完成环境检查和 Native Host 注册。你唯一需要手动做的是**在 Chrome 中加载扩展**：

1. 打开 `chrome://extensions`
2. 开启 **开发者模式**
3. 点击 **加载已解压的扩展程序**，选择本项目中的 `chrome-extension/` 目录

### 运行环境

- macOS（当前版本针对 macOS 优化）
- Python 3.10+
- Google Chrome
- ffmpeg（用于音频处理，`brew install ffmpeg`）
- openai-whisper（语音转写，`pip install openai-whisper`）

> 如果缺少依赖，agent 在首次执行时会检测并给出提示。

### 语音转写（Whisper）

语音转写使用 [openai-whisper](https://github.com/openai/whisper)，默认模型为 **`small`**，在速度和准确率之间取得平衡。

**首次使用时需要设置常用录制语言**，在对话中告诉 agent 即可（例如「把录制语言设为中文」）。设置后会持久保存，后续无需重复设置。

**切换模型大小：** 如果觉得转写不够准确，可以在对话中要求 agent 切换到更大的模型：

| 模型 | 速度 | 准确率 | 适用场景 |
|------|------|--------|----------|
| `small`（默认） | ⚡ 快 | 日常够用 | 大多数录制场景 |
| `medium` | 🔄 中等 | 更高 | 混合语言或口音较重时 |
| `large` | 🐢 较慢 | 最高 | 需要精确转写时 |

例如：「whisper 模型切到 medium」或「用 large 模型转写」。切换后的模型会持久保存，后续录制都会沿用。

> 首次下载模型时会耗时较久

**切换录制语言：** 随时可以在对话中切换，例如：「录制语言换成英文」「转写语言切到日语」。

---

## 两种使用模式

### 模式一：Agent中启动

`启动 ui commander，我来录一个bug`唤醒 skill 后：

1. Agent 自动进入等待模式，准备接收新录制
2. 你会看到一条粗体提示：**现在请切到 Chrome，按 Option+S 开始，按 Option+E 结束。**
3. 切到 Chrome，聚焦目标页面
4. 按 **`Option+S`** 开始录制（页面会出现录制提示）
5. 在真实页面复现 bug，同时**语音讲解**期望行为和实际问题
6. 按 **`Option+E`** 结束录制
7. Agent 自动读取工件，在当前对话中继续分析和修复

> 你不需要先把问题「写对」，只需要把问题「做出来」。

### 模式二：浏览器中直接录制 (推荐)

安装好浏览器插件后，直接点击插件，按快捷键录制，结束后会弹出 review 的页面，在页面点击复制按钮贴给 agent 即可：

```
使用 ui commander 分析 http://127.0.0.1:47321/sessions/20260313-143022-a1b2c3/live
```

---

## 工作流

```
你在 Chrome 中操作复现          UI Commander 在后台捕获
┌─────────────────────┐        ┌──────────────────────────┐
│  打开真实页面        │        │  交互事件 + 指针轨迹      │
│  Option+S 开始录制   │───────▶│  周期性关键帧截图         │
│  边操作边语音讲解    │        │  麦克风录音 → Whisper 转写 │
│  Option+E 结束录制   │        │  Console / Network 日志   │
└─────────────────────┘        └──────────┬───────────────┘
                                          │
                                          ▼
                               ┌──────────────────────────┐
                               │  结构化 Session 工件      │
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
                               │  Coding Agent 接力        │
                               │  分析问题 → 定位代码      │
                               │  → 直接修复或给出方案     │
                               └──────────────────────────┘
```

---

## 如何唤醒

UI Commander 作为 skill 安装后，你只需要在和 AI agent 的对话中**用自然语言提及它**，skill 就会自动被触发。不需要手动执行任何命令——所有环境准备、录制等待和工件解析都由 agent 自动完成。

### 🗣️ 直接点名

| 示例 |
|------|
| `使用 ui commander` |
| `用 ui-commander` |
| `启动 ui commander` |
| `use ui-commander` |
| `使用 ui commander 复现一个前端 bug` |
| `启动 ui commander，我来录一下` |

### 💬 描述意图（自动触发）

当你的描述明确涉及「在浏览器中演示 / 录制前端问题」时，skill 也会被自动唤醒：

| 示例 |
|------|
| `录一个前端 bug` |
| `复现网页 bug` |
| `我这里有个前端问题，想直接演示` |
| `我想把 bug 演给你看` |
| `帮我看一下这个页面的问题` |

### 🔗 传入已有 Session

如果你手上已经有一条录制好的 session，直接贴 URL 或 session id，agent 会跳过录制，从已有会话继续：

| 示例 | 行为 |
|------|------|
| `使用 ui commander 分析 http://127.0.0.1:47321/sessions/<id>/live` | 从已有 session 分析问题 |
| `使用 ui commander 分析并直接修复 http://127.0.0.1:47321/sessions/<id>/live` | 从已有 session 直接修复代码 |
| 直接贴一个 session id | Agent 自动定位对应会话 |

> 包含「直接修复」字样时，agent 会直接进入代码修改模式而非仅做分析。

---

## 录制技巧

录制时不需要像写文档一样正式，**自然地说就好**：

| ✅ 推荐做法 | ❌ 不需要做的 |
|:-----------|:------------|
| 用鼠标指向你在说的区域 | 写一份详细的 bug 报告 |
| 说「我点了这个按钮，预期弹出弹窗」 | 记住精确的 CSS 选择器 |
| 出现异常时说「这里不对」 | 提前整理复现步骤 |
| 有相似元素时用鼠标圈给 agent 看 | 背诵组件名和文件路径 |

> UI Commander 会自动将你的鼠标轨迹与语音中的「这个」「那里」等指代词对齐，生成结构化的上下文线索。

---

## 快捷键

| 操作 | macOS | Windows / Linux |
|------|-------|-----------------|
| 开始录制 | `Option + S` | `Alt + S` |
| 结束录制 | `Option + E` | `Alt + E` |

> 需要在 Chrome 浏览器聚焦时使用。录制开始后页面会显示提示，此时开始语音讲解。

---

## Session 工件

每次录制会自动生成一组结构化工件，供 agent 解析和推理：

<details>
<summary><b>📂 完整工件清单</b></summary>

| 文件 | 说明 |
|------|------|
| `summary.json` | 会话摘要，agent 的首要入口 |
| `session.json` | 会话元数据和生命周期状态 |
| `events.jsonl` | 按时间戳排列的原始浏览器事件 |
| `interaction_timeline.json` | 精简后的高价值交互步骤 |
| `focus_regions.json` | 指针聚集区域、悬停和圈选手势 |
| `focus_regions/` | 焦点区域的叠加轨迹图和裁切截图 |
| `screenshots/` | 关键交互截图 |
| `screenshots/keyframes/` | 900ms 间隔的周期性关键帧 |
| `audio/mic.wav` | 麦克风原始录音 |
| `transcript.txt` | Whisper 语音转写文本 |
| `segments.json` | 带时间线对齐和焦点区域关联的转写片段 |
| `referential_mentions.json` | 「这个」「那里」等指代词与指针热点的映射 |
| `intent_evidence.json` | 紧凑的意图证据包 |
| `intent_resolution.json` | 融合后的用户意图和目标区域 |
| `console_logs.jsonl` | Console 输出和运行时异常 |
| `network_logs.jsonl` | 网络请求、响应和加载失败 |
| `review.html` | 本地 review 页面（录制后自动打开） |

</details>

---

## 架构

```
┌─────────────────────────────────────────────────┐
│                   Chrome 浏览器                  │
│  ┌─────────────────────────────────────────────┐ │
│  │         UI Commander 扩展 (MV3)             │ │
│  │  background.js ← content.js ← offscreen.js │ │
│  └──────────────────┬──────────────────────────┘ │
└─────────────────────┼───────────────────────────┘
                      │ Native Messaging
                      ▼
┌─────────────────────────────────────────────────┐
│           本地 Native Host 伴侣进程              │
│  companion.py                                    │
│  ├─ 接收浏览器事件流                              │
│  ├─ 音频录制 (ffmpeg + 系统麦克风)                │
│  ├─ 语音转写 (openai-whisper)                    │
│  ├─ 焦点区域分析 + 截图处理                       │
│  ├─ 意图融合                                     │
│  └─ Session 工件输出                              │
└──────────────────┬──────────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────────┐
│        结构化 Session 工件                        │
└──────────────────┬──────────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────────┐
│       AI Coding Agent (Codex / Copilot)          │
│  读取工件 → 分析问题 → 定位代码 → 修复           │
└─────────────────────────────────────────────────┘
```

- **Chrome 扩展** — Manifest V3，通过 Debugger API 捕获交互、截图、Console 和网络事件
- **Native Messaging Host** — Chrome 与本地 Python 进程的通信桥梁
- **伴侣进程** — 核心引擎：音频录制、Whisper 转写、截图处理、焦点分析、工件生成
- **Session Server** — 录制完成后自动启动的本地 review 页面服务

---

## 多语言支持

界面提示和语音转写均支持多语言：

| 语言 | 界面提示 | 语音转写 |
|------|---------|---------|
| 🇨🇳 中文 | ✅ | ✅ |
| 🇺🇸 English | ✅ | ✅ |
| 🇯🇵 日本語 | ✅ | ✅ |
| 🇰🇷 한국어 | ✅ | ✅ |

首次使用需要设置录制语言，之后会持久保存。随时可在对话中切换语言，例如：

- 「把录制语言设为中文」
- 「转写语言切到英文」
- 「录制语言换成日语」

---

## 许可证

[MIT](LICENSE)
