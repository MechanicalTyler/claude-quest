# Plugin Marketplace Version Notification — Implementation Guide

When this plugin releases a new version via a git tag, it should notify the `claude-quest` marketplace to automatically update its version pin.

## Prerequisites

- The `MARKETPLACE_DISPATCH_TOKEN` secret must be available in your repo (it is set at the org level — no per-repo configuration needed)
- The PAT is a fine-grained token scoped to `MechanicalTyler/claude-quest` with `Actions: write` permission

## Setup

1. Find your plugin's name from the table below
2. Create `.github/workflows/notify-marketplace.yml` in your repo using the template below, replacing `<YOUR-PLUGIN-NAME>` with your plugin's name

## Plugin Names

| Repo | Plugin name to use |
|------|--------------------|
| claude-plugin-audit-trail | `audit-trail` |
| claude-plugin-notifications | `notifications` |
| claude-plugin-dev-workflow | `dev-workflow` |
| claude-plugin-guardrails-git | `guardrails-git` |
| claude-plugin-guardrails-bash | `guardrails-bash` |
| claude-plugin-guardrails-docker | `guardrails-docker` |
| claude-plugin-guardrails-xcode | `guardrails-xcode` |

## Workflow Template

Create `.github/workflows/notify-marketplace.yml`:

```yaml
name: Notify Marketplace

on:
  push:
    tags: ['v*']

jobs:
  notify:
    runs-on: ubuntu-latest
    steps:
      - name: Dispatch version bump to claude-quest
        uses: actions/github-script@v7
        with:
          github-token: ${{ secrets.MARKETPLACE_DISPATCH_TOKEN }}
          script: |
            await github.rest.repos.createDispatchEvent({
              owner: 'MechanicalTyler',
              repo: 'claude-quest',
              event_type: 'plugin-version-bump',
              client_payload: {
                plugin: '<YOUR-PLUGIN-NAME>',
                version: context.ref.replace('refs/tags/v', '')
              }
            })
```

## How It Works

1. You push a tag like `v1.8.0` to your plugin repo
2. This workflow fires a dispatch event to `claude-quest` with your plugin name and `1.8.0`
3. `claude-quest` patches `.claude-plugin/marketplace.json`, opens a PR on branch `chore/bump-<plugin>-<version>`, and immediately squash-merges it
4. The marketplace is updated within ~60 seconds of your tag push

## Versioning Convention

- Tags must follow the format `v<semver>` (e.g., `v1.8.0`, `v2.0.0-beta.1`)
- The `v` prefix is stripped before storing in `marketplace.json`
- The version in `plugin.json` in your repo should match the tag

## Troubleshooting

- **Dispatch silently does nothing:** Check that `MARKETPLACE_DISPATCH_TOKEN` is set at the org level and has not expired
- **`claude-quest` workflow fails with "Plugin not found":** Verify the `plugin` name in your workflow matches exactly the `name` field in `claude-quest/.claude-plugin/marketplace.json`
- **Version already matches, no PR opened:** The marketplace is already at this version — this is a no-op and is expected behavior
