# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**reflection** is a standalone Claude plugin (v0.1.0) that tracks agent-performance inconsistencies across sessions. It is fully decoupled from `dev-workflow` — it has no dependency on it and makes no changes to it — so it works in any session, with or without other plugins installed.

## Architecture

### SessionStart hook

`hooks/reflection_session_start.py` runs on every session start and emits a fixed `additionalContext` payload (via `{"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "..."}}`) instructing the agent to watch for five trigger types throughout the session (correction of a claim, "no"/"don't"/"stop doing X", a repeated/rephrased request, pushback on an approach, visible frustration/escalation) and log each occurrence immediately and passively — no task interruption, no permission-asking. Like the notifications plugin's hooks, it degrades silently (exit 0, no output) on any error.

### Log file

`~/.claude/reflection/log.md` — append-only Markdown, one entry per trigger, each with an ISO-8601 timestamp, a one-line context note (skill/project/cwd), the trigger type, and a one-line quote/paraphrase. This is uncommitted runtime state, created on first write — the same convention `dev-workflow` uses for `~/.claude/dev-workflow/state/`.

### `reflect` skill

`skills/reflect/SKILL.md`, invoked via `/reflect`, runs four phases:

1. **Read the log** — read `~/.claude/reflection/log.md`; if missing/empty, note "no logged entries" and continue.
2. **Catch-up scan** — scan the live conversation for uncaptured trigger moments and append them; then locate the most recently modified `.jsonl` transcript under the current project's `~/.claude/projects/` folder (excluding the live session's own file) and scan it too, skipping this part if no other transcript exists.
3. **Synthesize with root-cause attribution** — group entries by context; for each recurring or clearly fixable problem, attribute the root cause to either a named skill's `SKILL.md` (located under `~/.claude/plugins/cache/{marketplace}/{plugin}/{version}/skills/{skill}/`, searched by name across marketplaces/plugins) with the specific instruction quoted, or a named `CLAUDE.md` (user-global or repo-level) with the missing/ignored rule identified. Never a generic observation.
4. **Write the report** — render a standalone, self-contained, light/dark-aware HTML report (no external assets, no network calls) to `~/.claude/reflection/reports/{ISO-timestamp}.html`.

Report output (also uncommitted runtime state): `~/.claude/reflection/reports/`.

The skill never edits any file other than appending catch-up entries to the log (phase 2) and writing its own report (phase 4) — it only ever suggests fixes, never applies them.

## File Layout

```
hooks/
  hooks.json                        # SessionStart hook registration
  reflection_session_start.py       # Emits watch-and-log instructions on every session start
skills/
  reflect/
    SKILL.md                        # /reflect: read -> catch-up scan -> synthesize -> report
.claude-plugin/
  plugin.json                       # Plugin manifest
```

## Working on This Codebase

Content is a hook script plus a Markdown skill definition — there is no compiled code, no build step, and no automated test suite (the hook emits a fixed payload; the skill's behavior is agent-driven at runtime, not deterministic code, so it is verified through manual scenarios rather than unit tests). When changing behavior, bump the version in `.claude-plugin/plugin.json`.

**Do not** add a dependency on or integration with `plugins/dev-workflow` — this plugin is deliberately standalone so it works in any session.
