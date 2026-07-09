#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.8"
# ///

import json
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
# forms (git branch <name>, git switch -c, git worktree add, chained commands,
# git -C <dir> ...) are all covered, not just 'git checkout -b'.

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
WORKTREE_REASON = ("Git worktree commands are not allowed — worktrees create branches and working "
                   "trees outside the branch policy. Please continue working on the current branch "
                   "instead.")


def _block(reason):
    print(json.dumps({"decision": "block", "reason": reason}))
    sys.exit(1)


def get_current_branch(git_dir=None):
    cmd = ['git'] + (['-C', git_dir] if git_dir else []) + ['branch', '--show-current']
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, subprocess.SubprocessError, FileNotFoundError):
        pass
    return None


def tokenize_segments(command):
    """Split a shell command into token lists, one per `;`/`&&`/`||`/`|`
    separated simple command. Raises ValueError on unbalanced quoting."""
    lex = shlex.shlex(command, posix=True, punctuation_chars=True)
    lex.whitespace_split = True
    segments, current = [], []
    for tok in lex:
        if all(ch in ';|&()' for ch in tok):
            if current:
                segments.append(current)
                current = []
        else:
            current.append(tok)
    if current:
        segments.append(current)
    return segments


def parse_git_invocation(segment):
    """If the segment invokes git, return (subcommand, args, dir from -C);
    otherwise None. Skips git's global options to find the subcommand."""
    if 'git' not in segment:
        return None
    rest = segment[segment.index('git') + 1:]
    git_dir = None
    while rest and rest[0].startswith('-'):
        opt = rest.pop(0)
        if opt == '-C' and rest:
            git_dir = rest.pop(0)
        elif opt in ('-c', '--git-dir', '--work-tree') and rest:
            rest.pop(0)
    if not rest:
        return None
    return rest[0], rest[1:], git_dir


def git_invocations(command):
    """All git invocations in the command as (subcommand, args, dir) tuples."""
    try:
        segments = tokenize_segments(command)
    except ValueError:
        return []  # unbalanced quoting — the shell will reject the command anyway
    return [inv for inv in map(parse_git_invocation, segments) if inv]


def gh_invocations(command):
    """Token lists following 'gh' in each shell segment of the command."""
    try:
        segments = tokenize_segments(command)
    except ValueError:
        return []
    return [seg[seg.index('gh') + 1:] for seg in segments if 'gh' in seg]


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
        return WORKTREE_REASON
    if creates:
        branch = get_current_branch(git_dir)
        if branch and branch != 'main':
            return BRANCH_CREATION_REASON.format(branch=branch)
    return None


def check_git_branch_policy(tool_name, tool_input):
    if tool_name != 'Bash':
        return
    for invocation in git_invocations(tool_input.get('command', '')):
        reason = evaluate_git_invocation(*invocation)
        if reason:
            _block(reason)


# --- End branch policy ----------------------------------------------------------


def check_git_commit_branch(tool_name, tool_input):
    if tool_name != 'Bash':
        return
    for subcommand, args, git_dir in git_invocations(tool_input.get('command', '')):
        if subcommand == 'commit' and get_current_branch(git_dir) == 'main':
            _block("Direct commits to the 'main' branch are not allowed. Please create a feature "
                   "branch first (e.g., 'git checkout -b feature/your-feature-name') and commit "
                   "your changes there, then create a pull request.")


def check_git_no_verify(tool_name, tool_input):
    if tool_name != 'Bash':
        return
    for subcommand, args, git_dir in git_invocations(tool_input.get('command', '')):
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


def check_git_commit_boilerplate(tool_name, tool_input):
    if tool_name != 'Bash':
        return
    command = tool_input.get('command', '')
    if (any(sub == 'commit' for sub, _, _ in git_invocations(command))
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


def add_timeout_to_git_commit(tool_name, tool_input):
    if tool_name != 'Bash':
        return
    if any(sub == 'commit' for sub, _, _ in git_invocations(tool_input.get('command', ''))):
        _require_timeout(tool_input, "Git commit", 900000)


def add_timeout_to_git_push(tool_name, tool_input):
    if tool_name != 'Bash':
        return
    if any(sub == 'push' for sub, _, _ in git_invocations(tool_input.get('command', ''))):
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

        add_timeout_to_git_commit(tool_name, tool_input)
        add_timeout_to_git_push(tool_name, tool_input)
        add_timeout_to_gh_run_watch(tool_name, tool_input)
        check_git_commit_branch(tool_name, tool_input)
        check_git_branch_policy(tool_name, tool_input)
        check_git_no_verify(tool_name, tool_input)
        check_git_commit_boilerplate(tool_name, tool_input)
        check_pr_create_boilerplate(tool_name, tool_input)
        check_pr_comment_boilerplate(tool_name, tool_input)

        sys.exit(0)
    except json.JSONDecodeError:
        sys.exit(0)
    except Exception:
        sys.exit(0)


if __name__ == '__main__':
    main()
