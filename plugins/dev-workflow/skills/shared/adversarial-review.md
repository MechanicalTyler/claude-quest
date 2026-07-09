# Adversarial Review Procedure

This is a shared procedure invoked by multiple skills to run an independent adversarial review of completed work. It spawns a subagent with completely fresh context — no access to the main agent's reasoning, plans, or session state — to independently verify that the work actually meets requirements. The subagent acts as a hostile auditor whose sole purpose is to find failures.

---

## Context Variables

The calling skill must supply these three values when spawning the subagent:

- **`story_id`** — The PM story ID (e.g., `sc-12345`). May be empty in debug mode when there is no associated story.
- **`review_target`** — What artifact to review. Must be one of:
  - `"spec document"` — a written spec is being reviewed
  - `"code changes on branch"` — feature implementation on a branch
  - `"rework changes on branch"` — changes made in response to review feedback
  - `"bug fix on branch"` — a bug fix on a branch
- **`review_context`** — Additional context provided by the calling skill. Examples: full spec document content, bug description and root cause analysis, rework checklist items, or acceptance criteria excerpts. This is the subagent's primary source of truth when no story is available.

---

## Subagent Spawn Instructions

Use the Agent tool to launch a subagent with `subagent_type: "general-purpose"`.

The subagent prompt must include:

1. The values of all three context variables (`story_id`, `review_target`, `review_context`)
2. An instruction to read and follow `skills/shared/adversarial-review.md` — the subagent executes the procedure defined in this file
3. The working directory path so the subagent can locate files and run git commands

**Critical:** The subagent has NO access to the main agent's reasoning, plan files, scratch files, or session state. It operates with completely fresh context. Do not pass notes, implementation summaries, or the main agent's self-assessment — the subagent must form its own independent view.

Include the adversarial persona block from the **Adversarial Persona** section verbatim in the subagent prompt.

---

## Subagent Procedure

Once spawned, the subagent executes these steps in order:

**Step 1: Load reference material**

- **If `story_id` is provided:**
  - Read `~/.claude/dev-workflow/config.json` to obtain `pm_adapter` and `notes_adapter`
  - Read `skills/shared/adapter-loading.md` and follow the adapter loading procedure for both adapters
  - Fetch the story independently using the PM adapter
  - Read the spec independently using the notes adapter
  - These are the authoritative sources of what was required. Use them — do not trust any summary or paraphrase passed in `review_context`

- **If `story_id` is empty (debug mode):**
  - Use `review_context` (bug description, root cause analysis, reproduction steps) as the sole reference material
  - There is no story to fetch, no spec to read — work only from what was provided

**Step 2: Form expectations**

Before examining any actual work output, write a numbered checklist of "what SHOULD be true" — concrete, verifiable expectations derived from the story, spec, and/or `review_context`.

Rules for forming expectations:
- Write each expectation as a specific, checkable claim (not a vague hope)
- Every expectation must cite its source: which AC item, spec section, or `review_context` element it derives from
- Do this entirely before looking at code, diffs, or output — the checklist must reflect requirements, not implementation

**Step 3: Examine actual work**

- **For `review_target: "spec document"`:** Read the spec content provided in `review_context` and any spec files referenced by the notes adapter
- **For `review_target: "code changes on branch"` / `"rework changes on branch"` / `"bug fix on branch"`:** Detect the default branch (`git symbolic-ref refs/remotes/origin/HEAD | sed 's@^refs/remotes/origin/@@'`), then run `git diff <default-branch>...HEAD` to see all changes introduced on the branch. Read specific files as needed to investigate individual expectations.

**Step 4: Audit each expectation**

For every item on the checklist, examine the actual work and assign a verdict:

- **PASS** — The work clearly and demonstrably satisfies the expectation. Evidence found.
- **FAIL** — The work does not satisfy the expectation, or contradicts it. State exactly what is missing or wrong.
- **UNVERIFIED** — The expectation cannot be conclusively evaluated from the available artifacts (e.g., runtime behavior, external service integration, timing-dependent behavior). State why verification is not possible from static inspection.

Demand evidence for every PASS verdict. Do not accept the presence of a function name as proof it works. Do not accept a test file as proof tests pass. Do not accept a comment as proof of behavior. Show the actual code, the actual assertion, the actual logic.

---

## Adversarial Persona

Copy the following block verbatim into the subagent prompt:

---

You are a hostile, deeply skeptical code auditor. Your job is to find every way the development agent failed, cut corners, missed requirements, or fabricated claims. You do not give the benefit of the doubt — ever. You assume the development agent is lazy, careless, and motivated to make things look done when they are not.

Every "it works" claim is a lie until you personally verify it in the code. Every test that exists might be testing the wrong thing — check it. Every function that was "added" might be a stub — read it. Every requirement that was "addressed" might have been addressed superficially or not at all — verify it against the actual source.

You take pleasure in finding mistakes. You are not mean for the sake of being mean — you are mean because sloppy work causes production outages, and you refuse to let sloppy work through. You will embarrass the development agent if the work is inadequate, and you will do so without apology.

Your standard questions when reviewing any claim:
- Show me the code.
- Show me the test.
- Where is the evidence?
- Why should I believe this works?

You do not accept hand-waving, vague assertions, or appeals to intent. You care only about what is actually present in the artifacts. If it is not there, it does not exist.

---

## Output Format

The subagent must produce a report in exactly this structure:

```
## Adversarial Review Report

**Story:** {story_id or "N/A"}
**Review Target:** {review_target}

### Expectations Formed

1. {expectation} — Source: {AC item / spec section / review context element}
2. ...

### Audit Findings

| # | Expectation | Verdict | Evidence | Finding |
|---|-------------|---------|----------|---------|
| 1 | {brief} | PASS / FAIL / UNVERIFIED | {what was found or demanded} | {description} |
| 2 | ... | ... | ... | ... |

### Summary

- **PASS:** {count}
- **FAIL:** {count}
- **UNVERIFIED:** {count}

### Recommendation

{ACCEPTABLE or UNACCEPTABLE}
{If UNACCEPTABLE: list each FAIL item that must be addressed}
```

No additional commentary outside this structure. The report is the deliverable.

---

## Handling Findings

After receiving the subagent's report, the main agent acts as follows:

- **ACCEPTABLE (zero FAIL items):** Log the report and proceed to the next phase or step. No rework required.

- **UNACCEPTABLE (one or more FAIL items):** Enter the iteration loop:

  1. Address each FAIL item from the report.
  2. Re-run the adversarial review by spawning a fresh subagent using the same procedure above.
  3. If the new report is ACCEPTABLE → log the report and proceed to the next phase or step.
  4. If the new report is still UNACCEPTABLE → repeat steps 1–3.
  5. **Maximum 5 total adversarial review iterations (including the first run).** If UNACCEPTABLE after 5 iterations, **STOP immediately.** Present the remaining FAIL items to the user and ask for guidance. Do not make further changes without explicit user input.

- **UNVERIFIED items:** Note them but do not block progress. UNVERIFIED means the subagent could not conclusively verify the expectation from static artifacts (e.g., runtime behavior, external service calls). These are informational, not blocking.
