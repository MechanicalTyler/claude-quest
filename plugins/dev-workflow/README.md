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
| `/start developing [story-id]` | developing | Branch, implement with TDD, commit, create PR |
| `/start writing-specs story-id` | writing-specs | Fetch story → analyze codebase → write Claude Instructions spec |
| `/start reviewing-prs PR` | reviewing-prs | Multi-perspective PR review against story requirements |
| `/start testing-prs PR` | testing-prs | Functional testing with evidence gathering |
| `/start debugging` | debugging | Debug-first workflow (describe bug → investigate → TDD fix) |
| `/start debugging story-id --rework` | debugging | Read story comments as rework items → fix → new PR |
| `/start creating-stories` | creating-stories | Interview user → draft story → submit to PM tool |
| `/start full-cycle [story-id\|description]` | full-cycle | Drive the whole lifecycle end to end: creating-stories → writing-specs → developing → reviewing-prs → testing-prs, looping until tests pass |

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
      "developing": "sonnet",
      "reviewing-prs": "opus",
      "testing-prs": "opus",
      "addressing-pr-comments": "sonnet",
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
| `models.stages.writing-specs` | `sonnet` | full-cycle's writing-specs stage subagent (autonomous path only) |
| `models.stages.developing` | `sonnet` | full-cycle's developing stage subagent |
| `models.stages.reviewing-prs` | `opus` | full-cycle's reviewing-prs stage subagent |
| `models.stages.testing-prs` | `opus` | full-cycle's testing-prs stage subagent |
| `models.stages.addressing-pr-comments` | `sonnet` | full-cycle's fix subagent in the review and test loops |
| `models.stages.entry-detection` | `sonnet` | full-cycle's resume/entry-detection subagent |
| `models.stages.pr-number-read` | `sonnet` | full-cycle's post-developing PR-number resolution subagent |
| `models.stages.decision-read` | `sonnet` | full-cycle's authoritative review/test decision-read subagent |

**Resolution order** for any dispatch: `models.stages.<stage-key>` → `models.<task-type>` → built-in default. Stage-level keys take priority over task-type keys. Users who never add the `models` section see no change in behavior.

**Migration note:** the `models.stages.*` keys were renamed to match the sc-1623 skill rename (`write-spec` → `writing-specs`, `start-development` → `developing`, `review-pr` → `reviewing-prs`, `test-pr` → `testing-prs`, `address-pr-comments` → `addressing-pr-comments`). If your `settings.json` has an existing `models.stages.start-development`-style entry under one of these five old names, rename it manually to the new key — the old key silently stops applying (falls through to `models.implementation`/`models.review`/default instead of erroring) rather than failing loudly. `entry-detection`, `pr-number-read`, and `decision-read` are unaffected.

### CI / Deploy Gate Exemptions

Two optional arrays let specific repos opt out of the otherwise-mandatory CI gates. Both default to gated.

| Key | Governs | Effect when a repo is listed |
|-----|---------|------------------------------|
| `ci_gate_exempt_repos` | `reviewing-prs`'s dev build CI gate | The review may APPROVE without a passing dev build CI run. The review body states the gate was skipped by exemption. |
| `deploy_gate_exempt_repos` | `testing-prs`'s dev deploy CI gate | The test may APPROVE without a successful dev deploy CI run. The test report states functional dev testing was skipped by exemption. |

Each is an array of repository names (matching `git rev-parse --show-toplevel | xargs basename`). The two gates are independent — a repo may be exempt from one and not the other.

**Invariant — absence = gated, fallback ≠ exempt:**

- A repo that is **not** listed in the relevant array is **gated**. Exemption requires explicit listing.
- The `review_ci_command` / `deploy_command` `fallback` entry is **not** an exemption — falling back to the fallback instruction still requires the gate to run and pass.
- Absence of a CI/deploy workflow on a non-exempt repo is **not** auto-exempt — it is a `REQUEST_CHANGES` (review) or `REQUEST_CHANGES` + `tests-failing` (test).

A non-passing CI/deploy result on a non-exempt repo always yields `REQUEST_CHANGES`, never `APPROVE`. A local/Makefile/script deploy never satisfies the dev deploy gate — only a successful dev deploy CI run does.

**Exemption claims must show their work.** A skip sentence alone is not enough — the review/test report must also include the literal verification command and its output immediately after the skip sentence, e.g.:

```bash
$ jq '.ci_gate_exempt_repos' ~/.claude/dev-workflow/config.json
["whoof-app", "claude-quest", ...]
```

A missing verification line invalidates the exemption claim and is treated as a gate failure (`REQUEST_CHANGES`), not a pass.

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
