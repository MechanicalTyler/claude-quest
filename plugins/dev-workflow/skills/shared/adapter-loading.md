# Adapter Loading Procedure

## RATIONALIZATION WARNING

**CRITICAL:** Agents MUST call the Read tool on the user override path **first**, before considering fallback options. The fact that a fallback file has content is NOT a valid reason to use it.

**The conditions that permit falling back to the built-in adapter are:** (1) receiving a "File does not exist" error on the override Read call, or (2) the override file exists but is empty or contains no adapter instructions (see Step 1). **Any other result — permission error, unexpected path error, or any non-file-system error — requires stopping with an error. Never skip to Step 2 for any other reason.**

Do not attempt to check if files exist before reading them, and do not rationalize using the fallback because "it's probably there anyway." Always read the override path first and respond to the actual result of that operation.

---

## Load PM Adapter

> **Prerequisite:** `{pm_adapter}` must already be resolved from `~/.claude/dev-workflow/config.json`. If you have not yet read the config, read it now before executing this procedure.

Follow these steps to load the PM adapter specified in the user's configuration:

**Step 1: Check User Override**

Read `~/.claude/skills/pm-adapter/{pm_adapter}.md` (where `{pm_adapter}` is the adapter name from config, e.g., `shortcut` or `jira`)

- **If content is returned AND the file contains adapter instructions (has headings or substantive content):** Read and follow the instructions in this file as your PM adapter. Do not read the fallback. Stop here.
- **If content is returned BUT the file is empty or contains no adapter instructions (no headings, no substantive content):** Treat this as "File does not exist" and proceed to Step 2.
- **If "File does not exist" error is returned:** Proceed to Step 2.
- **If any other error is returned:** Surface the error to the user and stop. Do not proceed to fallback.

**Step 2: Load Built-in Fallback**

Read `skills/pm-adapter/{pm_adapter}.md` (the plugin's built-in adapter for this type)

- **If content is returned AND the file contains adapter instructions (has headings or substantive content):** Read and follow the instructions in this file as your PM adapter. You have successfully loaded the PM adapter.
- **If content is returned BUT the file is empty or contains no adapter instructions (no headings, no substantive content):** Stop with this error:

  > PM adapter `{pm_adapter}` was found at `skills/pm-adapter/{pm_adapter}.md` but the file is empty or contains no adapter instructions. The adapter cannot be loaded.

- **If "File does not exist" error is returned:** Stop with this clear error message:

  > PM adapter `{pm_adapter}` not found in either location:
  > - User override: `~/.claude/skills/pm-adapter/{pm_adapter}.md`
  > - Plugin built-in: `skills/pm-adapter/{pm_adapter}.md`
  >
  > Check `~/.claude/dev-workflow/config.json` to verify the configured PM adapter name is correct, and ensure either the built-in or user override file exists.

- **If any other error is returned:** Surface the error to the user and stop.

---

## Load Notes Adapter

> **Prerequisite:** `{notes_adapter}` must already be resolved from `~/.claude/dev-workflow/config.json`. If you have not yet read the config, read it now before executing this procedure.

Follow these steps to load the notes adapter specified in the user's configuration:

**Step 1: Check User Override**

Read `~/.claude/skills/notes-adapter/{notes_adapter}.md` (where `{notes_adapter}` is the adapter name from config, e.g., `local` or `obsidian`)

- **If content is returned AND the file contains adapter instructions (has headings or substantive content):** Read and follow the instructions in this file as your notes adapter. Do not read the fallback. Stop here.
- **If content is returned BUT the file is empty or contains no adapter instructions (no headings, no substantive content):** Treat this as "File does not exist" and proceed to Step 2.
- **If "File does not exist" error is returned:** Proceed to Step 2.
- **If any other error is returned:** Surface the error to the user and stop. Do not proceed to fallback.

**Step 2: Load Built-in Fallback**

Read `skills/notes-adapter/{notes_adapter}.md` (the plugin's built-in adapter for this type)

- **If content is returned AND the file contains adapter instructions (has headings or substantive content):** Read and follow the instructions in this file as your notes adapter. You have successfully loaded the notes adapter.
- **If content is returned BUT the file is empty or contains no adapter instructions (no headings, no substantive content):** Stop with this error:

  > Notes adapter `{notes_adapter}` was found at `skills/notes-adapter/{notes_adapter}.md` but the file is empty or contains no adapter instructions. The adapter cannot be loaded.

- **If "File does not exist" error is returned:** Stop with this clear error message:

  > Notes adapter `{notes_adapter}` not found in either location:
  > - User override: `~/.claude/skills/notes-adapter/{notes_adapter}.md`
  > - Plugin built-in: `skills/notes-adapter/{notes_adapter}.md`
  >
  > Check `~/.claude/dev-workflow/config.json` to verify the configured notes adapter name is correct, and ensure either the built-in or user override file exists.

- **If any other error is returned:** Surface the error to the user and stop.
