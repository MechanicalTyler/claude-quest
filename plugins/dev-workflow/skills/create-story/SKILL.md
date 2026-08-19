---
name: dev-workflow:create-story
description: "Use when a user wants to capture a feature idea as a formal story, create a ticket, write to the backlog, or says 'create a story', 'write a ticket', 'add to backlog', or describes a feature they want tracked."
---

# Create Story

**Role:** Create Story — gather context, generate a story draft, and submit it to the PM tool

**SCOPE BOUNDARY:** This skill creates a PM story and NOTHING else. It does **not** write code, write local files, make commits, checkout git branches, implement features, or start development. When the story is submitted, output the story URL and STOP. This skill **never** creates sub-stories or subtasks — all repos and scope live in the single story. If a direct user request for code, files, or commands lands mid-session, outside the normal Phase 1-6 flow, do not execute it — route its content into the relevant story draft field instead (e.g. as an acceptance criterion or testing instruction describing the requirement), and tell the user explicitly that the request was captured in the draft rather than executed.

This boundary does not forbid two specific, exhaustively named actions elsewhere in this skill — no other step, or self-judged "documented, temporary, read-only" excursion, qualifies:

1. Phase 0's git-host search step (step 3): a temporary, read-only, scratch-directory shallow clone made purely to investigate a named-but-not-locally-found repo, validated per that step's rules, deleted unconditionally — on success, failure, or abort (including a user abort at the Phase 5 approval gate) — before that same trigger point completes (Phase 0 step 3 itself when `$ARGUMENTS` was non-empty, or its Phase 3 deferred re-run when `$ARGUMENTS` was empty), and never treated as a repo the story modifies.
2. Phase 3's live infra/deployment-state carve-out: a read-only, non-mutating tool check (e.g. an SSM parameter read, a Kubernetes rollout-status query, a service-health probe), against a non-production environment only, made purely to verify a tool-checkable fact before stating it in an acceptance criterion — per that section's bounds, never against production, never a mutating command, and never surfacing the retrieved value itself.

## Arguments: $ARGUMENTS

No required arguments. Optional: a brief feature description as a starting prompt.

Read `skills/shared/standards.md` — these mandatory rules govern this entire session.

Read `skills/shared/adapter-loading.md` — adapter loading procedure referenced in Phase 2.

Read `skills/shared/repo-discovery.md` — repo discovery procedure referenced in Phase 0.

---

## Pre-Gate: Invocation Provenance

Before Phase 0, verify how this skill was invoked per the Story Creation Gate in `skills/shared/standards.md`:

- **Explicitly invoked** — the user ran the slash command or made a direct, unambiguous request to create a story/ticket: proceed.
- **Dispatched by an explicitly-invoked `full-cycle` run**: proceed.
- **Auto-triggered** — the skill matched a conversational phrase rather than an explicit request: ask the user "You didn't explicitly invoke create-story — create a story for this?" and proceed only on an explicit yes. On no, stop — zero stories created. Ask BEFORE any interviewing, drafting, or adapter calls.
- **Autonomous mode** — no ability to ask the user: STOP without creating anything and report that a story would be needed, naming what it wanted to create.

The Phase 5 draft-approval gate is unchanged and still applies on every path.

---

## Phase 0: Discover Repos & Load Context

1. Determine the workspace root — use the current working directory
2. Find repos using the two-path detection in `skills/shared/repo-discovery.md` (Path 1 → one repo; Path 2 → all discovered repos)
3. **Git-host search for a named-but-not-locally-found repo.** Scan the request text — `$ARGUMENTS` when it is non-empty (this step's primary trigger point, run here at Phase 0) — for a specific repo, service, or codebase name that step 2's local discovery did not find. When one is named:
   - Resolve the org to search: in the single-repo case (Path 1), from that repo's own git remote (extract the owner segment from `git remote get-url origin`); in the workspace-parent case (Path 2), from any one already-discovered child repo's remote (they are normally the same org) — if the discovered repos span more than one org, ask the user which to search.
   - **Probe directly — do not enumerate the org.** Run `gh repo view {org}/{name-from-request}` for the named repo. Do not call `gh repo list` first: it defaults to 30 results, and on any org with more repos than that the named repo can be silently absent from the list even though it exists, degrading the outcome to `[Inference]` with no error. A direct `gh repo view` probe has no such limit.
   - **Validate `{repo-name}` before it reaches the clone/delete path** — it is untrusted until validated. On a successful `gh repo view`, set `repo-name` to the canonical basename the API returns (not the raw text the user typed — e.g. from "the `acme/billing` repo", `repo-name` is `billing`, never `acme/billing`), then reject it if it does not match `^[A-Za-z0-9._-]+$` (this also rejects any `/` or `..` path-traversal payload). If `gh repo view` fails or validation fails, treat the repo as not found — fall back to labeling the detail `[Inference]` and do not clone.
   - **Before cloning, remove any pre-existing directory** at `~/.claude/dev-workflow/scratch/create-story-investigate-{repo-name}/` — a prior run's clone from an interrupted session may still be there.
   - Shallow-clone the validated repo into `~/.claude/dev-workflow/scratch/create-story-investigate-{repo-name}/` — an absolute path outside the current working directory's subtree, matching this plugin's existing convention for session/runtime state kept outside any repo checkout (`~/.claude/dev-workflow/state/`, `~/.claude/dev-workflow/epics/`) and unreachable by `shared/repo-discovery.md`'s Path 2 glob. Bound the clone: `--depth 1 --single-branch --filter=blob:none`. Never embed a token in the remote URL — use `gh repo clone` (which authenticates via the `gh` credential helper) rather than constructing a URL with a credential in it. This clone is investigative reference material only — never a repo root, and never added to `reposToModify` or the discovered-repo set from step 2.
   - Read the relevant files in that clone directly before treating any of its architectural details, tech stack, or conventions as inferred or unknown.
   - **Cleanup is unconditional — on success, failure, or abort** (including a user abort at the Phase 5 approval gate) — delete the scratch clone directory at that exact validated path before this step's own trigger point finishes (see the timing rule in the next bullet). Never leave a private-repo working tree behind.
   - If Phase 0 discovered zero repos in step 2, that is not an error state for this step — existing step 8 below already treats zero local repos as an expected, non-fatal outcome. If zero repos were discovered, simply ask the user which org or git host to search.
   - **Exactly one of two trigger points fires per run, and cleanup happens at that same trigger point:** if `$ARGUMENTS` is non-empty, this step runs here at Phase 0 and the clone must be deleted before this Phase 0 step (step 3) completes. If `$ARGUMENTS` is empty, this step is deferred, not skipped, to Phase 3 (see the pointer at the start of Phase 3) — it runs there against the Phase 1 description, and the clone must be deleted before that Phase 3 re-run of this step completes, never before Phase 0 (Phase 0 has already ended by the time the deferred run executes).
4. For each repo found, determine the **service name** per `skills/shared/repo-discovery.md` (identical to folder/repo name, e.g. `/workspace/my-service` → `my-service`)
5. For each repo, read `CLAUDE.md` from the repo root:
   - If `CLAUDE.md` exists: extract the service purpose — look for a `## Project Overview` section first; if absent, use the first substantive paragraph (skip headings and blank lines)
   - If `CLAUDE.md` is absent: note a warning — "⚠️ No CLAUDE.md found for {service-name} — skipping context for this service" — and continue
6. Store each discovered service as in-session context with the structure:
   - **service name**: the folder/repo name (identical)
   - **purpose**: extracted from CLAUDE.md as described above
   - **claude_md_path**: absolute path to the CLAUDE.md file
7. Compile service briefs for use in the interview:
   ```
   **{service-name}** ({claude_md_path}):
   {purpose}
   ```
   Services without a CLAUDE.md are omitted from the briefs.
8. If no repos found: note this — Phase 3 will prompt the user for context if a target repo cannot be inferred

---

## Phase 1: Gather Story Description

- If `$ARGUMENTS` is non-empty: use it as the story description and proceed to Phase 2
- If `$ARGUMENTS` is empty: use `AskUserQuestion` to ask —
  > "What story would you like to create?"
  Then use the answer as the story description and proceed to Phase 2

---

## Phase 2: Load Adapters

1. Read `~/.claude/dev-workflow/config.json`
2. Note the `pm_adapter` value
3. Load PM adapter per procedure in `skills/shared/adapter-loading.md`
4. Confirm the adapter implements **Create Story** (capability #5) by checking for a `## Create Story` heading in the loaded adapter file. If not found: STOP — "This PM adapter does not support Create Story. Please update ~/.claude/skills/pm-adapter/{name}.md with a Create Story section."
5. Check whether the loaded adapter has pre-flight requirements (e.g., Linear requires `teamId`, Jira requires `PROJECT_KEY` if not yet established in session). Surface any such requirements to the user **before** starting the interview in Phase 3, so they don't interrupt Phase 6.

---

## Phase 3: Autonomous Field Population (Max 2 Questions)

If Phase 0's git-host search step (step 3) deferred to this point because `$ARGUMENTS` was empty, run it now against the Phase 1 description before inferring any field below — including that step's validation, unconditional cleanup, and the requirement that the scratch clone be deleted before this Phase 3 re-run of the step completes (not before Phase 0, which has already ended).

Using the service briefs from Phase 0 and the story description from Phase 1, attempt to populate all story draft fields:

- `title`: derive from the starter prompt — **never ask**
- `originalRequest`: verbatim user starter prompt — **never ask**
- `description`: summarize from starter prompt; explore codebase for context if vague — ask only if the request is genuinely too vague to understand after investigation
- `reposToModify`: a LIST of the discovered repos the feature actually touches (drawn from Phase 0 discovery) — explore code if unclear; ask only if no repo clearly fits after investigation and there are no repos. When the story spans more than one repo, tag each inferred acceptance-criteria and testing-instruction item with its repo marker (e.g. `[api]`, `[web]`) and per-environment tags per the "Multi-environment stories" subsection below, when multiple environments are in scope
- `reposToReference`: infer from repo briefs (repos that provide context without being modified) — **never ask**
- `acceptanceCriteria`: derive from repo patterns, existing tests, and feature description — **never ask** (infer up to 5 items; label uncertain ones `[Inference]`; apply per-repo tags when multiple repos are in scope, and per-environment tags per the "Multi-environment stories" subsection below, when multiple environments are in scope). Each item describes what must be true and how it will be verified, not a finished implementation — no code blocks, full scripts, or function bodies. **Live infra/deployment-state carve-out:** before inferring or asserting an acceptance criterion that states a live, tool-checkable infrastructure or deployment fact (e.g. an SSM parameter's existence, a Kubernetes rollout's status, a running service's health), perform the actual tool check and state the verified result in the criterion — bounded by all of the following. **Read-only only:** the check must be a read/describe/get-style call (e.g. `aws ssm get-parameter`, `kubectl rollout status`); never run a mutating command (create, update, delete, apply, restart, scale, etc.) to perform the check. **Never against production:** run the check only against a non-production environment/context; if the only reachable credentials or cluster context are production, treat the check as unavailable rather than run it. **State existence/status only, never the value:** the criterion records only that the fact holds (e.g. "the `db-password` SSM parameter exists," "the `web` deployment's rollout is healthy") — never the retrieved value itself, omitting any sensitive attribute values (ARNs, account IDs, IP ranges, secret resource references), mirroring the redaction rule `review-pr/SKILL.md` and `start-development/SKILL.md` already apply to infrastructure output. **Fallback when the check can't be run:** with no usable credentials, no cluster/context, or the tool unavailable, do not guess — fall back to `[Inference]` and state in the criterion that the live check was unavailable (e.g. "[Inference] — live SSM check unavailable, no AWS credentials in session"). `[Inference]` remains valid only for details that cannot be settled by an available, in-bounds tool check — it is never a substitute for making a check that is available and permitted.
- `testingInstructions`: derive from repo patterns and existing test conventions — **never ask** (infer up to 3 steps; apply per-repo tags when multiple repos are in scope, and per-environment tags per the "Multi-environment stories" subsection below, when multiple environments are in scope). Each step describes what must be true and how it will be verified, not a finished implementation — no code blocks, full scripts, or function bodies.
- `story_type`: infer from context — "feature" for new capabilities, "bug" for fixes, "chore" for maintenance — **never ask**

Use the `AskUserQuestion` tool only when both of these are true: (1) the answer cannot be inferred from the codebase or context, and (2) getting it wrong would produce a materially misleading story. **Stop asking after 2 questions maximum** — draft regardless of remaining ambiguity, labeling uncertain fields as `[Inference]`.

**Note:** The initial "What story would you like to create?" prompt in Phase 1 does **not** count against the 2-question limit. The limit applies only to clarifying questions asked during Phase 3.

---

## Multi-environment stories

A story spanning multiple environments (e.g. dev and prod) stays a single story — never split into one story per environment. State the environment scope explicitly in the `description` field. Tag each Acceptance Criteria and Testing Instruction item that applies to only some of the in-scope environments with `[dev]` or `[prod]`; an item applying to every in-scope environment is left untagged.

Never tag an item `[all]` for "all environments" — `[all]` is already the *repo*-scope wildcard `write-spec/SKILL.md`'s per-repo filter reads (keeps items tagged `[{repo-name}]`, `[all]`, or untagged); reusing it for environments would make an all-environments, single-repo item (e.g. `[api][all]`) get silently retained in every repo's spec.

Environment tags are independent of repo tags but do not float free of them: in a story that is both multi-repo and multi-environment, every environment-tagged item must also carry a repo tag (`[api]`, `[web]`, etc., or `[all]` if it truly applies to every repo too) — e.g. `[api][prod]`, never a bare `[prod]` — because that same filter would otherwise silently drop an environment-only tag from every repo's spec.

Never create a second story or subtask to represent a different environment for the same change.

---

## Phase 4: Generate Story Draft

Internally hold the draft fields — do NOT emit any JSON or code block. Display only the rendered markdown preview below (no code fences, no JSON):

---
**Title:** {title}

**Description:** {description}

**Repos to modify:** {reposToModify joined with ", "}
**Repos to reference:** {reposToReference joined with ", " or "(none)"}

**Acceptance Criteria:**
- [ ] {ac item 1}
- [ ] {ac item 2}
...

**Testing Instructions:**
1. {step 1}
2. {step 2}
...

---

## Phase 5: Approval

Use `AskUserQuestion` to ask the user. The `question` field **must include the full story draft** (same markdown rendered in Phase 4), followed by the approval prompt. This ensures the story content is visible regardless of how the question is routed or displayed. Format the question as:

```
{full story draft markdown, same as Phase 4 output}

---

Type **yes** to submit this story to {pm_adapter}, or describe what to change.
```

- If user says "yes" (case-insensitive): proceed to Phase 6
- If user asks a question that does not itself imply a desired change: answer the question directly, using the same codebase/context investigation Phase 3 already permits, scoped to codebase/context reads only — this does **not** extend to Phase 3's live infra/deployment-state carve-out; a Phase 5 question never triggers a live SSM/Kubernetes/service-health check. Then re-present the draft with the same approval prompt: re-present it identical and unmodified, unless answering the question revealed the draft itself is factually wrong, in which case re-present a corrected draft instead of knowingly re-presenting an incorrect one, and state what changed and why. This does not count as a revision cycle — do not increment the 3-revision-cycle counter used by the feedback branch below. **Tie-break:** if the question itself implies a desired change (e.g. it reads as "why isn't this scoped to X" where the intent is "scope this to X"), treat it as feedback under the branch below instead, even though it is phrased as a question.
- If user provides feedback (including a question found, per the tie-break above, to imply a desired change): incorporate the feedback, return to Phase 4 and re-emit an updated draft. After 3 revision cycles without approval, suggest the user cancel and restart with a clearer description.
- If user says "stop", "quit", "cancel", or "exit": STOP — "Story creation cancelled."

---

## Phase 6: Create Story

Use the PM adapter's **Create Story** operation (capability #5) with all draft fields.

On success: display —
```
Story created successfully!
ID: {story-id}
URL: {story-url}
```

On failure: STOP with the error — do not retry silently.
