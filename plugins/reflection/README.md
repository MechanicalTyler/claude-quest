# reflection

Passively watches every Claude Code session for moments the agent didn't meet expectations, logs each one to a local file the instant it happens, and offers a `/reflect` skill that turns the accumulated log into a synthesized, root-cause-attributed HTML report.

## What it does

- **SessionStart hook**: injects standing watch-and-log instructions into every session (with or without any other plugin installed). The agent watches for five trigger types and, the moment one occurs, appends an entry to the log — silently, without interrupting the current task or asking permission.
- **`/reflect` skill**: reads the log, catches up on anything from the live conversation or the most recent prior session in the current project that wasn't already captured, groups recurring problems, attributes each to a specific root cause, and writes a self-contained HTML report.

## Trigger types

The hook watches for five kinds of corrective moment:

1. The user corrects a factual claim.
2. The user says "no" / "don't" / "stop doing X".
3. The user has to repeat or rephrase a request.
4. The user pushes back on a proposed approach.
5. The user shows visible frustration or escalation.

## Log file

`~/.claude/reflection/log.md` — created on first trigger. Append-only. Each entry contains:

- ISO-8601 timestamp
- One-line context note (skill / project / cwd, if identifiable)
- Trigger type
- One-line quote or close paraphrase of what the user said

## Reports

`/reflect` writes one HTML report per run to `~/.claude/reflection/reports/{ISO-timestamp}.html`, so a history of past syntheses accumulates in one place. Reports are fully self-contained (inline CSS, no external assets, no network calls) and light/dark aware.

Each report groups findings by root cause, and every finding is attributed to either:

- a specific skill file (in any installed plugin) and the exact instruction/section responsible, or
- a specific `CLAUDE.md` (user-global or repo-level) and the rule that's missing or being ignored.

`/reflect` never edits another skill's or plugin's files — it only appends catch-up entries to the log and writes its own report.

## Installation

Add to `~/.claude/settings.json`:

```json
{
  "enabledPlugins": {
    "reflection@local": { "path": "/path/to/reflection" }
  }
}
```

## License

MIT
