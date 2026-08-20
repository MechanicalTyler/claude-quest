# Context Compaction Protocol

Shared reference for all full-cycle checkpoint, sentinel, and compaction-fallback behavior.
Read this doc at skill startup when invoking full-cycle with a story ID.

---

## Checkpoint State File

Path: `~/.claude/dev-workflow/state/{story-id}.json`

Schema:
```json
{
  "story_id": "sc-1043",
  "repos": {
    "api": {
      "pr_number": 42,
      "stage": "review-loop",
      "review_loop_count": 1,
      "test_loop_count": 0,
      "next_action": "re-dispatch review-pr subagent for PR 42"
    },
    "web": {
      "pr_number": 43,
      "stage": "test-loop",
      "review_loop_count": 0,
      "test_loop_count": 1,
      "next_action": "re-dispatch test-pr subagent for PR 43"
    }
  },
  "approval_text": "Approved — proceed with the spec as written.",
  "approval_timestamp": "2026-06-10T16:05:00Z",
  "updated_at": "2026-06-10T17:30:00Z"
}
```

Each key under `repos` is a service/repo name, matching `repo-discovery.md`'s "service
name" convention. A single-repo story's `repos` map has exactly one entry and behaves
identically to the old single-valued fields, with no special-casing required by consuming
code paths.

### Write points

full-cycle writes the checkpoint at **every** stage boundary and loop iteration. Every
write below updates the correct repo's entry in the `repos` map, except where noted as a
top-level field:

- **After create-story returns:** initialize one `repos` entry per repo named in the
  story's "Repos to modify" field (per `repo-discovery.md`'s reconciliation rules — this
  field is set at story creation, so it is available immediately, independent of any
  later on-disk path resolution). Each entry starts as `pr_number: null, stage:
  "write-spec", review_loop_count: 0, test_loop_count: 0`.
- **After the user approves the spec in write-spec** (before start-development begins) —
  record the top-level `approval_text` (the user's literal approval message, verbatim)
  and `approval_timestamp` (ISO-8601 time the approval was given). These two fields are
  the mechanical evidence that the spec-approval gate actually fired; full-cycle refuses
  to dispatch start-development without them (see full-cycle's "Hard gate — recorded
  approval"). Also update every existing repo entry's `stage` to `"start-development"`
  (still `pr_number: null` — no PR exists yet).
- **After the start-development subagent returns:** for each PR it resolved, update that
  repo's entry with the real `pr_number` and advance `stage` to `"review-pr"`.
- **After each review-loop / test-loop iteration:** increment that PR's repo entry's
  `review_loop_count` / `test_loop_count`.
- **After a given PR's test-pr passes:** advance that repo's entry's `stage` to `"done"`.
  Other repos' entries are untouched and continue independently — this is the terminal
  state a fully finished repo reaches while a sibling repo can still be mid-loop.

The checkpoint **complements** GitHub/PM state — it stores what GitHub cannot: loop counts and
the orchestrator's next intended action. GitHub/PM remain authoritative for resume detection.

### Checkpoint write failure

If a write fails (disk full, permissions), surface the error to the user and continue.
Do NOT abort the pipeline. GitHub/PM state remains the resume authority.

---

## Sentinel File

Path: `~/.claude/dev-workflow/state/.compact-request`

Content: the exact resume command, e.g.:
```
/start full-cycle sc-1043
```

The sentinel is **only written inside tmux** (when `$TMUX` is set). Outside tmux the manual
fallback is used instead (see below). The compact-injector Stop hook consumes (deletes) the
sentinel after reading it — a sentinel is single-use.

### Stale sentinel

A sentinel older than 10 minutes is stale. The Stop hook deletes it without acting.

---

## High-Context Handoff Procedure

When the context meter has reported ≥75% and full-cycle reaches a stage boundary:

### Inside tmux (`$TMUX` is set)

1. Write the checkpoint (see Write points above).
2. Write the sentinel file with the resume command.
3. Announce to the user:

   > **Compacting at stage handoff.** Context has reached a high-usage threshold. Writing checkpoint and requesting /compact — the pipeline will resume automatically after compaction.

4. End the turn. The compact-injector Stop hook fires next.

### Outside tmux (`$TMUX` is not set)

1. Write the checkpoint.
2. Do **not** write the sentinel.
3. End the turn with this exact message (substitute the actual story ID):

   > **Good compaction point.** Context is high. To keep state clean, please run:
   >
   > 1. `/compact`
   > 2. `/start full-cycle {story-id}`
   >
   > The checkpoint has been written — the pipeline will re-enter at the correct stage.

---

## Compact-Injector Behavior Summary

`hooks/compact-injector.sh` (Stop hook):

1. If no sentinel exists → exit 0 (nothing to do).
2. If sentinel is older than 10 minutes → delete it, exit 0 (stale).
3. If `$TMUX` is not set → exit 0 (tmux required for injection).
4. Read the resume command from the sentinel, delete the sentinel, spawn detached injector.

Detached injector (runs after a ~2-second delay, out-of-band):

1. Confirm Claude Code pane shows idle prompt via `tmux capture-pane`.
2. Send `/compact` to the pane.
3. Poll pane until compaction completes (prompt returns).
4. Send the resume command.
5. Max 3 retries on any step. On final failure, write `~/.claude/dev-workflow/state/.compact-request.failed` and stop.
