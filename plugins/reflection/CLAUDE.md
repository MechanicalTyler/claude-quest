# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**reflection** is a standalone Claude plugin that tracks agent-performance inconsistencies across sessions. It has no hard dependency on `dev-workflow` and makes no changes to it, so it works in any session, with or without other plugins installed. The one exception is a runtime-detected, optional soft integration in the `reflect` skill's remediation offer: if an installed skill matches a story-creation naming pattern (e.g. `*:create-story`), reflect may offer to invoke it directly to self-file a bundled ticket — falling back to its standalone "file it yourself" flow whenever no such skill is detected.

## Architecture

### SessionStart hook

`hooks/reflection_session_start.py` runs on every session start and emits an `additionalContext` payload (via `{"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "..."}}`) instructing the agent to watch for several trigger types throughout the session (correction of a claim, "no"/"don't"/"stop doing X", a repeated/rephrased request, pushback on an approach, visible frustration/escalation) and log each occurrence immediately and passively — no task interruption, no permission-asking. These base instructions are always present, regardless of log state. Like the notifications plugin's hooks, it degrades silently (exit 0, no output) on any error.

The hook also checks `has_open_entries(LOG_PATH)` — true when `~/.claude/reflection/log.md` has at least one entry whose `status` segment is `open` or absent (entries written before status tracking existed). When true, a `/reflect` nudge is appended to the base instructions, telling the agent to run `/reflect` now to synthesize the unreviewed entries into a report. A fully-`reported` log never nudges. SessionStart fires on `startup`, `resume`, `clear`, `compact`, and `fork` — not once per session — so the nudge is gated by a per-session-id marker file at `~/.claude/reflection/state/{session_id}.nudged` (mirroring the old Stop hook's marker, keyed by the same session ID, which survives compaction), ensuring it still fires at most once per actual session even though the hook itself runs several times. This replaces the old Stop-hook approach, which guessed at session-ending moments via a sign-off-phrase regex and a PM done-transition scan of the transcript; both signals were inherently imprecise and could miss a real completion or fire mid-session. Moving the trigger to session start removes that guessing while keeping the same per-session dedup guarantee.

### Log file

`~/.claude/reflection/log.md` — append-only Markdown, one entry per trigger, each with an ISO-8601 timestamp, a one-line context note (skill/project/cwd), the trigger type, a one-line quote/paraphrase, and a fifth `status` segment: `open` (the default for new entries) or `reported (report: {path}, at: {timestamp})` once a report has covered it. Entries with no status segment (written before status tracking existed) are treated as `open`. This is uncommitted runtime state, created on first write — the same convention `dev-workflow` uses for `~/.claude/dev-workflow/state/`.

### `reflect` skill

`skills/reflect/SKILL.md`, invoked via `/reflect`, runs the following phases:

1. **Read the log** — read `~/.claude/reflection/log.md`; if missing/empty, note "no logged entries" and continue. Parse each entry's `status` segment (`open` or `reported (...)`; a missing segment is treated as `open`).
2. **Catch-up scan** — scan the live conversation for uncaptured trigger moments and append them (each ending with `| status: open`); then locate the most recently modified `.jsonl` transcript under the current project's `~/.claude/projects/` folder (excluding the live session's own file) and scan it too, skipping this part if no other transcript exists.
3. **Synthesize with root-cause attribution** — group entries by context. A group whose entries are all `reported` is skipped: instead of re-deriving its root cause, the report gets a short "Already tracked" note naming the earlier report that covered it and, when the group's entries carry a `story:` field, the linked story ID read from that field. For every group with at least one `open` entry, and for each recurring or clearly fixable problem, attribute the root cause to either a named skill's `SKILL.md` (located under `~/.claude/plugins/cache/{marketplace}/{plugin}/{version}/skills/{skill}/`, searched by name across marketplaces/plugins) with the specific instruction quoted, or a named `CLAUDE.md` (user-global or repo-level) with the missing/ignored rule identified. Never a generic observation.
4. **Write the report** — render a standalone, self-contained, light/dark-aware HTML report (no external assets, no network calls) to `~/.claude/reflection/reports/{ISO-timestamp}.html`. The report is written locally only — never published, uploaded, or shared via the Artifact tool or any other mechanism. Then update the log in place, split by root-cause attribution: entries in groups with no nameable root cause are set to `reported (report: {path}, at: {timestamp})` immediately; entries in root-caused groups are NOT marked `reported` until a mandatory per-finding remediation question is answered — file a follow-on story (status gains `| story: sc-XXXX`) or explicitly decline tracking (status gains `| declined: {ISO-8601 timestamp}`) — with the status and the trailing field written in the same log edit. A report file existing is never, by itself, grounds to mark a root-caused finding `reported`. Already-tracked groups are left untouched.

Report output (also uncommitted runtime state): `~/.claude/reflection/reports/`.

The skill never edits any file other than appending catch-up entries to the log (phase 2), writing its own report (phase 4), and updating existing log entries' `status` segments in place (phase 4) — it only ever suggests fixes, never applies them.

## File Layout

```
hooks/
  hooks.json                        # SessionStart hook registration
  reflection_session_start.py       # Emits watch-and-log instructions on every session start, plus a conditional /reflect nudge when open log entries exist
skills/
  reflect/
    SKILL.md                        # /reflect: read -> catch-up scan -> synthesize -> report
tests/
  conftest.py                       # Shared pytest fixtures (HOME redirect, hook module loader)
  test_reflection_session_start.py  # Unit tests for the SessionStart hook's open-entries gating and nudge logic
.claude-plugin/
  plugin.json                       # Plugin manifest
```

## Working on This Codebase

Content is hook scripts plus a Markdown skill definition — there is no compiled code and no build step. The SessionStart hook has real branching logic (open-entries gating for the nudge) covered by a pytest suite: run `python3 -m pytest plugins/reflection/tests/` from the repo root. The reflect skill's behavior is agent-driven at runtime, not deterministic code, so it remains verified through manual scenarios rather than unit tests. When changing behavior, bump the version in `.claude-plugin/plugin.json`.

**Do not** add a hard dependency on or required integration with `plugins/dev-workflow` — this plugin is deliberately standalone so it works in any session. The `reflect` skill's remediation offer may probe for and optionally invoke an already-installed story-creation-capable skill (runtime-detected by naming pattern, e.g. `*:create-story`) to self-file a bundled ticket; this soft integration must always degrade cleanly to the standalone "file it yourself" flow when no such skill is installed, and must never become a required import or hard dependency on any specific plugin.
