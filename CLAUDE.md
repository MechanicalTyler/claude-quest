# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**claude-quest** is a public marketplace of Claude Code plugins for software development teams (see `README.md` for the plugin list). It is hosted publicly on GitHub and installed directly via `/plugin marketplace add`.

Individual plugins document their own architecture in their own `plugins/<plugin-name>/CLAUDE.md` file — this file covers only what applies repo-wide.

## Public/Private Boundary

This repository is **public**. Its content — plugin source, skill instructions, documentation, commit history, and PR descriptions — is visible to anyone.

- Never reference a private company name, internal-only product name, or other non-public organization name anywhere in this repository's content, including skill instructions, code comments, commit messages, and PR titles/bodies/comments.
- If a story or spec drafted for this repo would otherwise need such a reference, generalize the wording instead (e.g. describe the constraint or convention itself, without naming the private organization it happens to originate from).
- A private, company-specific wrapper around a plugin in this repo belongs in its own separate private repository, not in this one.

This rule exists because a private company name has previously leaked into public-repo content drafted here.
