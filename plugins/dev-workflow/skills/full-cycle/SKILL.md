---
name: dev-workflow:full-cycle
description: "Drives the entire dev-workflow lifecycle end to end in order — create-story → write-spec → start-development → review-pr → test-pr — looping back through review and testing until both pass. Use when a user wants to run the whole development pipeline for a feature, take a story 'all the way through', or says 'full cycle', 'end to end', 'run the whole workflow', or '/start full-cycle'. Resumable: re-invoke at any point and it detects current story/PR state and enters at the correct stage."
---

# Full Cycle

**Role:** Orchestrator — drive the entire dev-workflow lifecycle from idea to tested PR, in order, looping the stages that must repeat.

**SCOPE BOUNDARY:** This skill **sequences** the existing dev-workflow skills — it does not reimplement any stage. It never writes feature code, specs, or PRs directly; each stage's own skill does that. The orchestrator's only direct actions are: talking to the user during the interactive stages, dispatching subagents for the non-interactive stages, reading PM/GitHub state to decide what runs next, and producing the end-of-run summary. This restriction holds even when the user directly asks for a mid-session fix — such a fix must always be routed through a `dev-workflow-fixer` Agent-tool dispatch, never handled with a direct `Edit`/`Bash`/`git` call in the orchestrator's own context. It **never merges the PR** — a human does that.

## Arguments: $ARGUMENTS

The skill accepts one of:

- **A PM story ID** (e.g., `sc-1043` or `1043`) — resume an existing story; detect its current state and enter the pipeline at the correct stage.
- **A free-form feature description** — begin a brand-new cycle at create-story.
- **No argument** — begin a brand-new cycle at create-story (create-story will prompt for the description).

Read `skills/shared/standards.md` — these mandatory rules govern this entire session.

Read `skills/shared/adapter-loading.md` — adapter loading procedures referenced in Setup.

Read `skills/shared/repo-discovery.md` — repo discovery procedure used by the stages this skill sequences.

Read `skills/shared/context-compaction.md` — checkpoint protocol, sentinel format, and non-tmux fallback wording used throughout this skill.

Read the CLAUDE.md file in this repository before starting.

---

## Setup: Load Adapters

1. Read `~/.claude/dev-workflow/config.json`
2. Note `pm_adapter` and `notes_adapter` values
3. Note the `models` section (if present) — used for stage-dispatch model resolution throughout this skill (see "Subagent model selection" below and "Subagent Model Selection" in `standards.md`)
4. Load PM adapter per procedure in `skills/shared/adapter-loading.md`
5. Load notes adapter per procedure in `skills/shared/adapter-loading.md`

Parse `$ARGUMENTS`:

- Matches a story ID pattern (`sc-NNNNN` or bare `NNNNN`) → treat as a **story ID**; go to Resume / Entry Detection.
- Non-empty and not a story ID → treat as a **feature description**; there is no story yet, so the entry stage is create-story (carry the description into that stage).
- Empty → no story yet; the entry stage is create-story.

---

## Interactive vs. Subagent Stages

This is the central design decision for this skill (resolved with the user — see the sc-1043 spec):

| Stage | Where it runs | Why |
|-------|---------------|-----|
| create-story | **Main orchestrator** (interactive) | Interviews the user; needs to ask questions. |
| write-spec | **Main orchestrator** (interactive) | Must gate development on the user's explicit spec approval. |
| start-development | **Subagent** | Non-interactive heavy implementation. |
| review-pr | **Subagent** | Non-interactive review. |
| test-pr | **Subagent** | Non-interactive functional testing. |
| address-pr-comments (loop-back) | **Subagent** | Non-interactive fix work on the same PR. |

A dispatched subagent has no tool to ask the user. The implementation/review/test stages (start-development, review-pr, test-pr) run their underlying skill in **autonomous mode** and return a single-line key/value result (see "Autonomous mode" and "Output Mode Detection" in `standards.md`); the orchestrator reads that result only as a hint. address-pr-comments does **not** emit a key/value result — it implements fixes and posts PR replies — so the orchestrator never depends on its return value. For every review/test outcome the orchestrator **re-confirms the authoritative state from GitHub and the PM story** (see Reading the Authoritative Review Decision) rather than trusting any subagent self-report.

**PR-branch checkout for subagent stages that operate on an existing PR.** review-pr and test-pr take a PR number argument, but `dev-workflow:address-pr-comments` resolves the PR from the *current branch* (`gh pr status`) — a freshly dispatched subagent is not checked out on that branch. Therefore every subagent prompt that runs address-pr-comments (or any stage that must act on an existing PR's branch) MUST first check out the PR branch:

```bash
gh pr checkout {PR_NUMBER}
```

Pass the explicit PR number in the prompt as well, so the subagent never has to guess or ask.

**How to dispatch (mandatory — per `standards.md` → "Subagent Dispatch"):**

Every subagent stage below runs in a **fresh, isolated context**. To get that, you MUST
dispatch it with the **Agent tool**, passing the stage's dedicated `subagent_type`. Do
**not** invoke the `Skill` tool yourself for a downstream stage — `Skill` loads content
into *your* context (no subagent), which is exactly the "everything runs in one agent"
failure this design prevents. Each worker's body invokes the matching
`dev-workflow:{stage}` skill autonomously, so stage behavior is unchanged.

**Every stage dispatch below is sequential — you cannot proceed until it returns.**
Dispatch it to block for its result per `standards.md` → "Subagent Wait Discipline"; do
not background it and end your turn to wait on a notification. This applies to every
"Dispatch the Agent tool" instruction in this skill, including inside the Review Loop and
Test Loop.

**Subagent type + model per dispatch.** Resolve the model with the resolution order
`models.stages.<stage-key>` → `models.<task-type>` → built-in default, then pass it as the
`model` parameter on the Agent call (it overrides the worker's frontmatter default):

| Stage / dispatch | `subagent_type` | `stages` key | Task type | Default model |
|-----------------|-----------------|--------------|-----------|---------------|
| entry-detection | `dev-workflow-pr-state-reader` | `entry-detection` | `implementation` | `sonnet` |
| write-spec (autonomous path only) | `dev-workflow-spec-writer` | `write-spec` | `implementation` | `sonnet` |
| start-development | `dev-workflow-developer` | `start-development` | `implementation` | `sonnet` |
| pr-number-read | `dev-workflow-pr-state-reader` | `pr-number-read` | `implementation` | `sonnet` |
| review-pr | `dev-workflow-reviewer` | `review-pr` | `review` | `opus` |
| address-pr-comments (fix loop) | `dev-workflow-fixer` | `address-pr-comments` | `implementation` | `sonnet` |
| test-pr | `dev-workflow-tester` | `test-pr` | `review` | `opus` |
| decision-read | `dev-workflow-pr-state-reader` | `decision-read` | `implementation` | `sonnet` |

**Output mode (per `standards.md` → "Output Mode Detection").** Determine the mode at startup. The orchestrator is **interactive by nature** when it must run create-story or write-spec, because those stages require user input (the spec-approval gate especially). If the skill is running non-interactively (no way to ask the user) AND the detected entry stage is create-story or write-spec, STOP and surface that the pipeline needs an interactive session to define/approve the spec. When resuming at start-development or later, no further interaction is required and the run may complete autonomously, emitting the flat key/value summary at Termination.

---

## Resume / Entry Detection

The skill is resumable: re-invoking it at any time must enter the pipeline at the correct stage. Determine the entry stage from PM story state, whether a linked PR exists, the PR's review decision, and test-pr's tracking labels. Evaluate top to bottom and enter at the **first** matching stage.

**Process Fidelity applies here (see `standards.md` → "Process Fidelity").** Entry detection selects where the pipeline resumes — it never skips or reorders work: entering at a non-default stage, skipping a stage (including write-spec or its User Approval Gate), or running stages out of the documented order beyond what the table below dictates requires asking the user for explicit permission first, never a silent inference from PR/story state.

**Why the row order matters:** when test-pr fails it submits a `REQUEST_CHANGES` review, which drives the PR's aggregate `reviewDecision` to `CHANGES_REQUESTED` — the *same* value review-pr produces when review fails. The PR review decision alone therefore cannot tell a failed review from a failed test. The `tests-failing` / `tested-in-dev` labels (set by test-pr — see the test-pr label requirement) are the disambiguator, so the label rows are evaluated **before** the generic `reviewDecision == CHANGES_REQUESTED` row.

| # | Observed state | Entry stage |
|---|----------------|-------------|
| 1 | No story yet (no story ID; feature description or empty argument) | **create-story** |
| 2 | Story exists but no spec is linked, or story state is "In Spec" / earlier | **write-spec** |
| 3 | Spec present / story "Ready for Dev" and **no** linked PR | **start-development** |
| 4 | Linked PR carries the `tested-in-dev` label and no `tests-failing` label | **finished** — testing passed; report and stop |
| 5 | Linked PR carries the `tests-failing` label | **address-pr-comments → test-pr** (test loop) |
| 6 | Linked PR `reviewDecision` is `CHANGES_REQUESTED` (and no `tests-failing` label) | **address-pr-comments → review-pr** (review loop) |
| 7 | Linked PR is review-approved with no `tested-in-dev`/`tests-failing` label | **test-pr** |
| 8 | Linked PR exists but has no review decision yet (`REVIEW_REQUIRED`/null) | **review-pr** |

How to gather each signal:

1. **Story state:** fetch the story via the PM adapter; read its workflow state. Treat it as a coarse, informational signal only — the plugin's built-in stages do **not** set a "Dev Complete" (or equivalent terminal) state, so resume detection must not depend on one. (A particular PM adapter may add such a transition; if present it corroborates the label, but the label is authoritative.)
2. **Linked PR:** use the PM adapter's "Finding PRs linked to a story" instructions. If none is linked there, fall back to `gh pr list --state all --search "{story_id}"`.
3. **Review decision:** `gh pr view {PR_NUMBER} --json reviewDecision` for the aggregate, or the latest review's `state` (see Reading the Authoritative Review Decision below).
4. **Test outcome:** test-pr applies a `tested-in-dev` (passed) or `tests-failing` (failed) label on every run (see "test-pr label requirement" below). These labels — not review recency or `reviewDecision` — are the durable signal that distinguishes the test stage from the review stage. If a review-approved PR carries **neither** label, treat it as **not yet tested** (row 7) and state that assumption to the user.

### Entry detection subagent

Gather the signals (story state, linked PRs, review decision, test labels) by
**dispatching the Agent tool** with `subagent_type: dev-workflow-pr-state-reader`
(model: resolved from `models.stages.entry-detection` → `models.implementation` → default
`sonnet`). Do not run this read inline. The dispatch prompt is:

> Fetch story {story-id} via the Shortcut MCP tool. Find any linked PRs via the
> PM adapter's "Finding PRs linked to a story" instructions (fall back to
> `gh pr list --state all --search "{story_id}"`). If a PR exists, read its
> `reviewDecision` and labels (`tested-in-dev`, `tests-failing`). Return **one line**:
>
> `entry_stage=<stage> pr=<number or none> review=<decision or none> labels=<csv or none>`

Read that one line. Use the Resume / Entry Detection table above to map it to an entry
stage. Raw PM/GitHub output never enters the main orchestrator context.

When the entry stage is mid-pipeline, run that stage, then continue forward through the remaining stages in normal order. State the detected entry stage to the user before proceeding.

### test-pr label requirement

This skill depends on test-pr labeling its outcome. test-pr is updated in this change to **always** add `tested-in-dev` on a passing run and `tests-failing` on a failing run (previously optional). If you run full-cycle against a build of test-pr that omits the labels, cold resume cannot distinguish "approved, not yet tested" from "approved and passed" — in that case it defaults to row 7 (re-test) and announces the re-test, which is safe but may repeat a passing test.

---

## Stage — create-story (interactive, main orchestrator)

Run only when there is no story yet.

This stage satisfies the Story Creation Gate in `skills/shared/standards.md` only because the user explicitly invoked full-cycle. If full-cycle itself was auto-triggered, create-story's invocation-provenance pre-gate must still fire its permission ask.

> Invoke Skill: `dev-workflow:create-story`
>
> Pass the feature description from `$ARGUMENTS` if one was provided.

Drive the interview to completion in the main agent so it can ask the user questions. Capture the resulting **story ID** and carry it forward. Proceed to write-spec.

---

## Stage — write-spec (interactive, main orchestrator)

> Invoke Skill: `dev-workflow:write-spec`
>
> Pass the story ID as the argument.

write-spec already writes one spec per repo named in the story (satisfying the "once per repo" requirement) and has its own User Approval Gate. Run it in the main agent so that gate is interactive.

**Autonomous path (e.g. an epic task):** when running autonomously there is no human to satisfy the approval gate, so do **not** run write-spec in this orchestrator's context. Instead **dispatch the Agent tool** with `subagent_type: dev-workflow-spec-writer` (model: resolved from `models.stages.write-spec` → `models.implementation` → default `sonnet`), passing the story/task ID and any PM-adapter override. The worker produces the spec(s) and proceeds — there is no interactive gate to honor in this mode.

**Mandatory confirmation gate (interactive path only):** Do NOT advance to start-development until the user has explicitly approved the spec(s) through write-spec's approval gate. If the user requests changes, let write-spec revise and re-present until approved. Only on explicit approval do you proceed.

**State ownership:** write-spec owns the "Ready for Dev" transition and the `claude-written` label. The orchestrator does not duplicate them.

---

## Stage — start-development (subagent)

**Dispatch the Agent tool** with `subagent_type: dev-workflow-developer` (model: resolved from `models.stages.start-development` → `models.implementation` → default `sonnet`). The worker's body already invokes `dev-workflow:start-development` autonomously; your dispatch prompt supplies only the variable inputs:

> Story/task ID: `{story-id}`. Run autonomously. [For an epic task, also pass the PM-adapter override, branch name, and the "do NOT use git worktrees" override.]

The subagent branches, implements with TDD, and opens the PR (one PR per repo for a multi-repo story). It returns its autonomous-mode key/value result.

After it returns, **dispatch the Agent tool** with `subagent_type: dev-workflow-pr-state-reader` (model: resolved from `models.stages.pr-number-read` → `models.implementation` → default `sonnet`) to resolve the **PR number(s)** authoritatively — do not resolve this inline. Dispatch prompt:

> Find any linked PRs for story `{story_id}` via the PM adapter's "Finding PRs linked to a story"
> instructions (the subagent attaches the PR to the story on creation), falling back to
> `gh pr list --state all --search "{story_id}"`. Return **one line**:
>
> `pr_numbers=<csv or none>`

Read that one line. Do not rely solely on the subagent's self-reported PR number, and never let raw PM/GitHub JSON enter the main orchestrator context.

**State ownership:** start-development owns the "In Development" transition. The orchestrator does not duplicate it.

Then proceed to review-pr for each resulting PR.

---

## Stage — review-pr (subagent)

For each PR produced by start-development:

**Dispatch the Agent tool** with `subagent_type: dev-workflow-reviewer` (model: resolved from `models.stages.review-pr` → `models.review` → default `opus`). The worker's body already invokes `dev-workflow:review-pr` autonomously and already carries the fresh-dev-build-CI mandate; your dispatch prompt supplies only:

> PR number: `{PR_NUMBER}`. Run autonomously.
>
> (Reminder, also enforced by the worker: you MUST trigger the **dev build CI** fresh on the PR's current HEAD and wait for it to reach a terminal state before reviewing. An approval without a fresh dev build CI run on current HEAD is invalid — the orchestrator treats it as a failed review. A non-passing CI result (failed/cancelled/timed-out) must yield REQUEST_CHANGES, never APPROVE. The sole exception is a repo explicitly listed in `ci_gate_exempt_repos`: there a CI-free APPROVE is **valid** and must NOT be treated as a failed stage or looped — the review body will say the gate was skipped by exemption.)

After it returns, read the PR's latest **review** decision authoritatively from GitHub (see below). Use that — not the subagent's self-report — to decide the next step.

---

## Review Loop

While the latest review decision for the PR is **changes requested**:

1. **Dispatch the Agent tool** with `subagent_type: dev-workflow-fixer` (model: resolved from `models.stages.address-pr-comments` → `models.implementation` → default `sonnet`). The worker's body already checks out the PR branch (`gh pr checkout {PR_NUMBER}`) and invokes `dev-workflow:address-pr-comments`; your dispatch prompt supplies only:
   > PR number: `{PR_NUMBER}`.

   It implements the requested changes on the **same branch and PR** and replies to the review.
2. Re-dispatch the reviewer via the Agent tool (`subagent_type: dev-workflow-reviewer`, model: resolved from `models.stages.review-pr` → `models.review` → default `opus`) for the same PR.
3. Re-read the authoritative review decision (the newest review submitted since this re-dispatch).

Repeat until the review decision is **approved**, subject to the Loop Safety Guard below. Then proceed to test-pr.

---

## Stage — test-pr (subagent)

Once the PR is review-approved:

**Dispatch the Agent tool** with `subagent_type: dev-workflow-tester` (model: resolved from `models.stages.test-pr` → `models.review` → default `opus`). The worker's body already invokes `dev-workflow:test-pr` autonomously and already carries the fresh-dev-deploy mandate; your dispatch prompt supplies only:

> PR number: `{PR_NUMBER}`. Run autonomously.
>
> (Reminder, also enforced by the worker: you MUST run the **dev deploy CI** to deploy the branch fresh and wait for it to succeed before executing any test scenario. A test result without a fresh dev deploy is invalid — the orchestrator treats it as a failed test. A local/Makefile/script deploy never counts; without a successful dev deploy CI run the verdict is REQUEST_CHANGES + `tests-failing`, never APPROVE. The sole exception is a repo explicitly listed in `deploy_gate_exempt_repos`: there a deploy-CI-free APPROVE is **valid** and must NOT be treated as a failed stage or looped — the test report will say functional dev testing was skipped by exemption.)

After it returns, read the PR's latest **test** decision authoritatively from GitHub.

**State ownership:** test-pr owns its outcome labels — it submits the `APPROVE`/`REQUEST_CHANGES` review and applies `tested-in-dev` (pass) or `tests-failing` (fail). The orchestrator only reads these; it never labels or transitions the PR/story itself.

---

## Test Loop

While testing **requests changes**:

1. **Dispatch the Agent tool** with `subagent_type: dev-workflow-fixer` (model: resolved from `models.stages.address-pr-comments` → `models.implementation` → default `sonnet`) for the same PR — the worker checks out the branch and invokes `dev-workflow:address-pr-comments`; pass only the PR number `{PR_NUMBER}`.
2. Re-dispatch the tester via the Agent tool (`subagent_type: dev-workflow-tester`, model: resolved from `models.stages.test-pr` → `models.review` → default `opus`) for the same PR.
3. Re-read the authoritative test decision (the newest review submitted since this re-dispatch).

Repeat until testing **passes**, subject to the Loop Safety Guard below.

---

## Reading the Authoritative Review Decision

Both review-pr and test-pr submit a **formal GitHub review** with an event of `APPROVE` or `REQUEST_CHANGES`. Read the latest decision from GitHub rather than trusting a subagent's self-report:

```bash
gh api repos/{owner}/{repo}/pulls/{PR_NUMBER}/reviews
```

Take the **most recent** review (highest `submitted_at`) and read its `state`:

- `APPROVED` → treat as **approved** / **passing**.
- `CHANGES_REQUESTED` → treat as **changes requested**.
- `COMMENTED` / `PENDING` → not a decision; the stage did not conclude — surface this to the user rather than looping.

**Dispatch this read via the Agent tool** with `subagent_type: dev-workflow-pr-state-reader` (model: resolved from `models.stages.decision-read` → `models.implementation` → default `sonnet`), returning one line:

> Run: `gh api repos/{owner}/{repo}/pulls/{PR_NUMBER}/reviews`
> Return **one line**: `decision=<APPROVED|CHANGES_REQUESTED|COMMENTED> submitted_at=<ISO>`

Read that one line. Never let the raw `gh api` JSON enter the main orchestrator context.

`gh pr view {PR_NUMBER} --json reviewDecision` is an acceptable convenience equivalent for the PR-level aggregate decision.

Because review-pr and test-pr both submit reviews on the same PR (and as the same bot author), recency alone cannot tell their decisions apart on a PR that has both. Disambiguate by context, not author:

- **Immediately after re-dispatching a specific stage**, read the newest review created since that dispatch — that one belongs to the stage you just ran. Recency is reliable here because you control the ordering.
- **For cold resume detection** (you did not just run a stage), do NOT infer the test outcome from review recency or from `reviewDecision` (a failed test and a failed review both produce `CHANGES_REQUESTED`). Use the durable signals instead: the `tested-in-dev` / `tests-failing` labels record test-pr's last outcome, and `reviewDecision` reflects the review stage only after the labels have been consulted. See Resume / Entry Detection.

---

## Loop Safety Guard

Neither the review loop nor the test loop may run forever. Track an attempt count per loop. After **3** fix-and-recheck cycles for a given loop without reaching approval/passing, **stop** and surface the situation to the user with: the PR number, the outstanding review/test feedback, and the cycle count. Do not continue looping. *[Inference — not specified in the story; included as a correctness safeguard for an automated loop.]*

---

## Termination

When testing passes — test-pr has submitted an `APPROVE` review and applied the `tested-in-dev` label — stop. **Leave the PR open** — do not merge. Produce a short end-of-run summary:

- Story ID and title
- PR number(s) and URL(s)
- Final test outcome (review approved + `tested-in-dev`) and current story state
- Per-loop fix-cycle counts, so an operator can see how many cycles each stage burned
- Note that the PR is left open for a human to merge

In autonomous mode, emit the summary as the flat key/value result defined in `standards.md` (`service-name`, `pm-key`, `pr-number`, `status`, `message`, plus the highest-signal extra keys such as `test-result`).

---

## State-Ownership Boundaries

The orchestrator only sequences stages; it must **never** fire a PM state transition owned by an individual skill:

- write-spec owns **"Ready for Dev"** (and the `claude-written` label)
- start-development owns **"In Development"**
- test-pr owns its **review submission and `tested-in-dev`/`tests-failing` labels**

The orchestrator never duplicates these transitions or labels. Its job between stages is to read state, not to write it.

---

## Context Hygiene

Read `skills/shared/context-compaction.md` at startup — it defines the checkpoint
schema, sentinel format, stale-sentinel lifecycle, and the exact non-tmux fallback
message wording. This section describes when full-cycle calls those procedures.

### Checkpoint writes

Write the checkpoint (`~/.claude/dev-workflow/state/{story-id}.json`) at every stage
boundary and loop iteration, using the stage and key facts at that moment:

| Moment | `stage` value | Notes |
|--------|---------------|-------|
| After create-story returns | `"write-spec"` | `story_id` now known |
| After spec approval gate | `"start-development"` | — |
| After start-development subagent returns | `"review-pr"` | record `pr_numbers` |
| After each address-pr-comments + review-pr iteration | `"review-loop"` | increment `review_loop_count` |
| After each address-pr-comments + test-pr iteration | `"test-loop"` | increment `test_loop_count` |
| After test-pr passes | `"done"` | final checkpoint |

If a checkpoint write fails, surface the error to the user and continue — do not abort.

### High-context handoff

When the context meter (PostToolUse hook) has reported ≥75% usage and full-cycle
reaches a stage boundary, follow the high-context handoff procedure defined in
`skills/shared/context-compaction.md`:

- **Inside tmux (`$TMUX` is set):** write checkpoint, write sentinel, announce, end turn.
- **Outside tmux:** write checkpoint, emit the exact manual-fallback message with the
  actual story ID substituted, end turn. Do not write a sentinel.

The context meter's `additionalContext` message is the trigger signal — act on it at
the next stage boundary after receiving it, not mid-stage.

---

## Multi-Repo Handling

For a story spanning multiple repos, defer to the existing skills' built-in multi-repo behavior — do not reimplement it:

- write-spec already writes one spec per repo named in the story.
- start-development already opens one PR per repo.

The orchestrator then runs the review → test cycle (including the loops) **for each resulting PR** independently. A later stage for one PR does not block a different PR. *[Inference — the sc-1043 target (`claude-plugin-dev-workflow`) is a single repo; this generalizes the single-repo flow without changing it.]*

---

## Completion Criteria

- The pipeline advanced through every required stage in order, entering at the correct stage on resume.
- write-spec's user-approval gate was honored before development began.
- Each non-interactive stage ran as an **Agent-tool dispatch** to its dedicated `subagent_type` (a fresh, isolated context per stage) on the resolved model — never via an inline `Skill` call. In the interactive path, create-story and write-spec ran in the main agent for their gates; in the autonomous path, write-spec ran as the `dev-workflow-spec-writer` worker.
- The review loop and test loop each ran until approval/passing or until the Loop Safety Guard stopped them.
- Testing passed (review approved + `tested-in-dev` label) and the PR is left open (not merged).
- A clear end-of-run summary was produced.
