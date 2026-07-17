# Shared Standards

These rules apply to every dev-workflow skill. Read this file at the start of each session.

---

## Reality Filter

- Never present generated, inferred, speculated, or deduced content as fact
- Label unverified content: [Inference] [Speculation] [Unverified]
- Ask for clarification if information is missing. Do not guess or fill gaps
- If you break this directive, say: "Correction: I previously made an unverified claim."

---

## Communication Standards

- **NO boilerplate** — Never include "Co-Authored by Claude", "Generated with Claude Code", or any AI attribution in commits, PRs, comments, or reports
- Output should read as if written by a human engineer
- Clear, professional, technically focused language

### Writing Style

Read and apply `skills/shared/anti-ai-writing-style.md` — it governs all written output in this session (PR descriptions, review comments, commit messages, reports, user-facing text).

---

## Output Format

Human-readable artifacts that are **written to local files** must be standalone HTML documents — not markdown. This applies to specs, plan files, design docs, mockups, and any report saved locally for a human to open and read.

**Standalone HTML** means each file is a complete document: `<!DOCTYPE html>`, a `<head>` with a `<title>` and minimal embedded `<style>`, and a `<body>` holding the content. The file opens cleanly in a browser on its own. Use the `.html` extension.

**Excluded — keep these as markdown** (markdown is the native format for these surfaces; HTML renders poorly or appears as raw tags):
- GitHub PR descriptions and PR titles
- GitHub review bodies, inline comments, and PR comments
- PM story bodies, descriptions, and comments (Shortcut, Linear, Jira, GitHub Issues)
- Design decision records under `.claude/dev-workflow/design-decisions/` — these are `.md` files (see Design Decisions below)

When a skill shows a mockup to the user, render it as HTML.

---

## Subagent Model Selection

When dispatching subagents via the Agent tool, resolve the model from the user's config and pass it via the `model` parameter on every `Agent()` call.

**Resolution order** for any dispatch:

1. Check `models.stages.<stage-key>` in `~/.claude/dev-workflow/config.json` (for stage-specific overrides used by full-cycle).
2. Check `models.<task-type>` in the same config (for task-type-level overrides).
3. Fall back to the built-in default from the table below.

A missing `models` section, a missing key, or an empty value falls through to the next level — never an error.

**Built-in defaults** (used when config keys are absent):

| Task type | Default model | Examples |
|-----------|---------------|----------|
| Coding / implementation (`implementation`) | `sonnet` | Implementer subagents, TDD cycles, file edits |
| Reasoning / exploration / planning (`reasoning`) | `opus` | Brainstorming, root cause analysis, architecture decisions |
| Review / testing (`review`) | `opus` | Code quality review, spec compliance review, PR review subagents, test scenario design |

These assignments override the generic guidance in `superpowers:subagent-driven-development`. Pass the `model` parameter on every `Agent()` call that dispatches a subagent.

---

## Subagent Dispatch (fresh context per stage)

**Every non-interactive stage runs in its own dispatched subagent — never inline.**
Invoking the `Skill` tool loads that skill's content into the **current** context; it does
**not** spawn a subagent. So an orchestrator that wants a stage to run in a fresh,
isolated context MUST dispatch it with the **Agent tool**, passing a `subagent_type` — it
must never reach for the `Skill` tool itself to run a downstream stage.

This plugin ships dedicated worker agent types in `agents/` so a dispatch cannot silently
collapse into an inline `Skill` call (the `subagent_type` parameter is a hard reference to
a worker, not a prose instruction the model can skim past). Map each stage to its worker:

| Stage / dispatch | `subagent_type` | Default model |
|------------------|-----------------|---------------|
| write-spec (autonomous path only) | `dev-workflow-spec-writer` | `sonnet` |
| start-development | `dev-workflow-developer` | `sonnet` |
| review-pr | `dev-workflow-reviewer` | `opus` |
| test-pr | `dev-workflow-tester` | `opus` |
| address-pr-comments (fix loops) | `dev-workflow-fixer` | `sonnet` |
| entry/resume detection + decision read + PR-number read | `dev-workflow-pr-state-reader` | `sonnet` |
| full-cycle driven per-task by `epic` | `dev-workflow-orchestrator` | inherit |

The `model` parameter on the Agent call **always wins** over the worker's frontmatter
`model:`, so config-driven model resolution (the order above) is preserved — pass the
resolved model on every dispatch. Each worker's body invokes the matching
`dev-workflow:{stage}` skill autonomously, so the stage logic, resumability, and loop
behavior are unchanged; only the dispatch boundary is made explicit.

Interactive stages (create-story, write-spec in the standalone full-cycle path) still run
in the **main agent** so their user-facing gates work — do not dispatch a worker for those.

---

## Subagent Wait Discipline (never go idle)

**Dispatching a subagent is not the end of your turn's work — resolving it is.** An
orchestrator that fires an `Agent` call and then stops, with nothing else queued and no
explicit statement of what happens next, produces a session that looks and behaves as
fully idle. It may eventually be woken by a completion notification, or it may not — a
subagent can die without ever emitting one, and a silent orchestrator has no way to tell
the difference between "still working" and "stuck forever." This section is mandatory for
every dispatch made by `full-cycle`, `epic`, `review-pr`'s perspective fan-out, and any
other skill in this plugin that dispatches subagents.

**Default: dispatch to block, not to background.** The overwhelming majority of dispatches
in this plugin are strictly sequential — the orchestrator cannot take its next action until
that one dispatch returns (read the PR number, read the review decision, decide the next
loop iteration). For that shape, dispatch the subagent so its result comes back within the
same continuous execution — do not fire it into the background and end your turn to wait
for an out-of-band wake event. If your harness's `Agent` tool defaults to a background
dispatch, explicitly request the blocking/synchronous variant (e.g. `run_in_background:
false`, or the harness's equivalent), or immediately follow the dispatch with a blocking
wait on that specific task before doing anything else. The test: if the very next thing you
need to do is read this subagent's result, you must not end the turn before you have it.

**Background dispatch is reserved for genuine concurrency.** Only use a backgrounded,
fire-and-forget dispatch when multiple independent subagents are meant to run at the same
time (`epic`'s per-repo scheduling round in Phase 7, `review-pr`'s six parallel perspective
reviewers). Even then:

- **State what's in flight before you stop.** The turn that dispatches the batch must
  explicitly name every subagent launched (role, target — PR/task/repo) and how completion
  will be detected. Never end a turn on unresolved dispatches with only an implicit
  "waiting" — say so out loud.
- **Never rely on notification delivery alone.** For any batch expected to take more than a
  couple of minutes, arm a bounded, visible fallback re-check (e.g. a scheduled wake-up, or
  polling task status through the harness's own status tool) so a subagent that dies without
  notifying is caught within a bounded time instead of hanging the pipeline forever.
- **The fallback must be visible, never a hidden loop.** "Wait for it to complete" and
  "wait for all N agents to complete" — wherever this plugin's skills say that — means:
  track completion through the harness's own task/agent status mechanism, or through an
  explicitly named, visible watcher. It never means a backgrounded shell loop
  (`while true; do sleep …; done` or equivalent) that produces no output the user can see.
  A user watching the session must always be able to tell that work is actively in
  progress, not silence they have to interrupt to interpret.

**On resume from any wait**, whether from a blocking result or a wake event, immediately
state what came back and what happens next — do not let the session's next visible action
be unrelated to the thing it was just waiting on.

---

## Subagent Nesting (version-dependent)

As of **Claude Code v2.1.172**, a subagent may itself spawn subagents — up to a **fixed
depth of 5** — provided the `Agent` tool is in its `tools` list (omitting `tools` grants
all tools, including `Agent`; explicitly listing `tools` without `Agent` blocks nesting by
design). Only the top-level subagent's summary returns to its caller.

This is what lets `epic → dev-workflow-orchestrator (full-cycle) → per-stage worker` run
each stage in fresh context (depth 3, well under the cap). On builds **older than
v2.1.172**, a dispatched subagent cannot nest, so a worker that would dispatch further
stages instead runs them inline within its own context — still isolated per task, just not
per stage. Workers that must fan out (developer, reviewer, tester, orchestrator) therefore
leave `tools` unrestricted; workers that never fan out (fixer, pr-state-reader) restrict
`tools` and omit `Agent`.

---

## Output Mode Detection

**Determine mode at the start of each session — it governs how you deliver your final response.**

**Interactive mode (default):** The agent can ask the user questions and receive answers. Final response should be human-readable prose, structured naturally for a developer audience.

**Autonomous mode:** Activated when any of the following are true:
- The prompt states the agent is running autonomously or in a pipeline
- The prompt instructs the agent to avoid asking questions unless absolutely necessary
- No tool is available to ask the user questions (e.g. `AskUserQuestion` is absent)

**Autonomous mode final response format — flat JSON key/value string:**

Required keys (omit only if genuinely empty/unknown):
- `service-name` — the service, repo, or project being acted on
- `pm-key` — the PM ticket/story ID (e.g. `sc-1234`, `gh-42`)
- `pr-number` — the GitHub PR number
- `status` — `success` or `error`
- `message` — one-sentence summary of what happened or what went wrong

Then add **up to 3** additional keys for the most valuable inferred context (e.g. `branch`, `test-result`, `spec-path`, `reviewer-decision`). Choose only the highest-signal keys — do not pad.

Example:
```json
{"service-name":"api-gateway","pm-key":"sc-1234","pr-number":"87","status":"success","message":"PR created and story updated.","branch":"feat/sc-1234-rate-limiting","test-result":"all passing"}
```

---

## Bash Command Rules

To avoid triggering unnecessary approval prompts:

- **No shell variable assignments** — Never write `VAR=$(command)` or `VAR=value` at the start of a Bash call. Use each command's output directly in subsequent commands as a literal value.
- **No comments before commands** — Never put `# comment` lines before or inside a Bash call. Remove all inline comments from shell commands.
- **No multi-`$()` compositions** — Never build a single command from multiple `$()` substitutions. Run each sub-command separately and use its literal output value.
- **One operation per call** — Each distinct shell operation should be its own Bash tool call.
- **No Bash-invoked inline Python** — Never run Python through Bash as an inline snippet (`python -c "..."`, `python3 <<'EOF'` heredocs, or piping a script into the interpreter). These trigger an approval prompt and are only permitted when the session is running in dangerously-skipped-permissions mode. To process or transform data, use the sandboxed context-mode `ctx_execute` MCP tool (no approval required) or commit a real `.py` script file and run it. This ban is about *inline* Python passed to Bash — not the MCP sandbox.

---

## Script Logging

**Every script you write — in any language (shell, Python, Go, Node, Ruby, etc.) — must log its progress so a human watching the output can tell where execution is and confirm the script is making forward progress, not silently hung.**

- **Log at every significant step** — Before each meaningful operation (setup, a network/API call, a long loop, a build, a migration, cleanup), emit a log line stating what is about to happen. After it completes, log the result. Silence between steps reads as a hang.
- **Make logs informative** — Include the step name, relevant identifiers (file, host, record count, iteration `N/total`), and outcome. Avoid bare `echo "done"` / `print("done")` with no context.
- **Surface progress in long-running work** — In loops or batch operations, log progress periodically (e.g. `Processing 40/200…`) so a stalled iteration is distinguishable from a slow-but-working one.
- **Flush logs immediately — never let them buffer until the script ends.** Many runtimes buffer stdout/stderr (especially when output is piped, not a TTY), so progress lines pile up and dump all at once at exit — which defeats the entire purpose and makes a working script look hung. Force line-buffered or unbuffered output and flush after each significant log:
  - **Python** — run with `python -u`, or set `PYTHONUNBUFFERED=1`, or `print(..., flush=True)`, or `logging` configured to a stream handler.
  - **Go** — `os.Stderr`/`os.Stdout` writes are unbuffered; if you wrap them in a `bufio.Writer`, call `Flush()` after each log.
  - **Node** — `console.error`/`console.log` to a TTY flush per call; when piping, prefer `process.stderr.write` and avoid buffering your own writes.
  - **Shell** — `echo`/`printf` are unbuffered, but wrap downstream pipelines in `stdbuf -oL -eL` (or the tool's own unbuffered flag) when they buffer.
- **Log to stderr for diagnostics** — Send progress/status lines to stderr so they don't pollute a script's real stdout output that may be piped or captured.
- **Timestamp long-running scripts** — For scripts that run more than a few seconds, prefix log lines with a timestamp so elapsed time between steps is visible.
- **Log failures loudly** — On error, log the failing step, the operation, and the exit code or error message before exiting. Never fail silently.

The goal: anyone tailing the output can answer "what is it doing right now, and is it stuck?" at any moment — in real time, not after the script finishes.

---

## File and Command Operations

- **Use Write tool for files** — Never use `cat` or `echo` with redirection to write files
- **Stay within repository** — Do not `cd` outside the repository directory

---

## Autonomy First

Before asking the user ANYTHING, exhaust all available tools. Read relevant files thoroughly, explore the codebase with Glob/Grep, check git history, read existing tests and documentation. Make your best informed decision and label it `[Inference]` if uncertain.

Questions are a last resort — only ask when **all** of these are true:
- The answer cannot be found by reading the codebase, docs, or git history
- Getting it wrong would produce a materially misleading result or require substantial rework
- The decision is genuinely high-stakes (significantly impacts scope, architecture, or correctness)

---

## Scope Discipline

**Do exactly what was asked. Nothing more.**

- Implement only the requirements explicitly stated in the story, spec, or user request
- Do not add features, improvements, refactorings, or "nice-to-haves" that were not requested
- Do not surface "implicit requirements" and treat them as work items — if something truly seems missing, flag it as an `[Open Question]` for the user to decide, do not include it in the deliverable
- "Targeted improvements" to surrounding code are out of scope unless the user specifically requested them
- Brainstorming should identify risks and ambiguities in the *stated* requirements — not generate new requirements or expand what was asked for
- If you discover something that arguably "should" be done but wasn't requested: note it briefly to the user at the end. Do not act on it

**The test:** Before including any work item, ask: "Did the user or story explicitly ask for this?" If the answer is no, leave it out.

---

## Process Fidelity (no undocumented deviation)

**Skipping, reordering, weakening, or ignoring any documented step, gate, or standard requires the user's explicit permission FIRST.**

- **What this covers** — Skipping any documented step, reordering the documented stage sequence, weakening or bypassing any documented gate (User Approval Gate, CI gate, deploy gate, Loop Safety Guard, Story Creation Gate), and ignoring any standard in this file or in a skill's own SKILL.md
- **Ask first, every time** — Before any such deviation, STOP and ask the user for explicit permission, stating exactly what would be skipped, reordered, or ignored and why. Proceed only on an explicit yes. This holds even when the deviation looks obviously safe, faster, or redundant in the moment — "this step seems unnecessary here" is precisely the judgment this rule removes
- **Autonomous contexts never deviate** — An agent with no ability to ask (autonomous mode, dispatched subagent) must NEVER deviate. Stop and report what would need to be skipped and why — mirroring how the Story Creation Gate handles story creation in autonomous contexts
- **Hard-fail rules have no override path** — Some documented rules are deterministic and non-negotiable; asking the user is not a way around them:
  - The **CI gate** default and the **deploy gate** default each have exactly one documented exception: their own config-driven exemption list (`ci_gate_exempt_repos` for CI, `deploy_gate_exempt_repos` for deploy — two separate lists, neither a judgment call). For these gates, "ask first" means stopping to flag that the agent was about to treat a non-exempt repo as exempt, override a failing/missing gate result, or otherwise deviate from the documented hard-fail logic. A user's "yes" there authorizes reporting the situation or updating the exemption config — never recording a passing verdict the gate did not actually produce
  - The **Loop Safety Guard**'s stop-after-3 cycle cap has NO exemption list and NO override path of any kind, documented or otherwise — it is unconditional. "Ask first" for it means stopping to report that the cycle cap was reached, exactly as already documented

The Story Creation Gate below is a specific instance of this rule; where the two overlap, the more specific gate's wording governs.

---

## Story Creation Gate

**A PM story, ticket, issue, or subtask may ONLY be created when the user explicitly invoked `create-story` or `full-cycle`.**

- **Explicit invocation only** — Story creation is permitted only when the user explicitly invoked the `create-story` skill (slash command or a direct, unambiguous request to create a story/ticket) or explicitly invoked `full-cycle` (whose pipeline legitimately begins at create-story)
- **Permission ask everywhere else** — In any other context — including when `create-story` was auto-triggered by a conversational phrase, or when any other skill believes a story is needed — ask the user for explicit permission FIRST, before any interviewing, drafting, or adapter calls. Only an explicit yes proceeds
- **Autonomous contexts never create** — An agent with no ability to ask (autonomous mode, dispatched subagent) must NEVER create a story under any circumstances. Stop and report that a story would be needed, naming what it wanted to create
- **Applies to every creation path** — The gate covers stories, tickets, issues, and subtasks, created via ANY mechanism: adapter instructions, direct MCP tools, CLI commands (`gh issue create`, `jira issue create`), or raw API calls

Reading, updating, commenting on, and labeling existing stories are unaffected — the gate restricts creation only.

---

## Testing Standards

**Write only real, functional, relevant tests.** A test must exercise actual behavior and be capable of failing when that behavior breaks.

- **No useless tests** — Do not write tests that assert against a value that can never change. Examples of useless tests: asserting a mock returns the value it was configured to return, asserting a constant equals itself, asserting a getter returns the field it was just set with. These pass regardless of whether the real code works and provide no signal.
- **What a useful test looks like** — It feeds real input through the unit under test and asserts on the produced output. Example: a function takes a string, parses/converts it, and returns a list — the test passes a representative string and asserts the exact list it should produce, including edge cases (empty, malformed, boundary values).
- **Mocks are for isolating dependencies, not for being the assertion target** — Mock external systems to control inputs, then assert on what *your* code does with them. Never let the assertion reduce to "the mock equals the mock."
- **Mandatory "why" comment** — Every test must open with a comment stating *why* the test exists and what it protects — the behavior or regression it guards. State the value, not a restatement of the test name.

  ```
  # Why: parseTags must split a comma-delimited string into a trimmed list so that
  # downstream filtering matches tags regardless of user spacing. Guards the empty-string
  # case which previously produced a [""] phantom tag.
  ```

This standard governs tests written in target repositories during development — it does not relax the rule that tests must never be skipped, ignored, deleted, or commented out to make a suite pass.

---

## Code Comments

Comments are short and succinct, the way a working developer writes them. Comment the end result — what the code does — not the reasoning for how you arrived at it.

- **No reasoning comments** — Do not narrate your thought process, alternatives you rejected, or why you chose an approach. The code is the deliverable; the path you took to it is not.
- **Succinct** — A few words on intent or a non-obvious effect. If the code is self-explanatory, add no comment.
- **Exception — tests** — The mandatory "why" comment on every test (see Testing Standards above) is **required** and stands apart from this rule. A test's reason for existing is the one place reasoning belongs in code.
- **No ticket/story references** — Never cite the PM ticket or story ID inline in a code comment (e.g. `(sc-33)`), including in test "why" comments. That reference belongs in the commit message and PR description — not in source that outlives the ticket.

---

## Design Decisions

A target repository may record architectural and design decisions as markdown files under `.claude/dev-workflow/design-decisions/` (any depth — `.claude/dev-workflow/design-decisions/**/*.md`). These are durable, agreed-upon decisions. Treat them as authoritative constraints.

- **Respect existing decisions** — Before changing behavior in an area covered by a design decision record, read the relevant record(s) and follow them. They override your default judgment.
- **Never overwrite without permission** — Do not modify or replace an existing `.claude/dev-workflow/design-decisions/**/*.md` file without first asking the user and getting explicit approval. If a new decision contradicts a recorded one, surface the conflict and let the user decide.
- **Record decisions made together** — When you and the user reach a non-trivial design decision during a session, write it to `.claude/dev-workflow/design-decisions/` as a new markdown file named for the functionality it governs (e.g. `inline-python-execution.md`, `tag-parsing-format.md`). Use kebab-case. Capture: the decision, the rationale, alternatives considered, and the date.
- These records are markdown, **excluded** from the HTML Output Format rule above.

---

## Activate Terse Mode

After reading this file, immediately invoke:

> Invoke Skill: `caveman:caveman`

If the invocation fails for any reason (plugin not installed, skill not found, or any other error), silently continue — this is a non-blocking enhancement.

---

## Problem Solving

- Never give up. If stuck, ask for help.
- If unable to access a screenshot, mockup, or attachment referenced in requirements — STOP and ask the user. Do not proceed with incomplete data.
