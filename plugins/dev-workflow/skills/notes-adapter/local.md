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
3. Apply these rules, in order, to get the resolved spec folder — the first matching row wins. Check for template tokens first: a templated value may also begin with `/` and would otherwise wrongly match the "absolute" row below.

   | `specs_path` value | Resolved spec folder |
   |--------------------|----------------------|
   | contains a `{story-id}` or `{repo}` token | substitute the tokens directly with the current story ID and repo name — the result is already the complete spec **file** path, not a folder (see Spec path below) |
   | unset or empty | `{repo_root}/docs/specs` |
   | absolute (begins with `/`) | the value, used as-is |
   | relative | `{repo_root}/{specs_path}` |

4. For the unset/absolute/relative rows only, strip any trailing slash from the resolved folder before appending a filename, so the path does not contain a doubled separator. This step does not apply when the templated row matched — its result is already a complete file path with no filename appended.

The same resolution rule is used by both Read spec and Write spec — a spec written to the configured folder must be found again by the reader.

## Spec path

Specs are standalone HTML documents (see Output Format in `skills/shared/standards.md`), so they use the `.html` extension.

```
{resolved-specs-folder}/{story-id}.html
```

**Templated case:** when the "contains a `{story-id}` or `{repo}` token" row matched in Resolve spec folder, the resolved value from that step is already the complete file path — do not append `{story-id}.html` to it.

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
2. If the templated row matched, the resolved value from step 1 is already the complete spec path — use it directly with the Read tool. Otherwise, use the Read tool with the full spec path `{resolved-specs-folder}/{story-id}.html`. If the file does not exist, return "not found".

## Write spec

1. Resolve the spec folder (see Resolve spec folder above) for the specific repo being written.
2. Create the destination directory if it doesn't exist:
   - **Templated case** (the templated row matched in step 1): the resolved value is a complete file path, not a folder — create only its **parent** directory, so the `mkdir -p` target does not collide with the file that gets written in step 3:
     ```bash
     mkdir -p $(dirname {resolved-value})
     ```
   - **Unset/absolute/relative case:** create the resolved folder itself, exactly as before:
     ```bash
     mkdir -p {resolved-specs-folder}
     ```
3. Use the Write tool to write the spec content:
   - **Templated case:** write directly to the resolved value from step 1 — do not append a filename.
   - **Unset/absolute/relative case:** write to the full path `{resolved-specs-folder}/{story-id}.html`, exactly as before.

## Note

For stories that span multiple repos with a relative `specs_path` (including the default `docs/specs/`), write one spec into each repo's own resolved folder. Every repo gets its own complete copy of the spec — nothing is shared or referenced across repos. Single-repo stories using the unset/absolute/relative rows are unaffected: one spec at `{resolved-specs-folder}/{story-id}.html`.

**Templated `specs_path`:** the resolved value is already a complete file path (see Spec path above), not a folder, so the "one spec at `{resolved-specs-folder}/{story-id}.html`" description does not apply to this case. For multi-repo stories, the `{repo}` token exists specifically so each repo resolves to its own distinct file path — the current repo's name is substituted into `{repo}` during Resolve spec folder, giving each repo its own spec path with no additional handling required beyond the token substitution already described.
