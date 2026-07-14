---
name: reflection:reflect
description: "Use when the user wants to review what went wrong in recent sessions, asks why the agent keeps getting corrected on the same thing, or says '/reflect', 'review how this session went,' or 'what problems came up.'"
---

# Reflect

**Role:** Read the reflection log, catch up on anything not yet captured, synthesize recurring problems with a specific root cause for each, and write the findings as a self-contained HTML report.

**SCOPE BOUNDARY:** This skill only ever *suggests* improvements in its own report output — it never edits another skill's or plugin's files, and it never edits `CLAUDE.md` files itself. The only files it writes are (a) newly caught-up entries appended to `~/.claude/reflection/log.md` in Phase 2, and (b) its own report file in Phase 4.

## Arguments: $ARGUMENTS

No required arguments.

---

## Phase 1: Read the log

Read `~/.claude/reflection/log.md`.

- If the file does not exist, or exists but is empty (no entries), note "no logged entries" and continue to Phase 3 with nothing to synthesize yet — Phase 2's catch-up scan may still surface entries to synthesize.
- Otherwise, parse all entries: each has a timestamp, a context note, a trigger type, and a quote/paraphrase.

## Phase 2: Catch-up scan

Two passes, in order:

**Pass A — live conversation.** Review the current conversation directly (it's already in context; no file read needed) for any of the five trigger types (correction of a claim; "no"/"don't"/"stop doing X"; a repeated/rephrased request; pushback on a proposed approach; visible frustration/escalation) that are not already reflected in the log. Append any newly found entries to `~/.claude/reflection/log.md` in the same format as existing entries.

**Pass B — most recent prior session.** Locate the current project's folder under `~/.claude/projects/` and find the most recently modified `.jsonl` transcript file in it, excluding the live session's own transcript file. If no such other file exists, skip this pass — that is not an error. Otherwise, read that transcript, scan its user-turn text for the same five trigger types, and append any newly found entries to the log.

## Phase 3: Synthesize with root-cause attribution

Group all log entries (original + newly caught-up) by their context note.

For any context with two or more entries, or a single entry that clearly points at a fixable gap, determine the root cause before writing a suggestion:

- **If the context names a skill:** locate that skill's actual `SKILL.md` under `~/.claude/plugins/cache/{marketplace}/{plugin}/{version}/skills/{skill}/` — search by skill/plugin name across marketplaces and plugins if the exact path isn't immediately obvious — and quote the specific instruction, phase, or missing case responsible for the recurring problem.
- **If no specific skill was active:** check the relevant `CLAUDE.md` files (`~/.claude/CLAUDE.md` and the current repo's own `CLAUDE.md`) for whether the expectation is already stated (and being ignored) or absent (and needs a new rule). Say which, and name the exact file.

Every suggestion must name either a skill file + section, or a specific `CLAUDE.md` + the rule to add. Never write a generic observation like "communicate better" — if a context's entries don't point at a specific, nameable cause, say so explicitly rather than inventing one.

## Phase 4: Write the report

Render the synthesis as a standalone, self-contained HTML document:

- Inline `<style>` only — no external stylesheets, fonts, CDN scripts, or network calls of any kind.
- Light/dark aware via `@media (prefers-color-scheme: dark)`.
- One section per root cause. Each section shows:
  - The recurring pattern (what kept happening)
  - Supporting quotes pulled from the log entries in that group
  - The attributed root cause (named skill file + section, or named `CLAUDE.md` + rule)
  - The concrete suggested fix

Write the file to `~/.claude/reflection/reports/{ISO-timestamp}.html` (creating the `reports/` folder if it doesn't exist yet — timestamp formatted so it sorts correctly as a filename, e.g. `2026-07-10T14-32-05.html`).

Tell the user the file path. In interactive mode, then go through the report's suggestions one at a time: for each suggestion Phase 3 traced to a specific, nameable root cause, explicitly offer to turn that finding into a trackable follow-on story or task using whatever story- or task-tracking tool the user has available — the offer names no specific plugin or skill, so it works in any session (added after the sc-1242 story-creation flow, where a root-caused finding only became a tracked story after the user had to ask twice). Suggestions Phase 3 could not trace to a specific cause get no offer — there is nothing fixable to file. Acting on an offer remains a separate, explicit follow-up outside this skill's own scope: this skill does not implement the fix itself and never creates a story, task, or any other artifact on its own initiative — an affirmative answer means the user proceeds with their own tooling.
