# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**reflection** is a standalone Claude plugin (v0.4.0) that tracks agent-performance inconsistencies across sessions. It is fully decoupled from `dev-workflow` — it has no dependency on it and makes no changes to it — so it works in any session, with or without other plugins installed.

## Architecture

### SessionStart hook

`hooks/reflection_session_start.py` runs on every session start and emits a fixed `additionalContext` payload (via `{"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "..."}}`) instructing the agent to watch for five trigger types throughout the session (correction of a claim, "no"/"don't"/"stop doing X", a repeated/rephrased request, pushback on an approach, visible frustration/escalation) and log each occurrence immediately and passively — no task interruption, no permission-asking. Like the notifications plugin's hooks, it degrades silently (exit 0, no output) on any error.

### Stop hook (session-end `/reflect` nudge)

`hooks/reflection_stop.py` fires at the end of every turn. It only acts when ALL of these hold: `stop_hook_active` is not set (avoids looping on its own block), the current session hasn't already been nudged (per-session marker at `~/.claude/reflection/state/{session_id}.nudged`), a completion signal is detected (see below), and `~/.claude/reflection/log.md` has at least one entry whose `status` segment is `open` or absent — a fully-`reported` log never nudges.

Completion detection is dual-signal; either signal alone is enough:

1. **Sign-off phrase** — the last user message matches a sign-off heuristic (e.g. "bye", "that's all", "done for now").
2. **PM done-transition** — the session's transcript shows a story/task moved to a done-type workflow state: an `mcp__`-prefixed tool call whose name contains an update-ish verb (`update`/`edit`/`transition`/`move`/`set`) and a story/task-ish noun (`story`/`stories`/`task`/`issue`/`ticket`), plus a done-type `type`/`name`/`state` value (`done`/`closed`/`resolved`/`complete`/`completed`, trimmed, case-insensitive) in any tool result — anywhere in the transcript, in any order. This signal is derived purely from parsing the transcript JSONL; the hook makes no MCP calls. It exists because session sc-1242 ended with a story moved to Done via a plain chat instruction and no sign-off phrase, which the old text-only check missed entirely.

When everything holds, it returns `{"decision": "block", "reason": "..."}` to stop the session from ending and tell the agent to run `/reflect` first — the same "block Stop, inject a reason" mechanism `dev-workflow`'s `compact-injector.sh` uses for `/compact`, but via the hook's own JSON decision output rather than tmux injection. Both signals are inherently imprecise heuristics (a regex over closing phrases; name/result pattern-matching over tool calls) and will occasionally miss a real completion or fire on an unrelated match — the per-session marker caps the cost of a false positive to one nudge.

### Log file

`~/.claude/reflection/log.md` — append-only Markdown, one entry per trigger, each with an ISO-8601 timestamp, a one-line context note (skill/project/cwd), the trigger type, a one-line quote/paraphrase, and a fifth `status` segment: `open` (the default for new entries) or `reported (report: {path}, at: {timestamp})` once a report has covered it. Entries with no status segment (written before status tracking existed) are treated as `open`. This is uncommitted runtime state, created on first write — the same convention `dev-workflow` uses for `~/.claude/dev-workflow/state/`.

### `reflect` skill

`skills/reflect/SKILL.md`, invoked via `/reflect`, runs four phases:

1. **Read the log** — read `~/.claude/reflection/log.md`; if missing/empty, note "no logged entries" and continue. Parse each entry's `status` segment (`open` or `reported (...)`; a missing segment is treated as `open`).
2. **Catch-up scan** — scan the live conversation for uncaptured trigger moments and append them (each ending with `| status: open`); then locate the most recently modified `.jsonl` transcript under the current project's `~/.claude/projects/` folder (excluding the live session's own file) and scan it too, skipping this part if no other transcript exists.
3. **Synthesize with root-cause attribution** — group entries by context. A group whose entries are all `reported` is skipped: instead of re-deriving its root cause, the report gets a short "Already tracked" note naming the earlier report that covered it and, when the group's entries carry a `story:` field, the linked story ID read from that field. For every group with at least one `open` entry, and for each recurring or clearly fixable problem, attribute the root cause to either a named skill's `SKILL.md` (located under `~/.claude/plugins/cache/{marketplace}/{plugin}/{version}/skills/{skill}/`, searched by name across marketplaces/plugins) with the specific instruction quoted, or a named `CLAUDE.md` (user-global or repo-level) with the missing/ignored rule identified. Never a generic observation.
4. **Write the report** — render a standalone, self-contained, light/dark-aware HTML report (no external assets, no network calls) to `~/.claude/reflection/reports/{ISO-timestamp}.html`. The report is written locally only — never published, uploaded, or shared via the Artifact tool or any other mechanism. Then update the log in place, split by root-cause attribution: entries in groups with no nameable root cause are set to `reported (report: {path}, at: {timestamp})` immediately; entries in root-caused groups are NOT marked `reported` until a mandatory per-finding remediation question is answered — file a follow-on story (status gains `| story: sc-XXXX`) or explicitly decline tracking (status gains `| declined: {ISO-8601 timestamp}`) — with the status and the trailing field written in the same log edit. A report file existing is never, by itself, grounds to mark a root-caused finding `reported`. Already-tracked groups are left untouched.

Report output (also uncommitted runtime state): `~/.claude/reflection/reports/`.

The skill never edits any file other than appending catch-up entries to the log (phase 2), writing its own report (phase 4), and updating existing log entries' `status` segments in place (phase 4) — it only ever suggests fixes, never applies them.

## File Layout

```
hooks/
  hooks.json                        # SessionStart + Stop hook registration
  reflection_session_start.py       # Emits watch-and-log instructions on every session start
  reflection_stop.py                # Nudges /reflect on a completion signal (sign-off phrase OR PM done-transition), if open log entries exist
skills/
  reflect/
    SKILL.md                        # /reflect: read -> catch-up scan -> synthesize -> report
tests/
  conftest.py                       # Shared pytest fixtures (transcript/log builders)
  test_reflection_stop.py           # Unit tests for the Stop hook's gating logic
  fixtures/                         # Transcript JSONL fixtures for the done-transition tests
.claude-plugin/
  plugin.json                       # Plugin manifest
```

## Working on This Codebase

Content is hook scripts plus a Markdown skill definition — there is no compiled code and no build step. The Stop hook has real branching logic (dual-signal detection, open-entries gating) covered by a pytest suite: run `python3 -m pytest plugins/reflection/tests/` from the repo root. The reflect skill's behavior is agent-driven at runtime, not deterministic code, so it remains verified through manual scenarios rather than unit tests. When changing behavior, bump the version in `.claude-plugin/plugin.json`.

**Do not** add a dependency on or integration with `plugins/dev-workflow` — this plugin is deliberately standalone so it works in any session.
