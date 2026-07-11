# dev-workflow

Role-based development workflow subagents with pluggable PM and notes adapters.

## Prerequisites

This plugin requires the [superpowers plugin](https://github.com/obra/superpowers) to be installed:

```
/plugin install superpowers@superpowers-marketplace
```

The superpowers plugin provides core methodology skills (TDD, systematic debugging, brainstorming, verification gates, subagent orchestration) that are invoked throughout the dev-workflow skill phases.

## Roles

| Command | Skill | Purpose |
|---------|-------|---------|
| `/start start-development [story-id]` | start-development | Branch, implement with TDD, commit, create PR |
| `/start write-spec story-id` | write-spec | Fetch story → analyze codebase → write Claude Instructions spec |
| `/start review-pr PR` | review-pr | Multi-perspective PR review against story requirements |
| `/start test-pr PR` | test-pr | Functional testing with evidence gathering |
| `/start start-debugging` | start-debugging | Debug-first workflow (describe bug → investigate → TDD fix) |
| `/start start-debugging story-id --rework` | start-debugging | Read story comments as rework items → fix → new PR |
| `/start create-story` | create-story | Interview user → draft story → submit to PM tool |
| `/start full-cycle [story-id\|description]` | full-cycle | Drive the whole lifecycle end to end: create-story → write-spec → start-development → review-pr → test-pr, looping until tests pass |

## Configuration

Create `~/.claude/dev-workflow/config.json`:

```json
{
  "pm_adapter": "shortcut",
  "notes_adapter": "obsidian",
  "adapters": {
    "obsidian": {
      "vault_path": "/path/to/your/vault",
      "prompts_dir": "Engineering/Prompts"
    },
    "local": {
      "specs_path": "docs/specs"
    },
    "shortcut": {
      "story_id_prefix": "sc-"
    }
  },
  "deploy_command": "Run the dev CI workflow in GitHub Actions",
  "ci_gate_exempt_repos": [],
  "deploy_gate_exempt_repos": [],
  "models": {
    "implementation": "sonnet",
    "reasoning": "opus",
    "review": "opus",
    "stages": {
      "start-development": "sonnet",
      "review-pr": "opus",
      "test-pr": "opus",
      "address-pr-comments": "sonnet",
      "entry-detection": "sonnet",
      "pr-number-read": "sonnet",
      "decision-read": "sonnet"
    }
  }
}
```

The `local` notes adapter's `specs_path` is optional. When omitted, specs default to `docs/specs/` relative to the repo root. Set it to a relative path (resolved against the repo root) or an absolute path to store specs elsewhere.

The `models` section is optional. When absent, all dispatches use the built-in defaults shown above. When present, any key you set overrides the default for that task type or stage; unspecified keys fall through to defaults automatically.

**Model key reference:**

| Key | Default | Governs |
|-----|---------|---------|
| `models.implementation` | `sonnet` | All coding/implementation subagents (implementers, TDD cycles) |
| `models.reasoning` | `opus` | All reasoning/planning subagents (brainstorming, architecture) |
| `models.review` | `opus` | All review/testing subagents (review board, adversarial review, test agents) |
| `models.stages.start-development` | `sonnet` | full-cycle's start-development stage subagent |
| `models.stages.review-pr` | `opus` | full-cycle's review-pr stage subagent |
| `models.stages.test-pr` | `opus` | full-cycle's test-pr stage subagent |
| `models.stages.address-pr-comments` | `sonnet` | full-cycle's fix subagent in the review and test loops |
| `models.stages.entry-detection` | `sonnet` | full-cycle's resume/entry-detection subagent |
| `models.stages.pr-number-read` | `sonnet` | full-cycle's post-start-development PR-number resolution subagent |
| `models.stages.decision-read` | `sonnet` | full-cycle's authoritative review/test decision-read subagent |

**Resolution order** for any dispatch: `models.stages.<stage-key>` → `models.<task-type>` → built-in default. Stage-level keys take priority over task-type keys. Users who never add the `models` section see no change in behavior.

### CI / Deploy Gate Exemptions

Two optional arrays let specific repos opt out of the otherwise-mandatory CI gates. Both default to gated.

| Key | Governs | Effect when a repo is listed |
|-----|---------|------------------------------|
| `ci_gate_exempt_repos` | `review-pr`'s dev build CI gate | The review may APPROVE without a passing dev build CI run. The review body states the gate was skipped by exemption. |
| `deploy_gate_exempt_repos` | `test-pr`'s dev deploy CI gate | The test may APPROVE without a successful dev deploy CI run. The test report states functional dev testing was skipped by exemption. |

Each is an array of repository names (matching `git rev-parse --show-toplevel | xargs basename`). The two gates are independent — a repo may be exempt from one and not the other.

**Invariant — absence = gated, fallback ≠ exempt:**

- A repo that is **not** listed in the relevant array is **gated**. Exemption requires explicit listing.
- The `review_ci_command` / `deploy_command` `fallback` entry is **not** an exemption — falling back to the fallback instruction still requires the gate to run and pass.
- Absence of a CI/deploy workflow on a non-exempt repo is **not** auto-exempt — it is a `REQUEST_CHANGES` (review) or `REQUEST_CHANGES` + `tests-failing` (test).

A non-passing CI/deploy result on a non-exempt repo always yields `REQUEST_CHANGES`, never `APPROVE`. A local/Makefile/script deploy never satisfies the dev deploy gate — only a successful dev deploy CI run does.

## Adapters

**PM adapters** (`skills/pm-adapter/`): `shortcut`, `linear`, `github-issues`

**Notes adapters** (`skills/notes-adapter/`): `obsidian`, `local`

## Custom Adapters

You can override any built-in adapter or create a new one by placing a file in `~/.claude/skills/`:

- PM adapters: `~/.claude/skills/pm-adapter/{name}.md`
- Notes adapters: `~/.claude/skills/notes-adapter/{name}.md`

Set the matching name in your config:

```json
{
  "pm_adapter": "my-pm-tool",
  "notes_adapter": "my-notes-tool"
}
```

User adapters in `~/.claude/skills/` take precedence over plugin adapters with the same name. This means you can override a built-in adapter (e.g., create `~/.claude/skills/pm-adapter/shortcut.md` to customize Shortcut behavior) or add support for a new tool entirely.

Your adapter must implement the same interface as built-in adapters — see `skills/pm-adapter/interface.md` or `skills/notes-adapter/interface.md` for the required capabilities.

## Context Compaction (full-cycle only)

Long `full-cycle` runs accumulate context. Version 2.15.0 introduced three mechanisms
to keep compaction lossless and, where possible, automatic:

**Checkpoints** — full-cycle writes `~/.claude/dev-workflow/state/{story-id}.json`
at every stage boundary and loop iteration. On re-invoke, the pipeline re-enters at
the correct stage regardless of when compaction occurred.

**Context meter** — a PostToolUse hook measures token usage against a fixed 200,000-token
baseline. At 60% it advises writing a checkpoint; at 75% it advises compacting at the
next handoff. Set `DEV_WORKFLOW_COMPACT_BASELINE` (tokens) to override the baseline.

**Compact injector** — a Stop hook fires at turn end. If a `.compact-request` sentinel
exists and the session is inside tmux, the hook spawns a detached process that injects
`/compact` into the pane and sends the resume command after compaction completes. Outside
tmux, full-cycle instead tells you the exact two commands to run manually.

Both hooks are registered automatically when the plugin is loaded.

## Installation

```json
{
  "enabledPlugins": {
    "dev-workflow@local": { "path": "/path/to/dev-workflow" }
  }
}
```

## License

MIT
