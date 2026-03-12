# AGENTS.md instructions for /Users/fjh/IT_Workspace/screen-commander

## Skills
A skill is a set of local instructions to follow that is stored in a `SKILL.md` file. Below is the list of skills that can be used. Each entry includes a name, description, and file path so you can open the source for full instructions when using a specific skill.

### Available skills
- dev-browser: Browser automation with persistent page state. Use when users ask to navigate websites, fill forms, take screenshots, extract web data, test web apps, or automate browser workflows. Trigger phrases include "go to [url]", "click on", "fill out the form", "take a screenshot", "scrape", "automate", "test the website", "log into", or any browser interaction request. (file: /Users/fjh/.agents/skills/dev-browser/skills/dev-browser/SKILL.md)
- peekaboo: Capture and automate macOS UI with the Peekaboo CLI. (file: /Users/fjh/.agents/skills/peekaboo/SKILL.md)
- skill-creator: Guide for creating effective skills. This skill should be used when users want to create a new skill (or update an existing skill) that extends Codex's capabilities with specialized knowledge, workflows, or tool integrations. (file: /Users/fjh/.codex/skills/.system/skill-creator/SKILL.md)
- skill-installer: Install Codex skills into $CODEX_HOME/skills from a curated list or a GitHub repo path. Use when a user asks to list installable skills, install a curated skill, or install a skill from another repo (including private repos). (file: /Users/fjh/.codex/skills/.system/skill-installer/SKILL.md)
- screen-commander: Capture a frontend bug reproduction inside the user's existing Chrome session, then turn the session into structured artifacts for any local coding agent to inspect. Use when the user wants to demonstrate a bug by clicking through the real app, narrating what should happen, and handing the resulting session to an agent for analysis or code changes. Trigger phrases include "use screen-commander", "启动 screen-commander", "录一个前端 bug", "复现网页 bug", or any request to record a Chrome bug reproduction and continue from the captured session. (file: /Users/fjh/IT_Workspace/screen-commander/SKILL.md)

### How to use skills
- Discovery: The list above is the skills available in this project (name + description + file path). Skill bodies live on disk at the listed paths.
- Trigger rules: If the user names a skill (with `$SkillName` or plain text) OR the task clearly matches a skill's description shown above, you must use that skill for that turn. Multiple mentions mean use them all. Do not carry skills across turns unless re-mentioned.
- Missing/blocked: If a named skill isn't in the list or the path can't be read, say so briefly and continue with the best fallback.
- How to use a skill (progressive disclosure):
  1. After deciding to use a skill, open its `SKILL.md`. Read only enough to follow the workflow.
  2. When `SKILL.md` references relative paths, resolve them relative to the skill directory listed above first, and only consider other paths if needed.
  3. If `SKILL.md` points to extra folders such as `references/`, load only the specific files needed for the request; don't bulk-load everything.
  4. If `scripts/` exist, prefer running or patching them instead of retyping large code blocks.
  5. If `assets/` or templates exist, reuse them instead of recreating from scratch.
- Coordination and sequencing:
  - If multiple skills apply, choose the minimal set that covers the request and state the order you'll use them.
  - Announce which skill(s) you're using and why (one short line). If you skip an obvious skill, say why.
- Context hygiene:
  - Keep context small: summarize long sections instead of pasting them; only load extra files when needed.
  - Avoid deep reference-chasing: prefer opening only files directly linked from `SKILL.md` unless you're blocked.
  - When variants exist, pick only the relevant reference file(s) and note that choice.
- Safety and fallback: If a skill can't be applied cleanly, state the issue, pick the next-best approach, and continue.
