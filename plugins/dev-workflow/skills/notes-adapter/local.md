# Notes Adapter: Local Filesystem

Stores specs on the local filesystem as standalone HTML documents. By default specs live in the repository under `docs/specs/`, so they travel with the code. The folder is configurable — see Configuration below.

No external tools required.

## Configuration

Optional key (from `~/.claude/dev-workflow/config.json` → `adapters.local`):

- `specs_path`: folder where specs are stored. Optional. When unset or empty, defaults to `docs/specs` (relative to the repo root) — the original behavior, so existing setups are unaffected.

## Resolve spec folder

Perform this before any Read spec or Write spec operation to determine the spec folder for the repo being acted on:

1. Resolve `repo_root` for the specific repo (run `git rev-parse --show-toplevel` from inside that repo).
2. Read `adapters.local.specs_path` from `~/.claude/dev-workflow/config.json`.
3. Apply these rules to get the resolved spec folder:

   | `specs_path` value | Resolved spec folder |
   |--------------------|----------------------|
   | unset or empty | `{repo_root}/docs/specs` |
   | absolute (begins with `/`) | the value, used as-is |
   | relative | `{repo_root}/{specs_path}` |

4. Strip any trailing slash from the resolved folder before appending a filename, so the path does not contain a doubled separator.

The same resolution rule is used by both Read spec and Write spec — a spec written to the configured folder must be found again by the reader.

## Spec path

Specs are standalone HTML documents (see Output Format in `skills/shared/standards.md`), so they use the `.html` extension.

```
{resolved-specs-folder}/{story-id}.html
```

Example: for story sc-12345 with default config (no `specs_path`):
```
/path/to/your/repo/docs/specs/sc-12345.html
```

Example: for story sc-12345 with `specs_path` set to `/Users/you/specs`:
```
/Users/you/specs/sc-12345.html
```

`repo_root` must resolve to the **specific repo being specced** — i.e. run `git rev-parse --show-toplevel` from inside that repo's directory, not from the folder the workflow was invoked from. When writing specs for multiple repos with a relative `specs_path` (including the default), resolve each repo's own root independently.

## Read spec

1. Resolve the spec folder (see Resolve spec folder above) for the specific repo being read.
2. Use the Read tool with the full spec path `{resolved-specs-folder}/{story-id}.html`. If the file does not exist, return "not found".

## Write spec

1. Resolve the spec folder (see Resolve spec folder above) for the specific repo being written.
2. Create the spec folder if it doesn't exist:
   ```bash
   mkdir -p {resolved-specs-folder}
   ```
3. Use the Write tool to write the spec content to the full path `{resolved-specs-folder}/{story-id}.html`.

## Note

For stories that span multiple repos with a relative `specs_path` (including the default `docs/specs/`), write one spec into each repo's own resolved folder. Every repo gets its own complete copy of the spec — nothing is shared or referenced across repos. Single-repo stories are unaffected: one spec at `{resolved-specs-folder}/{story-id}.html`.
