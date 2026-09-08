# Checkpoint Seeding

Shared procedure for a stage skill to seed or refresh its own entry in the dev-workflow
checkpoint (`~/.claude/dev-workflow/state/{story-id}.json`, schema defined in
`context-compaction.md`) when invoked standalone — outside `full-cycle`/`epic`, which
already write this file at their own stage boundaries (see `context-compaction.md` →
"Write points"). Every stage skill listed in that file's Write points table calls one of
the two procedures below at the point in its own flow noted there.

Both procedures are **best-effort telemetry, never a functional gate.** A failure at any
step — an unresolved story ID, an unwritable state directory, a malformed existing file —
is never surfaced as an error to the user and never blocks the caller's real work. Silently
skip (for an unresolved story ID) or surface-and-continue (for a write failure, per
`context-compaction.md` → "Checkpoint write failure") and proceed with the rest of the
skill exactly as if this procedure had not been called.

---

## Seed or Refresh Stage

**Inputs:** a story ID (or none), a list of repo names, a stage value, and optionally a PR
number.

1. **No story ID resolved:** no-op silently. Do not write anything, do not warn, do not
   block. This is the expected outcome whenever the caller cannot resolve a story ID (e.g.
   `reviewing-prs`/`testing-prs`/`addressing-pr-comments` on a PR with no linked story) —
   proceed with the rest of the skill unchanged.
2. **Read the existing checkpoint**, if any, at `~/.claude/dev-workflow/state/{story-id}.json`.
   - If the file exists and parses as a JSON object, use it as the base.
   - If the file does not exist, or exists but fails to parse as a JSON object, start from
     a fresh `{"story_id": "{story-id}", "repos": {}}` shape — a malformed existing file is
     never a reason to stop; treat it the same as absent.
3. **Upsert each named repo's entry** in the `repos` map:
   - If the repo has no existing entry, create one: `{"stage": "{stage}", "pr_number":
     null, "review_loop_count": 0, "test_loop_count": 0}`, then set `stage` to the given
     value and `pr_number` to the given PR number if one was supplied.
   - If the repo already has an entry, set only its `stage` field to the given value.
     When a PR number is supplied AND the entry's existing `pr_number` is `null`/absent,
     set it too. Never overwrite an already-set `pr_number` with a different value, and
     never touch `review_loop_count`, `test_loop_count`, or `next_action` — those fields
     are full-cycle/epic's own bookkeeping and this procedure is a merge-upsert, not a
     replace.
4. **Update the top-level `updated_at`** to the current ISO-8601 UTC timestamp.
5. **Write atomically.** Write the full updated JSON to a temp file in the same directory
   (e.g. `~/.claude/dev-workflow/state/.tmp-{story-id}-{unix-timestamp}-{pid}.json`), then
   `mv` it onto the real path — a plain rename on the same filesystem, so a concurrent
   reader (e.g. attention-hub's `get_dev_workflow_stage`) never observes a partially
   written file.
6. **On any failure in steps 2-5** (permission error, disk full, or any other write
   failure): surface the error to the user per `context-compaction.md` → "Checkpoint write
   failure", and continue — never block or abort the caller's real work over a checkpoint
   write failure.

This procedure never touches `review_loop_count`, `test_loop_count`, `approval_text`, or
`approval_timestamp` — those remain exclusively full-cycle/epic's own writes (see
`context-compaction.md` → "Write points"). A dispatched subagent's own standalone self-seed
(this procedure) and full-cycle's post-return write to the same repo entry can therefore
never clobber each other's fields, regardless of which one runs first or last within the
same pipeline execution.

---

## Seed Pending Pre-Story Placeholder

**Input:** a list of candidate repo names, discovered before any story exists.

Used only by `creating-stories` Phase 0, for the window between repo discovery and story
creation where no story ID exists yet to key a checkpoint by.

1. Build a `repos` map with one entry per candidate repo, each `{"stage": "init",
   "pr_number": null, "review_loop_count": 0, "test_loop_count": 0}`.
2. Write this to a uniquely named file in the checkpoint state directory:
   `~/.claude/dev-workflow/state/.pending-{unix-timestamp}-{pid}.json` — the leading dot
   matches the existing `.compact-request` sentinel's dot-prefixed convention for
   non-story runtime state in this directory. The `stage: "init"` entries are the freshest
   file on disk as soon as they're written, so they shadow any stale prior-story checkpoint
   for the same repo in `get_dev_workflow_stage`'s freshest-mtime-wins lookup — see
   `context-compaction.md`'s Legacy stage values note for how a reader treats an unrecognized
   stage value as opaque; `"init"` is simply never terminal (`STAGE_TERMINAL_STAGES` is
   `{"done", "finished"}`), so it always matches.
3. Return the placeholder file's path to the caller — `creating-stories` needs it to delete
   the file later (see its own Phase 0/Phase 6 instructions for the exact cleanup trigger
   points).
4. **On any write failure:** surface the error to the user and continue — same
   best-effort posture as "Seed or Refresh Stage" above. Proceed with the rest of
   `creating-stories` unchanged; the interview and story creation do not depend on this
   placeholder existing.

**Cleanup is the caller's responsibility, not this procedure's.** This procedure only
creates the placeholder file and reports its path — see `creating-stories/SKILL.md`'s own
instructions for when the placeholder must be deleted (every exit path: normal completion,
a Phase 5 user cancel, and a Phase 6 creation failure).
