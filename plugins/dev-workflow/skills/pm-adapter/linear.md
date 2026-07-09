# PM Adapter: Linear

Story ID format: `LIN-XXX` or team-prefixed `TEAM-XXX`

## Fetch Story

Use Linear MCP if available, otherwise use Linear GraphQL API with your API token.

Key fields to retrieve: title, description, comments, state, type, assignee

GraphQL query example:
```graphql
query Issue($id: String!) {
  issue(id: $id) {
    title
    description
    state { name }
    comments { nodes { body createdAt } }
  }
}
```

## Post Comment

Linear MCP comment tool, or GraphQL mutation:
```graphql
mutation CreateComment($issueId: String!, $body: String!) {
  commentCreate(input: { issueId: $issueId, body: $body }) {
    success
  }
}
```

## Update Story

Linear MCP update tool, or GraphQL mutation for state/label changes.

## Story Reference in PRs

**Native attachment:** Linear detects the issue identifier automatically from:
- Branch names containing `TEAM-###` anywhere (e.g., `username/ENG-123-fix-login`, `ENG-123-fix-login`)
- PR title containing `TEAM-###`
- PR description containing `TEAM-###` (use a closing keyword to auto-transition on merge: `Fixes ENG-123`, `Closes ENG-123`, `Resolves ENG-123`)
- Commit messages containing `TEAM-###`

**Note:** Detection does NOT apply to PR or issue comments — only titles, descriptions, branch names, and commit messages.

**Recommended:** Use Linear's auto-generated branch names (`username/TEAM-###-short-title`) to trigger the native link. Add `Fixes TEAM-###` in the PR description to auto-close the issue on merge.

**Fallback reference in PR body** (for reviewers without Linear access): `Linear Issue: TEAM-XXX`

## Finding PRs linked to a story

**MCP:** Linear's official MCP server (`mcp.linear.app/mcp`) does not expose a tool to list linked GitHub PRs. No MCP option available.

**GitHub search (only option):**
```bash
gh pr list --state all --search "TEAM-{id}"
```

## Story reference in notes Adapter

Format: `LIN-XXX` (or team-prefixed `TEAM-XXX` — use the same format that was passed in)

## Create Story

**⚠️ Gated operation:** subject to the Story Creation Gate in `skills/shared/standards.md` — never execute unless the gate is satisfied.

Use the Linear MCP create tool if available, otherwise use the GraphQL `issueCreate` mutation:

```graphql
mutation CreateIssue($teamId: String!, $title: String!, $description: String!) {
  issueCreate(input: {
    teamId: $teamId
    title: $title
    description: $description
  }) {
    success
    issue {
      identifier
      url
    }
  }
}
```

**Note:** `teamId` is required by Linear. If not available in context, ask the user for their Linear team ID before creating the story.

### Description format

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

Note: For multi-repo stories, follow the Multi-repo story contract in `skills/pm-adapter/interface.md` (repo tags on AC/testing items; never create subtasks or sub-stories).
```

Return: the created issue identifier (e.g., `LIN-42`) and URL for confirmation.
