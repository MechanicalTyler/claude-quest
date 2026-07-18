---
name: reflection:reflect
description: "Use when the user wants to review what went wrong in recent sessions, asks why the agent keeps getting corrected on the same thing, or says '/reflect', 'review how this session went,' or 'what problems came up.'"
---

# Reflect

**Role:** Read the reflection log, catch up on anything not yet captured, synthesize recurring problems with a specific root cause for each, and write the findings as a self-contained HTML report.

**SCOPE BOUNDARY:** This skill only ever *suggests* improvements in its own report output — it never edits another skill's or plugin's files, and it never edits `CLAUDE.md` files itself. The only files it writes are (a) newly caught-up entries appended to `~/.claude/reflection/log.md` in Phase 2, (b) its own report file in Phase 4, and (c) in-place `status` updates to existing `~/.claude/reflection/log.md` entries in Phase 4 — marking entries `reported` after a report covers them is expected, in-scope behavior, not a boundary violation. The report is written only to the local `~/.claude/reflection/reports/{ISO-timestamp}.html` path — this skill must never call the Artifact tool, or otherwise publish, upload, or share the report anywhere else.

## Arguments: $ARGUMENTS

No required arguments.

---

## Phase 1: Read the log

Read `~/.claude/reflection/log.md`.

- If the file does not exist, or exists but is empty (no entries), note "no logged entries" and continue to Phase 3 with nothing to synthesize yet — Phase 2's catch-up scan may still surface entries to synthesize.
- Otherwise, parse all entries. Each entry is one line in this pipe-delimited format (the fifth `status` segment was added with sc-1255):

  `- **{ISO-8601 timestamp}** | context: {note} | trigger: {type} | {quote} | status: open`

  Parse each entry's `status`: `open` (the default for new entries), or `reported (report: {path}, at: {ISO-8601 timestamp})` once a report has covered it. An entry with no status segment at all (written before status tracking existed) is treated as `open`.

  A `reported` entry may carry up to two optional trailing fields after its status segment (added with sc-1311): `| story: sc-XXXX` (a follow-on story has been filed for the finding) or `| declined: {ISO-8601 timestamp}` (the user explicitly declined tracking it). Neither field changes the meaning of the `status:` value itself. A `reported` entry with neither field is a normal terminal state, not a pending decision: it is either a non-root-caused finding (nothing fixable to file) or a legacy entry written before these fields existed.

  > Why `status` exists: without it, a group already covered by a report is re-synthesized as new on every run — in the sc-1242 follow-up session, `/reflect` re-derived the identical root-cause write-up for the same two log entries across two consecutive runs, even after the finding had already been filed as sc-1254. Status makes "already tracked" structural instead of ad-hoc prose.

## Phase 2: Catch-up scan

Two passes, in order:

**Pass A — live conversation.** Review the current conversation directly (it's already in context; no file read needed) for any of the five trigger types (correction of a claim; "no"/"don't"/"stop doing X"; a repeated/rephrased request; pushback on a proposed approach; visible frustration/escalation) that are not already reflected in the log. Append any newly found entries to `~/.claude/reflection/log.md` in the entry format from Phase 1, ending with `| status: open`.

**Pass B — most recent prior session.** Locate the current project's folder under `~/.claude/projects/` and find the most recently modified `.jsonl` transcript file in it, excluding the live session's own transcript file. If no such other file exists, skip this pass — that is not an error. Otherwise, read that transcript, scan its user-turn text for the same five trigger types, and append any newly found entries to the log, each ending with `| status: open`.

## Phase 3: Synthesize with root-cause attribution

Group all log entries (original + newly caught-up) by their context note.

Before writing up a context group, check its entries' `status`:

- **Every entry in the group is `reported`:** skip root-cause re-derivation for that group entirely. Instead render a short "Already tracked" note in the report — the same visual box treatment used ad-hoc in `reports/2026-07-14T19-47-28.html` (a `<div class="tracked">` with an `<h3>Already tracked</h3>` heading and one short paragraph) — naming the earlier report that covered the group and, when any of the group's entries carry a `story:` field, the linked story ID read from that field. No new root-cause section, no new suggestion.
- **Any entry in the group is still `open`:** produce the full write-up as usual, using every entry in the group — both `reported` and `open` — as supporting evidence, since a recurrence of a previously-reported problem deserves a fresh full analysis.

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

Write the file to `~/.claude/reflection/reports/{ISO-timestamp}.html` (creating the `reports/` folder if it doesn't exist yet — timestamp formatted so it sorts correctly as a filename, e.g. `2026-07-10T14-32-05.html`). This file is written locally only — never uploaded, published, or shared via the Artifact tool or any other mechanism.

Immediately after the report file is written, tell the user the file path, then update `~/.claude/reflection/log.md` in place. How a group's entries transition depends on whether Phase 3 traced it to a specific, nameable root cause:

- **Groups Phase 3 could not trace to a nameable root cause:** set each entry's status to `reported (report: {path-just-written}, at: {ISO-8601 time of writing})` immediately — no offer, no `story:`/`declined:` field. There is nothing fixable to file.
- **Groups fully written up with a specific, nameable root cause:** do NOT set `status: reported` yet. First go through these findings one at a time — this remediation question is mandatory for every such finding, not conditional on any mode: ask whether the user wants to (a) file a follow-on story or task for the finding themselves, using whatever story- or task-tracking tool they have available, and report back the resulting ID, or (b) explicitly decline tracking it (the offer names no specific plugin or skill, so it works in any session — added after the sc-1242 story-creation flow, where a root-caused finding only became a tracked story after the user had to ask twice). Once answered, write the group's status and remediation outcome together in the same log edit, appended as trailing fields on each entry:
  - Answer (a): `status: reported (report: {path}, at: {time}) | story: sc-XXXX` — using the story ID the user reported back
  - Answer (b): `status: reported (report: {path}, at: {time}) | declined: {ISO-8601 time of the decision}`

  A root-caused finding is only closed out once it is linked to a story or explicitly declined — a report file existing is never, by itself, grounds to mark it `reported`.

Groups skipped as already-tracked are left untouched — their entries are already `reported`.

Acting on an offer remains a separate, explicit follow-up outside this skill's own scope: this skill does not implement the fix itself and never creates a story, task, or any other artifact on its own initiative — an affirmative answer means the user proceeds with their own tooling and reports the resulting ID back for the log.

**Accepted edge case:** if the session ends before the user answers the remediation question for a finding, that finding's entries remain at their pre-Phase-4 status (not `reported`) and the finding is fully re-processed on the next `/reflect` run.
