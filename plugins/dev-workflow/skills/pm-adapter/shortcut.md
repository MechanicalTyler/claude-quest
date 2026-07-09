# PM Adapter: Shortcut

Story ID format: `sc-XXXXX` or numeric `XXXXX` (strip "sc-" prefix before MCP calls). Prefer `sc-XXXXX` any time `XXXXX` is not explicitly required.

## Fetch Story

MCP tool: `mcp__shortcut__stories-get-by-id` with numeric story ID

Returns: name, description, comments[], workflow_state, story_type

Also fetch comments with: `mcp__shortcut__stories-get-history` for full comment thread

## Post Comment

MCP tool: `mcp__shortcut__stories-create-comment` with story_id (numeric) and text

## Update Story

MCP tool: `mcp__shortcut__stories-update` with story_id (numeric) and fields object

## Story Reference in PRs

**Native attachment:** Shortcut detects the story ID automatically from:
- Branch names containing `sc-###` separated by `/` or `-` (e.g., `feature/sc-123-add-login`, `sc-123-add-login`)
- PR title containing `[sc-###]`
- PR body containing `[sc-###]`
- Commit messages containing `[sc-###]`

When a branch with the story ID is pushed and a PR is opened, Shortcut links the PR to the story automatically — no manual text in the PR body is required.

**Recommended:** Name branches as `username/sc-###/description` or `sc-###-description` to trigger the native link.

**Fallback reference in PR body** (for reviewers without Shortcut access): `Shortcut Story: sc-XXXXX`

## Finding PRs linked to a story

**Option 1 — MCP (preferred if Shortcut MCP is configured):**

```
mcp__shortcut__stories-get-by-id
  storyPublicId: {numeric-id}
  full: true
```

The response includes a `pull_requests` array with PR data (title, URL, status, draft, merged) and a `branches` array with linked branches.

**Option 2 — Shortcut REST API:**

```bash
curl -H "Shortcut-Token: $SHORTCUT_API_TOKEN" \
  "https://api.app.shortcut.com/api/v3/stories/{numeric-id}" \
  | jq '.pull_requests[]'
```

**Option 3 — GitHub search fallback:**
```bash
gh pr list --state all --search "sc-{id}"
```

## Story reference in notes Adapter

Format: `sc-XXXXX`

## Create Story

**⚠️ Gated operation:** subject to the Story Creation Gate in `skills/shared/standards.md` — never execute unless the gate is satisfied.

MCP tool: `mcp__shortcut__stories-create` with fields:
- `name`: story title
- `description`: full markdown body (see body format below)
- `story_type`: infer from context ("feature" for new capabilities, "bug" for fixes, "chore" for maintenance)
- `workflow_state_id`: use default workflow — call `mcp__shortcut__workflows-get-default` to get the starting state ID

### Story body format

Construct the description as:

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
```

**Multi-repo stories:** follow the Multi-repo story contract in `skills/pm-adapter/interface.md` (repo tags on AC/testing items; never create subtasks or sub-stories).

Return: the created story's public ID (e.g., `sc-601`) and `app_url` for confirmation.
