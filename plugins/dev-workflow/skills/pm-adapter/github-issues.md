# PM Adapter: GitHub Issues

Story ID format: `#XXX` or numeric `XXX`

## Fetch Story

```bash
gh issue view {number} --json title,body,comments,labels,state
```

Parse the JSON to extract title, description (body), and comments array.

## Post Comment

```bash
gh issue comment {number} --body "{text}"
```

## Update Story

```bash
# Add label
gh issue edit {number} --add-label "{label}"

# Set milestone
gh issue edit {number} --milestone "{milestone-name}"

# Close issue
gh issue close {number}
```

## Story Reference in PRs

**Native attachment:** GitHub detects issue references automatically from:
- PR body (description) using a closing keyword: `Closes #N`, `Fixes #N`, `Resolves #N` (case-insensitive) — auto-closes the issue when the PR merges to the default branch
- Commit messages using the same closing keywords
- PR body with a plain mention `#N` (cross-references without auto-closing)

**Note:** PR title alone does NOT trigger auto-close, though it creates a cross-reference visible in the issue timeline.

**Recommended:** Include `Closes #XXX` in the PR description to link natively and auto-close on merge.

**Fallback reference** (no auto-close): `Issue: #XXX`

## Finding PRs linked to a story

**Option 1 — MCP (if `github/github-mcp-server` is configured):**

```
search_pull_requests
  query: "repo:owner/repo closes:#{issue-number}"
```

Or to catch all keyword variants:
```
search_pull_requests
  query: "repo:owner/repo #{issue-number}"
```

**Option 2 — `gh` CLI:**

```bash
# Find PRs linked via closing keywords (most reliable)
gh pr list --state all --search "linked:{issue-number}"

# Or search by keyword in body
gh pr list --state all --search "closes #{issue-number} OR fixes #{issue-number}"
```

**Option 3 — Issue timeline API (finds all cross-references):**

```bash
gh api repos/OWNER/REPO/issues/{issue-number}/timeline --paginate \
  --jq '.[] | select(.event == "cross-referenced") | select(.source.type == "pull_request") | .source.issue.number'
```

## Story reference in notes Adapter

Format: `#XXX` — use the hash-prefixed issue number (e.g., `#123`)

## Create Story

**⚠️ Gated operation:** subject to the Story Creation Gate in `skills/shared/standards.md` — never execute unless the gate is satisfied.

Use the `gh` CLI to create a new issue. Write the body to a temp file first to avoid shell interpolation issues with multi-line markdown:

```bash
# Write body to temp file
# Then create the issue using --body-file
gh issue create --title "{title}" --body-file .scratch/tmp/gh-issue-body.md
```

Write the body content to `.scratch/tmp/gh-issue-body.md` using the Write tool before running the command.

### Body format

Construct the body as:

```
## Original Request
{originalRequest}

---

## Story

{description}

**Repos to modify:** {reposToModify joined with ", "}

**Repos to reference:** {reposToReference joined with ", " or "(none)" if empty}

**Acceptance Criteria**
- [ ] {ac item 1}
- [ ] {ac item 2}
...

**Testing Instructions**
1. {step 1}
2. {step 2}
...

Note: For multi-repo stories, follow the Multi-repo story contract in `skills/pm-adapter/interface.md` (repo tags on AC/testing items; never create subtasks or sub-stories).
```

Return: the created issue number (e.g., `#42`) and URL for confirmation.
