# Claude Quest

A collection of Claude Code plugins for software development teams.

Each plugin is independently installable and addresses a single concern. Install only what you need.

---

## Plugins

### [claude-plugin-guardrails](https://github.com/MechanicalTyler/claude-plugin-guardrails)

Pre-tool-use safety hooks that prevent common mistakes.

- Blocks commits and branch creation from `main`
- Blocks `--no-verify` flag on commits
- Blocks AI attribution boilerplate in commit messages and PR bodies
- Blocks `rm -rf` with broad wildcards
- Blocks `/tmp` directory usage (enforces `.scratch/tmp/`)
- Blocks `cd` outside the repo directory
- Automatically adds timeouts to `git commit`, `git push`, `docker build`, `gh run watch`

```json
"": { "path": "/path/to/claude-plugin-guardrails" }
```

---

### [claude-plugin-notifications](https://github.com/MechanicalTyler/claude-plugin-notifications)

System notifications when Claude completes tasks or needs your attention.

- macOS notification when Claude asks a question (`AskUserQuestion`)
- macOS + Slack notification when a task completes (`Stop` hook)
- Slack-only notification when a subagent finishes (`SubagentStop` hook)

```json
"": { "path": "/path/to/claude-plugin-notifications" }
```

---

### [claude-plugin-audit-trail](https://github.com/MechanicalTyler/claude-plugin-audit-trail)

Logs every tool call — input before execution, full event after — to JSON files in `~/.claude/logs/`.

- `pre_tool_use.json` — tool name and input for every call
- `post_tool_use.json` — complete event including tool response
- `subagent_spawns.log` — records every `Task` tool invocation

Useful for debugging, auditing, and building on top of Claude's activity.

```json
"": { "path": "/path/to/claude-plugin-audit-trail" }
```

---

### [claude-plugin-dev-workflow](https://github.com/MechanicalTyler/claude-plugin-dev-workflow)

Role-based development workflow with pluggable PM and notes adapters.

Provides five subagents invoked via `/start <role>`:

| Role | Command | What it does |
|------|---------|-------------|
| `developer` | `/start developer [story-id]` | Branch, TDD, implement, commit, PR |
| `writer` | `/start writer <story-id>` | Fetch story → multi-perspective analysis → write spec |
| `reviewer` | `/start reviewer <pr-number>` | PM/Dev/QA/Architect review → formal GitHub review |
| `tester` | `/start tester <pr-number>` | Deploy → test → evidence report → GitHub review |
| `debugger` | `/start debugger` | Systematic debug with hypothesis and failing test first |

**PM adapters:** Shortcut, Linear, GitHub Issues
**Notes adapters:** Obsidian vault, local filesystem

Configure via `~/.claude/dev-workflow/config.json`:

```json
{
  "pm_adapter": "shortcut",
  "notes_adapter": "obsidian",
  "adapters": {
    "obsidian": {
      "vault_path": "/path/to/your/vault",
      "prompts_dir": "Engineering/Prompts"
    }
  },
  "deploy_command": "kubectl rollout restart deployment/my-app -n my-namespace"
}
```

```json
"": { "path": "/path/to/claude-plugin-dev-workflow" }
```

---

### [](https://github.com/MechanicalTyler/)

Enforces role-based GitHub App authentication. Blocks personal tokens and direct `git`/`gh` commands, requiring wrapper scripts that authenticate as the correct bot identity per role.

**Requires:** `claude-plugin-dev-workflow`

```json
"@local": { "path": "/path/to/" }
```

---

## Installation

Add plugins to the `enabledPlugins` section of your `~/.claude/settings.json`:

```json
{
  "enabledPlugins": {
    "": { "path": "/Users/you/projects/claude-plugin-guardrails" },
    "": { "path": "/Users/you/projects/claude-plugin-notifications" },
    "": { "path": "/Users/you/projects/claude-plugin-audit-trail" },
    "": { "path": "/Users/you/projects/claude-plugin-dev-workflow" }
  }
}
```

Restart Claude Code after updating `settings.json`.

## Recommended combinations

**Minimal safety:** `guardrails`
**Active development:** `guardrails` + `dev-workflow` + `notifications`
**Full audit:** all four public plugins
**With GitHub App personas:** add `git-personas` (requires bot setup)

---

## What's a Claude Code plugin?

Claude Code plugins extend Claude's behavior with hooks, subagents, commands, and skills. A plugin is a directory containing a `manifest.json` and the referenced files. See the [Claude Code documentation](https://docs.anthropic.com/claude/claude-code) for details.
