---
name: dev-workflow:address-pr-comments
description: "Address PR review feedback in the current session — reads new comments, file-level inline comments, and review decisions since the last commit, then implements the required changes and replies to the PR with a summary of fixes. Use when a user asks to address PR comments, respond to review feedback, fix review notes, or iterate on a PR."
---

# Address PR Comments

**Role:** Address review feedback on the current PR — read, implement, and respond

**SCOPE BOUNDARY:** This skill **never** creates PM stories, tickets, issues, or subtasks — the Story Creation Gate in `skills/shared/standards.md` applies.

Read `skills/shared/standards.md` — these mandatory rules govern this entire session.

Compact the conversation before continuing — you are about to iterate on existing work.

---

## Step 1: Identify the PR

If no PR number is provided in context:

```bash
gh pr status --json currentBranch
```

Use the current branch's open PR. If no PR is open, ask the user for the PR number.

---

## Step 2: Load New Feedback

Fetch all comment types since the last commit. Use the actual PR number in every command.

**Conversation comments:**
```bash
gh api repos/{owner}/{repo}/issues/{PR_NUMBER}/comments
```

**Inline file comments:**
```bash
gh api repos/{owner}/{repo}/pulls/{PR_NUMBER}/comments
```

**Reviews (state + body):**
```bash
gh api repos/{owner}/{repo}/pulls/{PR_NUMBER}/reviews
```

Filter to comments created or updated after the last commit timestamp:
```bash
git log -1 --format=%cI
```

Deduplicate: if an inline comment is also referenced in a review body, address it once.

---

## Step 3: Summarize Required Changes

Before writing any code, list every actionable item as a numbered checklist:

```
## Changes Required

1. [Author @foo, file.ts:42] — [what they asked for]
2. [Author @bar, review body] — [what they asked for]
```

If no actionable feedback is found, inform the user and stop.

---

## Step 4: Implement Changes

Address each item from the checklist:

- Apply the full RED-GREEN-REFACTOR cycle for code changes:
  > Invoke Skill: `superpowers:test-driven-development`
- Address items in checklist order — do not skip or defer
- Do not change anything outside the scope of reviewer feedback. Exception: the Code Comment Compliance Check in Step 5 requires rephrasing or removing any matched ticket/commit-hash/CI-run-ID citation with no suppression path, even when the offending comment predates this review/fix round and no reviewer flagged it — this is the one carve-out to this rule.
- Commit frequently with descriptive messages referencing the item being addressed

---

## Step 5: Verify

### Code Comment Compliance Check

Run this as a mechanical grep, not a prose reminder — it backstops the "Code Comments" rule in `skills/shared/standards.md`, which was violated even though the rule was already written down.

1. **Find changed lines.** `git fetch origin`, then `git diff origin/HEAD --name-only` for the changed-file list (the whole-branch diff basis, not "since the last commit" — this catches citations introduced in any commit on the branch, not only the most recent one). For each changed file, run `git diff origin/HEAD -U0 -- {file}` and keep only lines prefixed with a single `+` (excluding the `+++` file-header line) — these are the lines added or modified on this branch.

2. **Identify comment lines.** Among those added/modified lines, a line counts as a comment when, ignoring leading whitespace, it starts with a line-comment marker recognized for that file's extension, or falls inside an added block-comment marker recognized for that extension:
   - `.tf` (HCL) — line markers `#` and `//` (HCL accepts both), block marker `/* … */`
   - `.yaml`/`.yml`, `.py`, `.sh`, `.rb` — `#` only
   - `.go`, `.js`, `.ts`, `.tsx`, `.jsx`, `.java`, `.c`, `.cpp`, `.rs` — `//` line marker and `/* … */` block marker
   - `.sql`, `.lua` — `--` line marker only

   A block-comment marker is only detected when the diff makes the opening delimiter itself an added (`+`-prefixed) line — a known limitation of the `-U0` approach. Unrecognized extensions are skipped (not blocked).

3. **Match patterns** against each comment line's text, case-insensitive, "on the same line" as the concrete reading of "adjacent" (informally, within about 40 characters):
   - (a) story ID — `\bsc-[0-9]+\b`
   - (b) commit hash — `\b(commit(s|ted)?|sha|hash|rev)\b.{0,40}\b[0-9a-f]{7,40}\b` or `\b[0-9a-f]{7,40}\b.{0,40}\b(commit(s|ted)?|sha|hash|rev)\b`
   - (c) CI run ID — `\b(run|ci)\b.{0,40}\b[0-9]+\b` or `\b[0-9]+\b.{0,40}\b(run|ci)\b` or a substring matching `github\.com/[^\s]+/actions/runs/[0-9]+` — no minimum digit count.

4. **On any match:** do not declare work complete. Report the file, line, and which pattern matched; the offending citation must be rephrased or removed per the "Code Comments" rule in `skills/shared/standards.md` (see the Step 4 carve-out above), and the check re-run. There is no suppression or override path.

This check runs once, from the current repo root, as part of Step 5 — `address-pr-comments` has no multi-repo path, no repo discovery, and no per-repo sub-agent dispatch.

> Invoke Skill: `superpowers:verification-before-completion`
>
> Verify with fresh execution:
> - All tests pass (run the full suite now)
> - Each checklist item from Step 3 has been addressed
> - Code is pushed to remote

---

## Step 5.5: Functional Verification in Dev Environment

After unit/integration tests pass, verify the fixes work in a running environment. Loop until certain.

**Deploy:**

Check `~/.claude/dev-workflow/config.json` for `deploy_command`.

- **If `deploy_command` is configured:** Deploy the branch to dev — follow the same deployment procedure as `dev-workflow:test-pr` Phase 3 (GitHub Actions, shell command, or other pattern).
- **If not configured:** Run the service locally. Start it using whatever mechanism the project provides (Makefile, npm scripts, etc.).

**Test:**

For each item from the Step 3 checklist, design and execute a focused test scenario:

1. Document what you're doing and the expected outcome
2. Execute with fresh commands — no assumptions from prior runs
3. Collect evidence: logs, API responses, CLI output, screenshots
4. Record PASS or FAIL with specific details

Apply the accountability rules from `dev-workflow:test-pr`: if you see an error, it is a failure — do not rationalize it away.

**Loop:**

- If any test fails → fix the issue, commit, push, re-deploy, re-test
- Continue until ALL addressed items pass functional testing
- Only proceed to Step 6 when you are certain every fix works correctly in the running environment

---

## Step 6: Reply to PR

### 6a: Reply to Inline Comments Directly

For each inline file comment addressed in Step 4, post a **direct reply** on that comment thread explaining what was changed:

```bash
gh api repos/{owner}/{repo}/pulls/{PR_NUMBER}/comments/{COMMENT_ID}/replies -f body="..."
```

Reply format: one concise sentence stating what was done (e.g., "Fixed — switched to `parseISO()` at `utils.ts:47`."). Do not repeat the reviewer's request back to them.

If you deviated from what the reviewer asked on a specific comment, explain why in the reply to that comment.

### 6b: Post Summary Comment

Post a summary comment on the PR covering all changes. Call out any deviations not already explained in inline replies.

Comment format:
```markdown
## Changes Addressed

1. [Item 1] — [what was changed and where: file.ts:42]
2. [Item 2] — [what was changed and where]

## Deviations
[Omit section entirely if none. Otherwise explain each deviation and reasoning.]
```

```bash
gh pr comment {PR_NUMBER} --body "..."
```
