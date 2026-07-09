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
  "stage": "review-loop",
  "pr_numbers": [42],
  "review_loop_count": 1,
  "test_loop_count": 0,
  "next_action": "re-dispatch review-pr subagent for PR 42",
  "updated_at": "2026-06-10T17:30:00Z"
}
```

### Write points

full-cycle writes the checkpoint at **every** stage boundary and loop iteration:

- After create-story returns a story ID
- After the user approves the spec in write-spec (before start-development begins)
- After each stage subagent (start-development, review-pr, test-pr, address-pr-comments) returns
- After each review-loop iteration (increment `review_loop_count`)
- After each test-loop iteration (increment `test_loop_count`)

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
