# claude-quest

A marketplace of Claude Code plugins for software development teams.

## Plugins

| Plugin | Description |
|--------|-------------|
| [guardrails-git](https://github.com/MechanicalTyler/claude-plugin-guardrails-git) | Git/GitHub safety: branch protection, boilerplate blocking, timeout enforcement |
| [guardrails-bash](https://github.com/MechanicalTyler/claude-plugin-guardrails-bash) | Shell safety: blocks `rm -rf`, `/tmp`, `cat`/`echo` file writes, `cd` outside repo |
| [guardrails-docker](https://github.com/MechanicalTyler/claude-plugin-guardrails-docker) | Enforces timeout on `docker build` |
| [guardrails-xcode](https://github.com/MechanicalTyler/claude-plugin-guardrails-xcode) | Enforces timeout on `xcodebuild` |
| [notifications](https://github.com/MechanicalTyler/claude-plugin-notifications) | macOS notifications when Claude completes tasks or needs attention |
| [audit-trail](https://github.com/MechanicalTyler/claude-plugin-audit-trail) | Logs every tool call to `~/.claude/logs/` for debugging and auditing |
| [dev-workflow](https://github.com/MechanicalTyler/claude-plugin-dev-workflow) | Role-based development subagents with pluggable PM and notes adapters |

## Installation

```
/plugin marketplace add MechanicalTyler/claude-quest
/plugin install <plugin-name>@claude-quest
```
