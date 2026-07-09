# Repo Discovery

Shared procedure for determining which repo(s) a story or task operates on. `create-story`, `write-spec`, and `start-development` all use this — keep behavior identical across them.

## Two-path detection

Run `git rev-parse --show-toplevel` (via the Bash tool):

- **Path 1 — inside a repo:** output is a non-empty absolute path (e.g. `/workspace/my-service`). You are inside one git repo. Use that path as the single repo root; skip all sub-folder scanning. This is the single-repo path — behave exactly as today.
- **Path 2 — parent/workspace folder:** output contains "not a git repository" or is empty. You are not inside a git repo. Use Glob to find `{CWD}/*/.git` (one level deep only). Each matching parent folder is a repo root. Each repo is its own checkout in its own sibling folder with its own feature branch.

## Service name

A repo's service name is identical to its folder name and repository name (e.g. repo at `/workspace/my-service` → service name `my-service`).

## Reconciling with the story's "Repos to modify" field

There are two repo-determination signals — on-disk discovery (above) and the story's **"Repos to modify"** field. Apply this precedence:

- **Path 1 (inside a single repo):** the field is informational. Operate on that one repo regardless of what the field lists. This preserves full single-repo backward compatibility.
- **Path 2 (parent folder), field present:** use only the listed repos (match by folder/service name).
- **Path 2 (parent folder), field absent or empty:** use all discovered repos.

## Per-item repo tags

Acceptance-criteria and testing-instruction items may carry a bracketed repo marker (e.g. `[api]`, `[web]`). Items tagged `[all]` or untagged apply to every repo. Skills filter scope per repo using these tags.

## Single-repo shortcut

When exactly one repo is in scope — inside a git repo, or the story names exactly one repo — skip any per-repo loop and use existing single-repo behavior unchanged.
