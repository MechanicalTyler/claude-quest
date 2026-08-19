# Code Comment Compliance Check

Shared procedure, referenced by `start-development/SKILL.md` (Pre-Completion Verification) and
`address-pr-comments/SKILL.md` (Step 5: Verify) — mirrors how `skills/shared/adversarial-review.md`
is a single procedure file invoked by reference from multiple call sites rather than copy-pasted.

Run this as a mechanical grep, not a prose reminder — it backstops the "Code Comments" rule in
`skills/shared/standards.md`, which was violated even though the rule was already written down.

## Step 1: Resolve the base ref

Resolve the default branch the same way `skills/shared/adversarial-review.md` (Step 3) does:

```bash
git fetch origin
git symbolic-ref refs/remotes/origin/HEAD | sed 's@^refs/remotes/origin/@@'
```

If this does not resolve (e.g. `fatal: ref refs/remotes/origin/HEAD is not a symbolic ref`), repair
it and re-resolve:

```bash
git remote set-head origin -a
```

**If the base ref still cannot be resolved after the repair attempt, this check blocks completion
— it does not pass.** Report the failure and stop. Do not treat an unresolved base as "no changes
found" and do not let the check silently no-op.

## Step 2: Find changed lines

Using the resolved base ref `{base}`, diff against the merge-base with **three-dot** syntax, not
two-dot — two-dot renders base-branch-only commits as inverted additions and flags lines this
branch never touched, and the gap grows unbounded as the branch ages:

```bash
git diff {base}...HEAD --name-only
```

For each changed file:

```bash
git diff {base}...HEAD -U0 -- {file}
```

Keep only lines prefixed with a single `+` (excluding the `+++` file-header line) — these are the
lines added or modified on this branch.

## Step 3: Identify comment lines

Among those added/modified lines, a line counts as a comment when, ignoring leading whitespace, it
starts with a line-comment marker recognized for that file's extension, or falls inside an added
block-comment marker recognized for that extension:

- `.tf` (HCL) — line markers `#` and `//` (HCL accepts both), block marker `/* … */`
- `.yaml`/`.yml`, `.py`, `.sh`, `.rb` — `#` only
- `.go`, `.js`, `.ts`, `.tsx`, `.jsx`, `.java`, `.c`, `.cpp`, `.rs` — `//` line marker and `/* … */`
  block marker
- `.sql`, `.lua` — `--` line marker only

A block-comment marker is only detected when the diff makes the opening delimiter itself an added
(`+`-prefixed) line; because `git diff -U0` isolates changed lines with no surrounding context, a
line that is textually inside a block comment whose opening delimiter was not itself touched by
this branch cannot be identified as a comment by this check and is out of scope — a known
limitation of the `-U0` approach. Unrecognized extensions are skipped (not blocked).

## Step 4: Match patterns

**These are PCRE patterns — run with `grep -P` (or `rg`).** A POSIX-ERE-only `grep` on PATH
(e.g. ugrep without `-P`) will silently under-match or mis-match some of these — verify `-P` (or
`rg`) is actually what executes before trusting a clean result.

Match against each comment line's text, case-insensitive, "on the same line" as the concrete
reading of "adjacent" (informally, within about 40 characters):

- (a) story ID — `\bsc-[0-9]+\b`
- (b) commit hash — `\b(commit(s|ted)?|sha|hash|rev)\b.{0,40}\b[0-9a-f]{7,40}\b` or
  `\b[0-9a-f]{7,40}\b.{0,40}\b(commit(s|ted)?|sha|hash|rev)\b`
- (c) CI run ID — `\b(run|ci)\b.{0,40}\b[0-9]{8,}\b` or `\b[0-9]{8,}\b.{0,40}\b(run|ci)\b`, or a
  substring matching `github\.com/\S+/actions/runs/[0-9]+`. The 8-digit floor on the bare-numeric
  alternatives is deliberate — it eliminates false positives on small numbers (durations, counts,
  thresholds) that are not run IDs while still matching real CI run IDs, which run 9-11 digits.
  The `actions/runs/` URL alternative has no digit floor because the URL shape itself is
  unambiguous.
- (d) verbose comment block — a contiguous run of added (`+`-prefixed) comment lines, per Step 3's
  per-extension comment-line detection, with no non-comment or blank line breaking the run, whose
  count exceeds 4 lines.

## Step 5: On any match

Do not declare work complete. Report the file, line, and which pattern matched (including pattern
(d)'s line-count threshold when that is the match); the offending citation or verbose block must be
rephrased, trimmed, or removed per the "Code Comments" rule in `skills/shared/standards.md`, and the
check re-run. There is no suppression or override path — this blocks on any match, even given the
heuristic's occasional false positive (e.g. a line reading "let the migration run for 100000000 ms
before checking" or "the nightly batch run processed 12345678 rows" would trip pattern (c); rephrase
it rather than bypass the check).

## Execution scope

- **Single-repo path** (`address-pr-comments`; single-repo `start-development`): runs once, from
  the repo root, as part of the calling skill's own verification step.
- **Multi-repo path** (`start-development` Step 3 dispatch): runs *inside each per-repo sub-agent,
  from that sub-agent's own repo root*, as part of its own self-review before it reports back to
  the main agent (mirroring how "Internal Code Review" is already scoped per-repo in that path).
  The main agent never runs this check itself from the multi-repo workspace parent. The per-repo
  dispatch prompt should **reference this file by path** (`skills/shared/code-comment-check.md`),
  not inline the full table — mirroring how `adversarial-review.md` is dispatched by reference.
