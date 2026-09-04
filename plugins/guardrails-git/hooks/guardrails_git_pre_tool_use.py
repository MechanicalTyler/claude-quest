#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.8"
# ///

import json
import os
import shlex
import sys
import re
import subprocess


def create_timeout_error_message(command_type, wanted_timeout, current_timeout):
    minutes = int(wanted_timeout / 60 / 1000)
    return f"You must set a timeout of {wanted_timeout}ms ({minutes} minutes) for {command_type} commands. This is not a test timeout error. Please retry the command with 'timeout': {wanted_timeout} in the tool parameters."


# --- Branch policy ------------------------------------------------------------
#
# Policy: new branches may only be created from 'main', and 'main' itself may
# not be checked out. Enforced on shlex tokens per shell segment so equivalent
# forms (git branch <name>, git switch -c, chained commands, git -C <dir> ...)
# are all covered, not just 'git checkout -b'. Recognized front-ends include
# the gitp/ghp and git-as-app.sh/gh-as-app.sh wrappers in addition to plain
# git/gh.
#
# 'git worktree' is exempted from the branch-creation-must-be-from-main check
# outright — every subcommand and flag combination ('add', with or without
# -b/-B/--detach, 'list', 'remove', 'prune', 'move', 'lock', ...) falls
# through to allowed there, regardless of the current branch. dev-workflow
# now requires isolated worktrees for implementation/fix work, and a hard
# block on worktree creation off a non-main branch is exactly what would
# prevent that — a dead branch of this check that can never fire safely is
# dead code, not a safeguard.
#
# One narrower exemption is carved out of that, though: 'git worktree add
# <path> <existing-ref>' with no -b/-B/--detach materializes <existing-ref>
# as a live, checked-out working tree — exactly the state the checkout-main
# guard exists to prevent. So that specific form gets the same treatment as
# 'git checkout main' when <existing-ref> is 'main'. Branch-creating forms
# (-b/-B, or 'add <path>' alone — an implicit new branch off HEAD) and
# detached forms (--detach) stay exempt, since none of them checks out
# 'main' itself.

# Any of these flags means 'git branch' is listing/deleting/moving/copying/
# configuring — not creating a branch.
BRANCH_NON_CREATE_OPTS = {'-d', '-D', '--delete', '-m', '-M', '--move',
                          '-c', '-C', '--copy', '-l', '--list', '-a', '--all',
                          '-r', '--remotes', '--show-current', '-v', '-vv',
                          '--verbose', '--merged', '--no-merged', '--contains',
                          '--no-contains', '--points-at', '--sort', '--format',
                          '--column', '--edit-description', '--set-upstream-to',
                          '-u', '--unset-upstream'}
# Branch-creating flags of 'git checkout' (-b/-B) and 'git switch' (-c/-C, --create).
CREATE_OPTS = {'-b', '-B', '-c', '-C', '--create', '--force-create', '--orphan'}

BRANCH_CREATION_REASON = ("New branches should only be created from 'main', but you're currently on "
                          "'{branch}'. You're already on the correct branch for your work, so no need "
                          "to create a new one.")
CHECKOUT_MAIN_REASON = ("Claude isn't allowed to checkout the main branch. "
                        "Please ask the user what to do instead.")
UNRESOLVED_BRANCH_REASON = ("Could not determine the current branch for this invocation — "
                            "refusing rather than assuming it's safe to proceed.")


def _block(reason):
    print(json.dumps({"decision": "block", "reason": reason}))
    sys.exit(1)


def get_current_branch(cwd=None):
    """Look up the current branch of the repo at `cwd`. `cwd` is passed
    explicitly to subprocess.run rather than baked into the argv via
    'git -C' — the hook process's own OS cwd is never a valid resolution
    base (it's never deliberately set to match the caller's shell), so
    every caller must resolve an actual directory first and hand it here.
    A falsy `cwd` means no caller ever resolved a real directory — refuse
    outright rather than letting subprocess.run(cwd=None) silently fall
    back to inheriting the hook process's own OS cwd, which would violate
    that same invariant."""
    if not cwd:
        return None
    try:
        result = subprocess.run(['git', 'branch', '--show-current'], capture_output=True,
                                text=True, timeout=5, cwd=cwd)
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, subprocess.SubprocessError, FileNotFoundError, OSError):
        pass
    return None


def tokenize_segments(command):
    """Split a shell command into token lists, one per `;`/`&&`/`||`/`&`
    separated simple command. `(`, `)`, and `|` are kept as their own
    single-token segments (rather than discarded like the other
    separators) so callers can detect subshell/pipe-stage scope
    boundaries — a `cd` inside `(...)` or on one side of a `|` runs in a
    forked subshell whose directory changes never reach anything outside
    that scope. Raises ValueError on unbalanced quoting."""
    lex = shlex.shlex(command, posix=True, punctuation_chars=True)
    lex.whitespace_split = True
    segments, current = [], []
    for tok in lex:
        if tok in ('(', ')', '|'):
            if current:
                segments.append(current)
                current = []
            segments.append([tok])
        elif all(ch in ';|&()' for ch in tok):
            if current:
                segments.append(current)
                current = []
        else:
            current.append(tok)
    if current:
        segments.append(current)
    return segments


def _resolve_path(directory, payload_cwd):
    """Resolve a possibly-relative directory (from 'cd <dir>' or 'git -C
    <dir>') against the payload's cwd as the base — never against the hook
    process's own OS cwd, which is never deliberately set to match the
    caller's shell. An already-absolute directory passes through
    unchanged. A relative directory with no base to resolve against is
    unresolvable — returning it unchanged would let subprocess.run(cwd=...)
    silently resolve it against exactly the forbidden base, so report None
    instead."""
    if directory is None or os.path.isabs(directory):
        return directory
    if not payload_cwd:
        return None
    return os.path.normpath(os.path.join(payload_cwd, directory))


def _cd_argument(seg):
    """Classify a segment as a 'cd' invocation's directory argument.
    Returns (kind, value): 'none' (not a 'cd' segment, or a 'cd' with no
    resolvable operand — e.g. bare 'cd', or only flag tokens) leaves the
    accumulated directory unchanged; 'unresolved' (a bare '-' — the
    caller shell's previous directory, which this hook has no notion of
    — or a '$'-bearing argument, e.g. '$HOME/x', which this hook cannot
    safely expand) means the directory from this point is unknown;
    'path' (value is the operand with a leading flag like 'cd -P' skipped
    and '~' expanded via os.path.expanduser) is handed to _resolve_path."""
    if not seg or seg[0] != 'cd':
        return 'none', None
    for tok in seg[1:]:
        if tok == '-' or '$' in tok:
            return 'unresolved', None
        if tok.startswith('-'):
            continue
        return 'path', os.path.expanduser(tok)
    return 'none', None


def resolve_default_dir(segments, index, payload_cwd):
    """The directory a git invocation at `index` actually runs in, absent
    an explicit 'git -C': replay every 'cd <dir>' segment before it in the
    command chain, each resolved against the directory accumulated so far
    (not against a fixed payload snapshot — a 'cd' chain composes, e.g. in
    'cd <repo> && cd <relative-subdir> && git commit' the second cd must
    resolve against the first, not against the shell's cwd before either
    ran), starting from the PreToolUse hook payload's 'cwd' (which reflects
    the persistent shell's current directory, not this hook process's own
    OS cwd).

    A '(' opens a new subshell scope (its own copy of the accumulated
    directory, discarded when the matching ')' closes it — nothing a 'cd'
    does inside survives past that ')'). A '|' resets the current scope's
    accumulated directory back to what it was before the current pipeline
    stage started — each stage of a pipe forks its own subshell, so a
    'cd' in one stage never reaches a later stage or anything after the
    pipe, even within the same '(...)' scope. An 'unresolved' cd argument
    (Required Change 3 forms this hook can't safely interpret) poisons the
    accumulated directory for the rest of its scope, same as a resolvable
    'cd' would overwrite it — later relative operands then correctly fail
    to resolve too, via _resolve_path's own falsy-base handling."""
    dir_stack = [payload_cwd]
    checkpoint_stack = [payload_cwd]
    for seg in segments[:index]:
        if seg == ['(']:
            dir_stack.append(dir_stack[-1])
            checkpoint_stack.append(dir_stack[-1])
        elif seg == [')']:
            if len(dir_stack) > 1:
                dir_stack.pop()
                checkpoint_stack.pop()
        elif seg == ['|']:
            dir_stack[-1] = checkpoint_stack[-1]
        else:
            kind, value = _cd_argument(seg)
            if kind == 'path':
                dir_stack[-1] = _resolve_path(value, dir_stack[-1])
            elif kind == 'unresolved':
                dir_stack[-1] = None
    return dir_stack[-1]


# Recognized git/gh front-end tokens, each mapped to how many positional
# (non-flag) tokens to skip after it — the wrapper's persona argument —
# before the real subcommand.
GIT_FRONTENDS = {'git': 0, 'gitp': 0, 'git-as-app.sh': 1}
GH_FRONTENDS = {'gh': 0, 'ghp': 0, 'gh-as-app.sh': 1}


def _find_frontend(segment, frontends):
    """(index, positional-skip count) of the first front-end token in the
    segment, or None."""
    for i, tok in enumerate(segment):
        if tok in frontends:
            return i, frontends[tok]
    return None


def parse_git_invocation(segment):
    """If the segment invokes a git front-end (git, gitp, git-as-app.sh),
    return (subcommand, args, explicit_dir); otherwise None. 'explicit_dir'
    is the raw (possibly relative, possibly None) argument of an explicit
    '-C <dir>' on the invocation — resolution against a default directory
    happens in git_invocations, which has the segment's position in the
    command chain and can rank -C above any 'cd'. Skips the wrapper's
    persona argument and git's global options to find the subcommand."""
    found = _find_frontend(segment, GIT_FRONTENDS)
    if found is None:
        return None
    idx, skip = found
    rest = segment[idx + 1:]
    git_dir = None
    while rest:
        if rest[0].startswith('-'):
            opt = rest.pop(0)
            if opt == '-C' and rest:
                git_dir = rest.pop(0)
            elif opt in ('-c', '--git-dir', '--work-tree') and rest:
                rest.pop(0)
        elif skip:
            rest.pop(0)
            skip -= 1
        else:
            break
    if not rest:
        return None
    return rest[0], rest[1:], git_dir


def git_invocations(command, payload_cwd=None):
    """All git invocations in the command as (subcommand, args, dir) tuples,
    'dir' resolved per invocation in precedence order: an explicit 'git -C'
    on that invocation, else the last 'cd <dir>' segment before it anywhere
    in the command chain, else payload_cwd as the final fallback. Relative
    '-C'/'cd' directories resolve against payload_cwd, never the hook
    process's own OS cwd."""
    try:
        segments = tokenize_segments(command)
    except ValueError:
        return []  # unbalanced quoting — the shell will reject the command anyway
    invocations = []
    for index, seg in enumerate(segments):
        parsed = parse_git_invocation(seg)
        if parsed is None:
            continue
        subcommand, args, explicit_dir = parsed
        base_dir = resolve_default_dir(segments, index, payload_cwd)
        if explicit_dir is not None:
            git_dir = _resolve_path(explicit_dir, base_dir)
        else:
            git_dir = base_dir
        invocations.append((subcommand, args, git_dir))
    return invocations


def gh_invocations(command):
    """Token lists following a gh front-end (gh, ghp, gh-as-app.sh) in each
    shell segment, with the wrapper's persona argument stripped."""
    try:
        segments = tokenize_segments(command)
    except ValueError:
        return []
    invocations = []
    for seg in segments:
        found = _find_frontend(seg, GH_FRONTENDS)
        if found is None:
            continue
        idx, skip = found
        rest = seg[idx + 1:]
        while rest and skip:
            if not rest[0].startswith('-'):
                skip -= 1
            rest.pop(0)
        invocations.append(rest)
    return invocations


def _matches_opt(tok, opts):
    """True if tok is one of opts, in --opt=value form, or in git's stuck
    short-option form ('-bname' for '-b name')."""
    return (tok.split('=', 1)[0] in opts
            or (not tok.startswith('--') and len(tok) > 2 and tok[:2] in opts))


def evaluate_git_invocation(subcommand, args, git_dir):
    """Return a block reason for a policy violation, else None."""
    creates = False
    if subcommand in ('checkout', 'switch'):
        flags = [tok for tok in args if tok.startswith('-') and tok != '--']
        positionals = [tok for tok in args if not tok.startswith('-')]
        creates = any(_matches_opt(tok, CREATE_OPTS) for tok in flags)
        if not creates and positionals and positionals[0] == 'main':
            return CHECKOUT_MAIN_REASON
    elif subcommand == 'branch':
        flags = [tok for tok in args if tok.startswith('-') and tok != '--']
        positionals = [tok for tok in args if not tok.startswith('-')]
        creates = bool(positionals) and not any(
            _matches_opt(tok, BRANCH_NON_CREATE_OPTS) for tok in flags)
    elif subcommand == 'worktree':
        # Every other 'worktree' subcommand/flag combination is allowed —
        # see the module comment above. Only 'add <path> <existing-ref>'
        # (no -b/-B/--detach) gets narrowed, and only when <existing-ref>
        # is 'main'.
        if args and args[0] == 'add':
            rest = args[1:]
            flags = [tok for tok in rest if tok.startswith('-') and tok != '--']
            positionals = [tok for tok in rest if not tok.startswith('-')]
            branch_creating = any(_matches_opt(tok, {'-b', '-B'}) for tok in flags)
            detached = any(_matches_opt(tok, {'--detach'}) for tok in flags)
            if (not branch_creating and not detached
                    and len(positionals) >= 2 and positionals[1] == 'main'):
                return CHECKOUT_MAIN_REASON
    if creates:
        branch = get_current_branch(git_dir)
        if branch == 'main':
            pass  # creating a new branch from main is exactly the allowed flow
        elif branch:
            return BRANCH_CREATION_REASON.format(branch=branch)
        else:
            return UNRESOLVED_BRANCH_REASON
    return None


def check_git_branch_policy(tool_name, tool_input, payload_cwd=None):
    if tool_name != 'Bash':
        return
    command = tool_input.get('command', '')
    for invocation in git_invocations(command, payload_cwd):
        reason = evaluate_git_invocation(*invocation)
        if reason:
            _block(reason)


# --- End branch policy ----------------------------------------------------------


def check_git_commit_branch(tool_name, tool_input, payload_cwd=None):
    if tool_name != 'Bash':
        return
    command = tool_input.get('command', '')
    for subcommand, args, git_dir in git_invocations(command, payload_cwd):
        if subcommand != 'commit':
            continue
        branch = get_current_branch(git_dir)
        if branch == 'main':
            _block("Direct commits to the 'main' branch are not allowed. Please create a feature "
                   "branch first (e.g., 'git checkout -b feature/your-feature-name') and commit "
                   "your changes there, then create a pull request.")
        elif not branch:
            _block(UNRESOLVED_BRANCH_REASON)


def check_git_no_verify(tool_name, tool_input, payload_cwd=None):
    if tool_name != 'Bash':
        return
    for subcommand, args, git_dir in git_invocations(tool_input.get('command', ''), payload_cwd):
        for tok in args:
            if tok == '--':
                break
            if tok == '--no-verify' or (subcommand == 'commit' and tok == '-n'):
                _block("The '--no-verify' flag is not allowed in git commands. "
                       "You are never allowed to skip hooks")


CLAUDE_BOILERPLATE_PATTERNS = [
    r'Generated with Claude Code',
    r'Co-Authored by Claude',
    r'Generated with \[Claude Code\]',
    r'Co-Authored-By:\s*Claude',
    r'<noreply@anthropic\.com>',
    r'claude\.ai/code',
    r'Generated by Claude',
    r'Created with Claude Code',
    r'Assisted by Claude',
    r'With help from Claude',
    r'@anthropic\.com',
]
AI_BOILERPLATE_PATTERNS = CLAUDE_BOILERPLATE_PATTERNS + [
    r'AI-generated',
    r'AI generated',
    r'Generated by AI',
    r'Created by AI',
    r'Built with AI',
]


def _has_boilerplate(command, patterns):
    return any(re.search(p, command, re.IGNORECASE) for p in patterns)


def _gh_subcommand_present(command, words):
    """True when the command runs `gh <words...>` (flags between words ignored)."""
    for args in gh_invocations(command):
        positionals = [tok for tok in args if not tok.startswith('-')]
        if positionals[:len(words)] == words:
            return True
    return False


def check_git_commit_boilerplate(tool_name, tool_input, payload_cwd=None):
    if tool_name != 'Bash':
        return
    command = tool_input.get('command', '')
    if (any(sub == 'commit' for sub, _, _ in git_invocations(command, payload_cwd))
            and _has_boilerplate(command, CLAUDE_BOILERPLATE_PATTERNS)):
        _block("Boilerplate code patterns are not allowed in git commit messages. Please remove "
               "references to Claude Code, co-authorship with Claude, or Anthropic email addresses "
               "from your commit message and try again.")


def check_pr_create_boilerplate(tool_name, tool_input):
    if tool_name != 'Bash':
        return
    command = tool_input.get('command', '')
    if (_gh_subcommand_present(command, ['pr', 'create'])
            and _has_boilerplate(command, AI_BOILERPLATE_PATTERNS)):
        _block("Boilerplate patterns are not allowed in PR titles or descriptions. Please remove "
               "references to Claude Code, AI generation, co-authorship with Claude, or Anthropic "
               "email addresses from your PR content and try again.")


def _is_pr_comment_api_call(command):
    for args in gh_invocations(command):
        positionals = [tok for tok in args if not tok.startswith('-')]
        if positionals[:1] == ['api'] and any(
                re.search(r'repos/.+/issues/\d+/comments', tok) for tok in args):
            return True
    return False


def check_pr_comment_boilerplate(tool_name, tool_input):
    if tool_name != 'Bash':
        return
    command = tool_input.get('command', '')
    if _is_pr_comment_api_call(command) and _has_boilerplate(command, AI_BOILERPLATE_PATTERNS):
        _block("Boilerplate patterns are not allowed in PR comments. Please remove references to "
               "Claude Code, AI generation, co-authorship with Claude, or Anthropic email addresses "
               "from your comment and try again.")


def _require_timeout(tool_input, command_type, wanted_timeout):
    timeout = tool_input.get('timeout')
    if timeout != wanted_timeout:
        _block(create_timeout_error_message(command_type, wanted_timeout, timeout))


def add_timeout_to_git_commit(tool_name, tool_input, payload_cwd=None):
    if tool_name != 'Bash':
        return
    if any(sub == 'commit' for sub, _, _ in git_invocations(tool_input.get('command', ''), payload_cwd)):
        _require_timeout(tool_input, "Git commit", 900000)


def add_timeout_to_git_push(tool_name, tool_input, payload_cwd=None):
    if tool_name != 'Bash':
        return
    if any(sub == 'push' for sub, _, _ in git_invocations(tool_input.get('command', ''), payload_cwd)):
        _require_timeout(tool_input, "Git push", 900000)


def add_timeout_to_gh_run_watch(tool_name, tool_input):
    if tool_name != 'Bash':
        return
    if _gh_subcommand_present(tool_input.get('command', ''), ['run', 'watch']):
        _require_timeout(tool_input, "gh run watch", 1800000)


def main():
    try:
        input_data = json.load(sys.stdin)
        tool_name = input_data.get('tool_name', '')
        tool_input = input_data.get('tool_input', {})
        payload_cwd = input_data.get('cwd')

        add_timeout_to_git_commit(tool_name, tool_input, payload_cwd)
        add_timeout_to_git_push(tool_name, tool_input, payload_cwd)
        add_timeout_to_gh_run_watch(tool_name, tool_input)
        check_git_commit_branch(tool_name, tool_input, payload_cwd)
        check_git_branch_policy(tool_name, tool_input, payload_cwd)
        check_git_no_verify(tool_name, tool_input, payload_cwd)
        check_git_commit_boilerplate(tool_name, tool_input, payload_cwd)
        check_pr_create_boilerplate(tool_name, tool_input)
        check_pr_comment_boilerplate(tool_name, tool_input)

        sys.exit(0)
    except json.JSONDecodeError:
        sys.exit(0)
    except Exception:
        sys.exit(0)


if __name__ == '__main__':
    main()
