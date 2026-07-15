# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**dev-workflow** is a Claude plugin (v2.22.0) that provides action-based development workflow orchestration with pluggable PM and notes adapters. It enables specialized workflows (Start Development, Story to Spec, Review PR, Test PR, Start Debugging, Create Story, Full Cycle) through structured, quality-gated stages.

**Dependency:** Requires the `superpowers` plugin to be installed — it provides core methodology skills (TDD, debugging, brainstorming, subagent orchestration, verification).

## Architecture

### Role Dispatcher Pattern

Skills are invoked directly by name:

| Command | Skill | Purpose |
|---------|-------|---------|
| `/start start-development [story-id]` | `dev-workflow:start-development` | Feature implementation with TDD |
| `/start write-spec story-id` | `dev-workflow:write-spec` | Story → Claude Instructions spec |
| `/start review-pr PR-number` | `dev-workflow:review-pr` | Multi-perspective PR review |
| `/start test-pr PR-number` | `dev-workflow:test-pr` | Functional testing with evidence |
| `/start start-debugging` | `dev-workflow:start-debugging` | Bug investigation |
| `/start start-debugging story-id --rework` | `dev-workflow:start-debugging` (rework mode) | Address review feedback |
| `/start create-story` | `dev-workflow:create-story` | Interview user → draft → submit story |
| `/start full-cycle [story-id\|description]` | `dev-workflow:full-cycle` | End-to-end lifecycle orchestrator looping review/test until pass |
| `/start epic [summary\|epic-slug]` | `dev-workflow:epic` | Decompose a large initiative into a self-managed tasklist, then autonomously drive each task to a review- and test-approved open PR, pausing for a human to merge |

### Adapter System

PM and notes integrations are **pluggable adapters** with a common interface defined in `skills/pm-adapter/interface.md` and `skills/notes-adapter/interface.md`.

**PM Adapters** (`skills/pm-adapter/`): Shortcut, Linear, Jira, GitHub Issues, Tasklist (file-backed, used by the `epic` orchestrator — no external PM tool)
**Notes Adapters** (`skills/notes-adapter/`): Local filesystem (`docs/specs/`), Obsidian vault

**Override mechanism:** User-provided adapters at `~/.claude/skills/pm-adapter/{name}.md` or `~/.claude/skills/notes-adapter/{name}.md` take precedence over built-in adapters.

### Superpowers Integration

Skills invoke superpowers throughout their workflows:
- `superpowers:writing-plans` — Implementation task structuring
- `superpowers:test-driven-development` — RED-GREEN-REFACTOR cycles
- `superpowers:brainstorming` — Requirement discovery and edge cases
- `superpowers:systematic-debugging` — Root cause analysis
- `superpowers:subagent-driven-development` — Parallel task execution
- `superpowers:requesting-code-review` / `superpowers:receiving-code-review` — Review workflows
- `superpowers:verification-before-completion` — 5-phase verification gate

## Key Design Decisions

- **review-pr skill has two modes:** First Review (exhaustive 4-perspective analysis) vs. Re-Review (verify previous `CHANGES_REQUESTED` items were addressed, new findings only if they meet the Critical Exception Threshold)
- **start-debugging skill is a unified 3-mode skill:** Debug mode (no args), Development mode (story-id), Rework mode (story-id + `--rework`)
- **epic skill is an orchestrator-only initiative driver:** deep discovery → one up-front consensus gate → self-managed `tasklist.md` (Mermaid graph + embedded per-task description/status) at `~/.claude/dev-workflow/epics/[epic-slug]/` → autonomous scheduler (cross-repo concurrent, same-repo sequential, one in-flight PR per repo, no worktrees) driving each task through `full-cycle` pinned to the `tasklist` adapter. On reviewer+tester dual approval it does **not** merge — it marks the task `awaiting-merge`, tracks the open PR, and pauses that line of work for a human to merge; a later resume detects the human merge and advances the task to done (unblocking dependents). Epic PRs carry **no** `sc-` ID (documented exception). Bug intake: a subagent *reports* a defect from a prior task; the *orchestrator* appends a priority-scheduled `bug` task. Resumable from `tasklist.md`.
- **tasklist PM adapter is file-backed, not config-selected:** the `epic` orchestrator pins it per dispatch (supplying the tasklist path + task ID in the subagent prompt) rather than mutating global `config.json`. It implements the full pm-adapter interface against `tasklist.md` so `full-cycle` and the stage skills run unchanged.
- **Stage isolation via dedicated subagent types:** the orchestrators (`full-cycle`, `epic`) run every non-interactive stage in a fresh, isolated context by **dispatching the Agent tool** with a stage-specific `subagent_type` from `agents/` — never by invoking the `Skill` tool themselves (a `Skill` call loads into the *current* context, which is what made stages run in one agent). Each worker's body invokes the matching `dev-workflow:{stage}` skill autonomously, so stage logic/resumability/loops are unchanged; the `model` parameter on the dispatch overrides the worker's frontmatter default, preserving config-driven model resolution. See `skills/shared/standards.md` → "Subagent Dispatch". Workers that fan out (developer/reviewer/tester/orchestrator) keep the `Agent` tool; `fixer` and `pr-state-reader` are tool-restricted.
- **Subagent nesting (Claude Code v2.1.172+):** a subagent may nest further subagents (fixed depth-5 cap) when it has the `Agent` tool. This is what lets `epic → dev-workflow-orchestrator (full-cycle) → per-stage worker` give each stage fresh context (depth 3). On builds older than v2.1.172, nesting is unavailable and a task's stages run inline within its worker — isolated per task, not per stage. See `skills/shared/standards.md` → "Subagent Nesting".
- **Reality Filter:** All skills enforce labeling unverified content as `[Inference]`, `[Speculation]`, or `[Unverified]`
- **Config location:** User configuration lives at `~/.claude/dev-workflow/config.json`, not in the repo

## File Layout

```
skills/
  start-development/   # Full development workflow (TDD, subagents, PR)
  write-spec/          # Story → Claude Instructions spec transformation
    spec-template.html # Standalone HTML document shell for generated specs
  review-pr/           # Multi-perspective PR review with mode detection
  test-pr/             # Evidence-based functional testing
  start-debugging/     # Debug/dev/rework unified skill
  create-story/        # Interactive interview → PM story creation
  full-cycle/          # End-to-end lifecycle orchestrator (sequences all stages)
  epic/                # Initiative orchestrator: discovery → consensus → self-managed tasklist → autonomous per-task full-cycle drive
  address-pr-comments/ # Address review feedback in current session
  pm-adapter/          # PM tool adapters + interface spec (includes file-backed tasklist adapter)
  notes-adapter/       # Notes storage adapters + interface spec
  shared/              # Shared protocol docs (standards, adapter-loading, context-compaction, ...)
agents/                # Dedicated subagent types dispatched by the orchestrators (one per pipeline role)
  dev-workflow-spec-writer.md      # write-spec (autonomous path only)
  dev-workflow-developer.md        # start-development
  dev-workflow-reviewer.md         # review-pr
  dev-workflow-tester.md           # test-pr
  dev-workflow-fixer.md            # address-pr-comments (review/test fix loops; tool-restricted)
  dev-workflow-pr-state-reader.md  # entry/resume detection + PR-number resolution + authoritative decision read (read-only)
  dev-workflow-orchestrator.md     # full-cycle, dispatched per-task by epic (retains Agent tool to nest)
hooks/
  context-meter.sh     # PostToolUse: token usage meter — emits at 60%/75% of 200k baseline
  compact-injector.sh  # Stop: consumes .compact-request sentinel and injects /compact via tmux
  hooks.json           # Hook registration (CLAUDE_PLUGIN_ROOT-relative paths)
.claude-plugin/        # Plugin manifest (plugin.json)
```

Runtime state (not committed): `~/.claude/dev-workflow/state/`
- `{story-id}.json` — per-story checkpoint (stage, PR numbers, loop counts, next action)

Epic state (not committed): `~/.claude/dev-workflow/epics/[epic-slug]/`
- `tasklist.md` — the epic's single source of truth: Mermaid dependency graph + embedded per-task description/AC/testing/status. Doubles as durable cross-task resume state.
- `.compact-request` — sentinel written by full-cycle at a high-context handoff (inside tmux only)
- `.compact-request.failed` — written by compact-injector on injection failure
- `context-meter-tier.txt` — last announced meter tier (prevents repeat emissions)

## Working on This Codebase

Content is mostly Markdown skill definitions, plus a small number of static assets (e.g., `skills/write-spec/spec-template.html`) — there is no compiled code, no tests to run, and no build step. Changes are made by editing `.md` files (and the occasional asset file) in `skills/` and `commands/`.

When modifying a skill:
- Update the version in `.claude-plugin/plugin.json` if changing behavior, **and** bump the matching entry's `version` in the repo-root `.claude-plugin/marketplace.json` to the same value — the two drift independently and only the second one is what marketplace consumers actually see
- Maintain phase numbering consistency within skills (phases are referenced by number in other skills and documentation)
- Preserve the adapter interface contracts in `interface.md` files — adapters must implement all required operations
- Test skill changes by invoking them with `/start <role>` in a target repository
