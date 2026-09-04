"""Token-based gating for the non-branch checks: commit-to-main, --no-verify,
boilerplate, and timeout enforcement."""

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "guardrails_hook_checks",
    Path(__file__).resolve().parent.parent / "hooks" / "guardrails_git_pre_tool_use.py",
)
hook = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(hook)


def run_check(check, command, monkeypatch, capsys, branch="feature/x", timeout=None):
    """Run a check function. Returns the block decision dict, or None if allowed."""
    monkeypatch.setattr(hook, "get_current_branch", lambda cwd=None: branch)
    tool_input = {"command": command}
    if timeout is not None:
        tool_input["timeout"] = timeout
    try:
        check("Bash", tool_input)
    except SystemExit:
        return json.loads(capsys.readouterr().out)
    return None


def mirror_git_frontends(commands):
    # Why: authenticated commands in this workspace route through the gitp and
    # git-as-app.sh wrappers instead of bare git; every check must hold for
    # those spellings too or it is bypassable by spelling alone (sc-1266).
    mirrored = []
    for cmd in commands:
        mirrored.append(cmd)
        for variant in (cmd.replace("git ", "gitp "),
                        cmd.replace("git ", "git-as-app.sh developer ")):
            if variant != cmd:
                mirrored.append(variant)
    return mirrored


GIT_WRAPPER_PREFIXES = ["gitp", "git-as-app.sh developer"]
GH_WRAPPER_PREFIXES = ["ghp", "gh-as-app.sh reviewer"]


# --- commit on main -------------------------------------------------------------

def test_commit_on_main_blocked(monkeypatch, capsys):
    decision = run_check(hook.check_git_commit_branch, "git commit -m 'x'",
                         monkeypatch, capsys, branch="main")
    assert decision is not None
    assert "main" in decision["reason"]


def test_commit_off_main_allowed(monkeypatch, capsys):
    assert run_check(hook.check_git_commit_branch, "git commit -m 'x'",
                     monkeypatch, capsys, branch="feature/x") is None


def test_quoted_git_commit_not_matched(monkeypatch, capsys):
    assert run_check(hook.check_git_commit_branch, 'echo "git commit"',
                     monkeypatch, capsys, branch="main") is None


def test_chained_commit_on_main_blocked(monkeypatch, capsys):
    assert run_check(hook.check_git_commit_branch, "git add . && git commit -m 'x'",
                     monkeypatch, capsys, branch="main") is not None


@pytest.mark.parametrize("prefix", GIT_WRAPPER_PREFIXES)
def test_commit_on_main_blocked_via_wrapper(prefix, monkeypatch, capsys):
    # Why: commit-to-main protection must hold when the commit is routed
    # through the gitp / git-as-app.sh wrappers, or the guardrail is
    # bypassable by spelling alone (sc-1266).
    decision = run_check(hook.check_git_commit_branch, f"{prefix} commit -m 'x'",
                         monkeypatch, capsys, branch="main")
    assert decision is not None
    assert "main" in decision["reason"]


@pytest.mark.parametrize("prefix", GIT_WRAPPER_PREFIXES)
def test_commit_off_main_allowed_via_wrapper(prefix, monkeypatch, capsys):
    # Why: widening front-end recognition must not tighten policy — a normal
    # wrapper commit on a feature branch stays allowed (sc-1266).
    assert run_check(hook.check_git_commit_branch, f"{prefix} commit -m 'x'",
                     monkeypatch, capsys, branch="feature/x") is None


def test_quoted_wrapper_commit_not_matched(monkeypatch, capsys):
    # Why: a quoted mention of a wrapper name is not an invocation; mirrors
    # the existing quoted-git protection for the new front-ends (sc-1266).
    assert run_check(hook.check_git_commit_branch, 'echo "gitp commit"',
                     monkeypatch, capsys, branch="main") is None


@pytest.mark.parametrize("prefix", GIT_WRAPPER_PREFIXES)
def test_chained_commit_on_main_blocked_via_wrapper(prefix, monkeypatch, capsys):
    # Why: wrapper commits hidden behind && chains must be caught the same
    # way chained bare-git commits already are (sc-1266).
    assert run_check(hook.check_git_commit_branch,
                     f"{prefix} add . && {prefix} commit -m 'x'",
                     monkeypatch, capsys, branch="main") is not None


# --- commit-to-main resolution inside a worktree ------------------------
#
# get_current_branch() resolves from wherever the subprocess actually runs
# ('-C <dir>', a payload cwd, or nothing). These tests fake a branch lookup
# that differs by git_dir so a bug that ignores the worktree's own directory
# (falling back to the primary checkout's branch) would misclassify a
# legitimate feature-branch commit inside a worktree as a commit to 'main'.

WORKTREE_DIR = "/repo/.worktrees/feature-x"
MAINREPO_DIR = "/repo"


def _worktree_aware_lookup(cwd=None):
    """Faithful stand-in for get_current_branch: only the two directories
    under test resolve to a branch at all. Everything else — including any
    directory a resolution bug might wrongly compute — returns None, exactly
    like the real lookup on a path that isn't a repo (OSError/SubprocessError
    fall through to `return None`). Both call sites fail OPEN on None, so a
    resolution bug that lands on the wrong directory surfaces as a wrongly-
    ALLOWED command instead of being silently absorbed as 'main' — a double
    that defaulted unrecognized directories to 'main' would mask exactly
    this class of bug, since a miscomputed directory would read as 'the
    primary checkout', which happens to be the answer most tests expect
    anyway."""
    if cwd == WORKTREE_DIR:
        return "feature/x"
    if cwd == MAINREPO_DIR:
        return "main"
    return None


def test_commit_via_dash_c_worktree_not_blocked_when_primary_on_main(monkeypatch, capsys):
    # Why: 'git -C <worktree>' must resolve the worktree's own branch, not
    # the primary checkout's 'main', even though the hook process's own OS
    # cwd never leaves the primary checkout.
    monkeypatch.setattr(hook, "get_current_branch", _worktree_aware_lookup)
    tool_input = {"command": f"git -C {WORKTREE_DIR} commit -m 'x'"}
    try:
        hook.check_git_commit_branch("Bash", tool_input)
    except SystemExit:
        pytest.fail("commit inside worktree via 'git -C' should not be blocked")


def test_commit_via_payload_cwd_in_worktree_not_blocked(monkeypatch, capsys):
    # Why: when the persistent shell's cwd has already moved into a worktree
    # from an earlier Bash call, the PreToolUse payload's 'cwd' field carries
    # that directory even though this hook process's own OS cwd never left
    # the primary checkout — a bare 'git commit' there must resolve via the
    # worktree's branch, not the primary checkout's 'main'.
    monkeypatch.setattr(hook, "get_current_branch", _worktree_aware_lookup)
    tool_input = {"command": "git commit -m 'x'"}
    try:
        hook.check_git_commit_branch("Bash", tool_input, WORKTREE_DIR)
    except SystemExit:
        pytest.fail("commit with payload cwd inside worktree should not be blocked")


def test_commit_via_leading_cd_fallback_not_blocked(monkeypatch, capsys):
    # Why: fallback path when the hook payload carries no usable cwd — a
    # leading 'cd <dir> &&' parsed out of the command string itself must
    # resolve the worktree's branch, matching the 'call sites updated to use
    # git -C explicitly' fix but covering any that still use plain 'cd'.
    monkeypatch.setattr(hook, "get_current_branch", _worktree_aware_lookup)
    tool_input = {"command": f"cd {WORKTREE_DIR} && git commit -m 'x'"}
    try:
        hook.check_git_commit_branch("Bash", tool_input)
    except SystemExit:
        pytest.fail("commit via leading-cd fallback should not be blocked")


def test_commit_still_blocked_on_actual_main_with_payload_cwd(monkeypatch, capsys):
    # Why: guards against a fix that stops resolving branches correctly at
    # all — a commit made with the payload cwd pointed at the primary
    # checkout (still on 'main') must remain blocked.
    monkeypatch.setattr(hook, "get_current_branch", _worktree_aware_lookup)
    tool_input = {"command": "git commit -m 'x'"}
    with pytest.raises(SystemExit):
        hook.check_git_commit_branch("Bash", tool_input, MAINREPO_DIR)
    decision = json.loads(capsys.readouterr().out)
    assert decision["decision"] == "block"
    assert "main" in decision["reason"]


# --- directory-resolution precedence: a command's own 'cd' must outrank a
# stale payload cwd
# -----------------------------------------------------------------------

def test_commit_via_cd_to_main_repo_blocked_despite_stale_payload_cwd(monkeypatch, capsys):
    # Why: the guard-bypass this round fixes — 'cd <main-repo> && git commit'
    # must BLOCK even when the payload's cwd (a stale snapshot from before
    # this command ran, e.g. left over from an earlier Bash call into a
    # worktree) points elsewhere. The command's own 'cd' reflects what THIS
    # command actually does; the payload cwd cannot override that.
    monkeypatch.setattr(hook, "get_current_branch", _worktree_aware_lookup)
    tool_input = {"command": f"cd {MAINREPO_DIR} && git commit -m 'x'"}
    with pytest.raises(SystemExit):
        hook.check_git_commit_branch("Bash", tool_input, WORKTREE_DIR)
    decision = json.loads(capsys.readouterr().out)
    assert decision["decision"] == "block"
    assert "main" in decision["reason"]


def test_commit_via_cd_to_worktree_not_blocked_despite_stale_payload_cwd(monkeypatch, capsys):
    # Why: the mirror bug — the residual deadlock this whole effort exists to
    # remove, surviving in the 'cd' form. 'cd <worktree-on-feature-x> &&
    # git commit' must NOT block even when the payload cwd still points at
    # the primary checkout (on 'main').
    monkeypatch.setattr(hook, "get_current_branch", _worktree_aware_lookup)
    tool_input = {"command": f"cd {WORKTREE_DIR} && git commit -m 'x'"}
    try:
        hook.check_git_commit_branch("Bash", tool_input, MAINREPO_DIR)
    except SystemExit:
        pytest.fail("commit via cd into a feature-branch worktree should not "
                    "be blocked despite a stale payload cwd on main")


def test_commit_via_multi_segment_cd_chain_blocked(monkeypatch, capsys):
    # Why: cd-tracking must scan the WHOLE command chain, not just a leading
    # segment — 'git fetch && cd <main-repo> && git commit' puts the 'cd'
    # second, after an earlier git invocation, and the old leading_cd_dir
    # never saw it.
    monkeypatch.setattr(hook, "get_current_branch", _worktree_aware_lookup)
    tool_input = {"command": f"git fetch && cd {MAINREPO_DIR} && git commit -m 'x'"}
    with pytest.raises(SystemExit):
        hook.check_git_commit_branch("Bash", tool_input)
    decision = json.loads(capsys.readouterr().out)
    assert decision["decision"] == "block"
    assert "main" in decision["reason"]


# --- directory-resolution precedence: composed relative 'cd'/'-C' chains
# -----------------------------------------------------------------------
#
# resolve_default_dir replays the WHOLE 'cd' chain, accumulating the
# resolved directory as it goes, rather than resolving only the last 'cd'
# against a fixed payload snapshot — a relative argument to a later 'cd' or
# '-C' must resolve against the directory the previous 'cd' established,
# not against the shell's cwd from before any of them ran.

def test_commit_via_abs_repo_then_relative_subdir_blocked(monkeypatch, capsys):
    # Why: the second 'cd's relative argument ('subdir/..') must resolve
    # against the directory the FIRST 'cd' just established, not against a
    # stale payload cwd left over from an earlier Bash call into a worktree.
    # A net-no-op subdir hop off the main repo must still resolve to exactly
    # MAINREPO_DIR and BLOCK.
    monkeypatch.setattr(hook, "get_current_branch", _worktree_aware_lookup)
    tool_input = {"command": f"cd {MAINREPO_DIR} && cd subdir/.. && git commit -m 'x'"}
    with pytest.raises(SystemExit):
        hook.check_git_commit_branch("Bash", tool_input, WORKTREE_DIR)
    decision = json.loads(capsys.readouterr().out)
    assert decision["decision"] == "block"
    assert "main" in decision["reason"]


def test_commit_via_parent_then_relative_repo_name_blocked(monkeypatch, capsys):
    # Why: reaching the main repo via 'cd <parent> && cd <name>' (the
    # sibling-checkout idiom) must resolve the second, relative 'cd' against
    # the parent directory the first 'cd' established, landing on exactly
    # MAINREPO_DIR — not against a stale payload cwd pointed at a worktree.
    monkeypatch.setattr(hook, "get_current_branch", _worktree_aware_lookup)
    tool_input = {"command": "cd / && cd repo && git commit -m 'x'"}
    with pytest.raises(SystemExit):
        hook.check_git_commit_branch("Bash", tool_input, WORKTREE_DIR)
    decision = json.loads(capsys.readouterr().out)
    assert decision["decision"] == "block"
    assert "main" in decision["reason"]


def test_commit_via_parent_cd_then_relative_dash_c_blocked(monkeypatch, capsys):
    # Why: an explicit 'git -C <relative>' must resolve against the
    # accumulated chain position (the preceding 'cd /'), not against a stale
    # payload cwd — 'git -C repo' from '/' must land on exactly MAINREPO_DIR.
    monkeypatch.setattr(hook, "get_current_branch", _worktree_aware_lookup)
    tool_input = {"command": "cd / && git -C repo commit -m 'x'"}
    with pytest.raises(SystemExit):
        hook.check_git_commit_branch("Bash", tool_input, WORKTREE_DIR)
    decision = json.loads(capsys.readouterr().out)
    assert decision["decision"] == "block"
    assert "main" in decision["reason"]


def test_checkout_dash_b_via_parent_then_relative_worktree_name_blocked(monkeypatch, capsys):
    # Why: reaching a worktree via 'cd <parent> && cd <name>' must resolve
    # the branch-creation guard's directory the same way as a commit does —
    # creating a new branch while already on a non-main branch (here: the
    # worktree's feature/x) must BLOCK, and must do so from the exact
    # worktree directory the chain computes, not a stale payload cwd pointed
    # at the main repo.
    monkeypatch.setattr(hook, "get_current_branch", _worktree_aware_lookup)
    tool_input = {"command": "cd /repo/.worktrees && cd feature-x && git checkout -b feature/z"}
    with pytest.raises(SystemExit):
        hook.check_git_branch_policy("Bash", tool_input, MAINREPO_DIR)
    decision = json.loads(capsys.readouterr().out)
    assert decision["decision"] == "block"
    assert "feature/x" in decision["reason"]


def test_commit_via_worktree_then_cd_dot_allowed(monkeypatch, capsys):
    # Why: deadlock mirror of the above — 'cd <worktree> && cd .' is a
    # net-no-op relative hop that must still resolve to exactly WORKTREE_DIR
    # and stay ALLOWED, even with a stale payload cwd pointed at the main
    # repo (the residual deadlock this whole effort exists to remove).
    monkeypatch.setattr(hook, "get_current_branch", _worktree_aware_lookup)
    tool_input = {"command": f"cd {WORKTREE_DIR} && cd . && git commit -m 'x'"}
    try:
        hook.check_git_commit_branch("Bash", tool_input, MAINREPO_DIR)
    except SystemExit:
        pytest.fail("commit via cd-then-cd-dot into a worktree should not be blocked "
                    "despite a stale payload cwd on the main repo")


# --- get_current_branch: real subprocess behavior, no mock -----------------
#
# The tests above all substitute a double for get_current_branch. These
# exercise the REAL function against real temp git repos so the None-on-
# bad-path fallback (OSError/SubprocessError -> None) has coverage that
# isn't mediated by a mock at all.

def test_get_current_branch_none_for_non_git_directory(tmp_path):
    assert hook.get_current_branch(str(tmp_path)) is None


def test_get_current_branch_none_for_nonexistent_directory():
    assert hook.get_current_branch("/no/such/directory/at/all") is None


def test_get_current_branch_reads_real_repo(tmp_path):
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "checkout", "-b", "feature/real"],
                   check=True, capture_output=True)
    assert hook.get_current_branch(str(tmp_path)) == "feature/real"


def test_get_current_branch_none_for_falsy_cwd():
    # Why: a falsy cwd (None, or '') means no caller ever resolved a real
    # directory. subprocess.run(cwd=None) would silently inherit the hook
    # process's own OS cwd, which _resolve_path's docstring calls "never a
    # valid resolution base" — this must refuse outright instead, without
    # even attempting the subprocess call.
    assert hook.get_current_branch(None) is None
    assert hook.get_current_branch("") is None


# --- Required Change 5: regression coverage for the round-7 review -------------
#
# Directory-resolution gaps that let an unresolvable or wrongly-scoped
# directory read as "safe to proceed" instead of triggering a refusal.

def test_commit_check_absent_payload_cwd_relative_cd_blocks(monkeypatch, capsys):
    # Why: with no payload cwd and only a relative 'cd' argument, there is no
    # base to resolve against — must come out unresolvable/blocked, never
    # silently resolved against the hook process's own OS cwd.
    monkeypatch.setattr(hook, "get_current_branch", _worktree_aware_lookup)
    tool_input = {"command": "cd subdir && git commit -m 'x'"}
    with pytest.raises(SystemExit):
        hook.check_git_commit_branch("Bash", tool_input)
    decision = json.loads(capsys.readouterr().out)
    assert decision["decision"] == "block"
    assert "Could not determine the current branch" in decision["reason"]


def test_commit_check_cd_tilde_blocks(monkeypatch, capsys):
    # Why: '~' resolves via os.path.expanduser to some real absolute path
    # (not one of the fake lookup's two recognized directories), so the
    # lookup returns None and the commit must be blocked as unresolvable —
    # proving '~' is actually expanded rather than treated as a literal,
    # nonexistent-looking relative path.
    monkeypatch.setattr(hook, "get_current_branch", _worktree_aware_lookup)
    tool_input = {"command": "cd ~/some-repo && git commit -m 'x'"}
    with pytest.raises(SystemExit):
        hook.check_git_commit_branch("Bash", tool_input, MAINREPO_DIR)
    decision = json.loads(capsys.readouterr().out)
    assert decision["decision"] == "block"
    assert "Could not determine the current branch" in decision["reason"]


def test_commit_check_cd_dollar_var_blocks(monkeypatch, capsys):
    # Why: this hook cannot safely expand shell variables — a '$'-bearing
    # 'cd' argument must be treated as unresolvable, not silently mangled
    # into some other (possibly-real) directory.
    monkeypatch.setattr(hook, "get_current_branch", _worktree_aware_lookup)
    tool_input = {"command": "cd $HOME/repo && git commit -m 'x'"}
    with pytest.raises(SystemExit):
        hook.check_git_commit_branch("Bash", tool_input, MAINREPO_DIR)
    decision = json.loads(capsys.readouterr().out)
    assert decision["decision"] == "block"
    assert "Could not determine the current branch" in decision["reason"]


def test_commit_check_cd_dash_p_flag_skipped_resolves_real_dir(monkeypatch, capsys):
    # Why: 'cd -P <dir>' must resolve to <dir>, not treat the '-P' flag
    # itself as the directory operand — this is a positive case: the real
    # worktree directory is correctly identified, so the commit is allowed.
    monkeypatch.setattr(hook, "get_current_branch", _worktree_aware_lookup)
    tool_input = {"command": f"cd -P {WORKTREE_DIR} && git commit -m 'x'"}
    try:
        hook.check_git_commit_branch("Bash", tool_input, MAINREPO_DIR)
    except SystemExit:
        pytest.fail("'cd -P <dir>' should resolve <dir>, not the '-P' flag itself")


def test_commit_check_cd_dash_bare_blocks(monkeypatch, capsys):
    # Why: 'cd -' (previous directory) has no meaning to this hook — it
    # tracks no shell directory history — so it must be unresolvable/block.
    monkeypatch.setattr(hook, "get_current_branch", _worktree_aware_lookup)
    tool_input = {"command": "cd - && git commit -m 'x'"}
    with pytest.raises(SystemExit):
        hook.check_git_commit_branch("Bash", tool_input, MAINREPO_DIR)
    decision = json.loads(capsys.readouterr().out)
    assert decision["decision"] == "block"
    assert "Could not determine the current branch" in decision["reason"]


def test_commit_check_cd_inside_subshell_not_leaked_outside(monkeypatch, capsys):
    # Why: the reproducer from the round-7 review —
    # '(cd .worktrees/feature-x && git status) && git commit -m x' — a 'cd'
    # inside '( ... )' must not affect a git invocation outside the closing
    # ')'. The outer commit still runs at MAINREPO_DIR (on 'main') and must
    # be blocked, not silently allowed via the inner worktree's branch.
    monkeypatch.setattr(hook, "get_current_branch", _worktree_aware_lookup)
    tool_input = {"command": f"(cd {WORKTREE_DIR} && git status) && git commit -m 'x'"}
    with pytest.raises(SystemExit):
        hook.check_git_commit_branch("Bash", tool_input, MAINREPO_DIR)
    decision = json.loads(capsys.readouterr().out)
    assert decision["decision"] == "block"
    assert "main" in decision["reason"]


def test_commit_check_cd_inside_subshell_still_applies_inside(monkeypatch, capsys):
    # Why: mirror of the above — a git invocation still INSIDE the same
    # '( ... )' scope as the 'cd' must see its effect (the worktree's own
    # branch), proving the fix scopes the leak rather than discarding the
    # cd entirely.
    monkeypatch.setattr(hook, "get_current_branch", _worktree_aware_lookup)
    tool_input = {"command": f"(cd {WORKTREE_DIR} && git commit -m 'x')"}
    try:
        hook.check_git_commit_branch("Bash", tool_input, MAINREPO_DIR)
    except SystemExit:
        pytest.fail("commit inside the same '(...)' scope as its 'cd' should not be blocked")


def test_commit_check_cd_before_pipe_not_leaked_after(monkeypatch, capsys):
    # Why: each pipeline stage forks its own subshell — a 'cd' that is
    # itself one side of a '|' must not affect a git invocation after the
    # pipe, even joined by '&&'. If the leak happened, the commit would
    # wrongly resolve to the worktree's 'feature/x' and be allowed; it must
    # instead still resolve to MAINREPO_DIR ('main') and block.
    monkeypatch.setattr(hook, "get_current_branch", _worktree_aware_lookup)
    tool_input = {"command": f"cd {WORKTREE_DIR} | true && git commit -m 'x'"}
    with pytest.raises(SystemExit):
        hook.check_git_commit_branch("Bash", tool_input, MAINREPO_DIR)
    decision = json.loads(capsys.readouterr().out)
    assert decision["decision"] == "block"
    assert "main" in decision["reason"]


def test_commit_check_cd_not_actually_run_due_to_short_circuit(monkeypatch, capsys):
    # Why: 'false && cd <dir>; git commit' never actually runs the 'cd' in a
    # real shell (short-circuited by 'false &&'). This hook does token-level
    # pattern matching, not full shell interpretation, and does not model
    # '&&' short-circuiting (same class of gap as the pre-existing,
    # out-of-scope 'eval'/'bash -c' limitations) — it replays the 'cd'
    # unconditionally. Pin down that actual, current behavior here so a
    # future change to this doesn't silently alter it unnoticed.
    monkeypatch.setattr(hook, "get_current_branch", _worktree_aware_lookup)
    tool_input = {"command": f"false && cd {WORKTREE_DIR} ; git commit -m 'x'"}
    try:
        hook.check_git_commit_branch("Bash", tool_input, MAINREPO_DIR)
    except SystemExit:
        pytest.fail("current implementation replays 'cd' unconditionally, "
                    "regardless of preceding '&&' short-circuiting")


# --- Required Change 5: the severe finding, reproduced end-to-end ------------
#
# A detached worktree's 'git branch --show-current' returns '' (empty
# string), which the pre-fix code treated as falsy-therefore-"not main" and
# let 'git branch -f main HEAD' proceed, force-moving 'main' to an
# agent-authored commit. This drives the REAL get_current_branch against a
# REAL fixture repo (built under pytest's own tmp_path, entirely outside
# this repo's working tree) through the REAL hook function — no mocks.

def test_worktree_branch_force_main_blocked_end_to_end(tmp_path):
    mainrepo = tmp_path / "mainrepo"
    wt = tmp_path / "wt"

    result = subprocess.run(["git", "init", "-b", "main", str(mainrepo)],
                            capture_output=True, text=True)
    assert result.returncode == 0, f"git init failed: {result.stderr}"
    assert (mainrepo / ".git").is_dir()

    subprocess.run(["git", "-C", str(mainrepo), "config", "user.email", "test@test.com"],
                   check=True, capture_output=True)
    subprocess.run(["git", "-C", str(mainrepo), "config", "user.name", "test"],
                   check=True, capture_output=True)
    (mainrepo / "file.txt").write_text("hello\n")
    subprocess.run(["git", "-C", str(mainrepo), "add", "file.txt"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(mainrepo), "commit", "-q", "-m", "initial"],
                   check=True, capture_output=True)

    wt_add = subprocess.run(["git", "-C", str(mainrepo), "worktree", "add", "--detach", str(wt)],
                            capture_output=True, text=True)
    assert wt_add.returncode == 0, f"worktree add failed: {wt_add.stderr}"

    # Confirm the fixture actually reproduces the empty-string detached-HEAD
    # branch name that caused the original bug.
    assert hook.get_current_branch(str(wt)) == ""

    command = f"git -C {wt} branch -f main HEAD"
    with pytest.raises(SystemExit):
        hook.check_git_branch_policy("Bash", {"command": command}, str(mainrepo))


# --- --no-verify -----------------------------------------------------------------

BLOCKED_NO_VERIFY = mirror_git_frontends([
    "git commit --no-verify -m 'x'",
    "git push --no-verify",
    "git commit -n -m 'x'",
    "git add . && git commit --no-verify -m 'x'",
    "git -C /somedir commit --no-verify -m 'x'",
])


@pytest.mark.parametrize("command", BLOCKED_NO_VERIFY)
def test_no_verify_blocked(command, monkeypatch, capsys):
    decision = run_check(hook.check_git_no_verify, command, monkeypatch, capsys)
    assert decision is not None, f"expected block: {command}"
    assert "no-verify" in decision["reason"]


ALLOWED_NO_VERIFY = mirror_git_frontends([
    "git commit -m 'mentions --no-verify in the message'",
    "git commit -m 'x'",
    "grep -r no-verify docs/",
    "git push origin feature/x",
    "git log -n 5",
])


@pytest.mark.parametrize("command", ALLOWED_NO_VERIFY)
def test_no_verify_allowed(command, monkeypatch, capsys):
    assert run_check(hook.check_git_no_verify, command, monkeypatch, capsys) is None


# --- boilerplate ------------------------------------------------------------------

def test_commit_boilerplate_blocked(monkeypatch, capsys):
    decision = run_check(hook.check_git_commit_boilerplate,
                         'git commit -m "feat: x\n\nGenerated with Claude Code"',
                         monkeypatch, capsys)
    assert decision is not None


def test_commit_boilerplate_without_commit_allowed(monkeypatch, capsys):
    assert run_check(hook.check_git_commit_boilerplate,
                     'echo "Generated with Claude Code"', monkeypatch, capsys) is None


def test_clean_commit_allowed(monkeypatch, capsys):
    assert run_check(hook.check_git_commit_boilerplate,
                     'git commit -m "feat: add widget"', monkeypatch, capsys) is None


@pytest.mark.parametrize("prefix", GIT_WRAPPER_PREFIXES)
def test_commit_boilerplate_blocked_via_wrapper(prefix, monkeypatch, capsys):
    # Why: AI-boilerplate screening on commit messages must apply to
    # wrapper-routed commits identically to bare git (sc-1266).
    decision = run_check(hook.check_git_commit_boilerplate,
                         f'{prefix} commit -m "feat: x\n\nGenerated with Claude Code"',
                         monkeypatch, capsys)
    assert decision is not None


@pytest.mark.parametrize("prefix", GIT_WRAPPER_PREFIXES)
def test_clean_commit_allowed_via_wrapper(prefix, monkeypatch, capsys):
    # Why: clean wrapper commits must pass — recognition widened, policy
    # unchanged (sc-1266).
    assert run_check(hook.check_git_commit_boilerplate,
                     f'{prefix} commit -m "feat: add widget"', monkeypatch, capsys) is None


def test_pr_create_boilerplate_blocked(monkeypatch, capsys):
    decision = run_check(hook.check_pr_create_boilerplate,
                         'gh pr create --title t --body "AI-generated implementation"',
                         monkeypatch, capsys)
    assert decision is not None


def test_pr_create_clean_allowed(monkeypatch, capsys):
    assert run_check(hook.check_pr_create_boilerplate,
                     'gh pr create --title t --body "Adds widget"',
                     monkeypatch, capsys) is None


def test_pr_create_boilerplate_without_gh_allowed(monkeypatch, capsys):
    assert run_check(hook.check_pr_create_boilerplate,
                     'echo "gh pr create AI-generated"', monkeypatch, capsys) is None


@pytest.mark.parametrize("prefix", GH_WRAPPER_PREFIXES)
def test_pr_create_boilerplate_blocked_via_wrapper(prefix, monkeypatch, capsys):
    # Why: PR-description boilerplate screening must apply when PRs are
    # created through ghp / gh-as-app.sh, the required path in this
    # workspace (sc-1266).
    decision = run_check(hook.check_pr_create_boilerplate,
                         f'{prefix} pr create --title t --body "AI-generated implementation"',
                         monkeypatch, capsys)
    assert decision is not None


@pytest.mark.parametrize("prefix", GH_WRAPPER_PREFIXES)
def test_pr_create_clean_allowed_via_wrapper(prefix, monkeypatch, capsys):
    # Why: clean wrapper-routed PR creation stays allowed (sc-1266).
    assert run_check(hook.check_pr_create_boilerplate,
                     f'{prefix} pr create --title t --body "Adds widget"',
                     monkeypatch, capsys) is None


def test_pr_create_boilerplate_without_wrapper_invocation_allowed(monkeypatch, capsys):
    # Why: quoted wrapper mention is not an invocation — no false positive
    # from the widened recognition (sc-1266).
    assert run_check(hook.check_pr_create_boilerplate,
                     'echo "ghp pr create AI-generated"', monkeypatch, capsys) is None


def test_pr_comment_boilerplate_blocked(monkeypatch, capsys):
    decision = run_check(
        hook.check_pr_comment_boilerplate,
        'gh api repos/owner/repo/issues/5/comments -f body="Generated by Claude"',
        monkeypatch, capsys)
    assert decision is not None


def test_pr_comment_clean_allowed(monkeypatch, capsys):
    assert run_check(
        hook.check_pr_comment_boilerplate,
        'gh api repos/owner/repo/issues/5/comments -f body="Fixed in abc123"',
        monkeypatch, capsys) is None


@pytest.mark.parametrize("prefix", GH_WRAPPER_PREFIXES)
def test_pr_comment_boilerplate_blocked_via_wrapper(prefix, monkeypatch, capsys):
    # Why: PR-comment boilerplate screening must apply to wrapper-routed
    # gh api comment calls (sc-1266).
    decision = run_check(
        hook.check_pr_comment_boilerplate,
        f'{prefix} api repos/owner/repo/issues/5/comments -f body="Generated by Claude"',
        monkeypatch, capsys)
    assert decision is not None


@pytest.mark.parametrize("prefix", GH_WRAPPER_PREFIXES)
def test_pr_comment_clean_allowed_via_wrapper(prefix, monkeypatch, capsys):
    # Why: clean wrapper-routed PR comments stay allowed (sc-1266).
    assert run_check(
        hook.check_pr_comment_boilerplate,
        f'{prefix} api repos/owner/repo/issues/5/comments -f body="Fixed in abc123"',
        monkeypatch, capsys) is None


# --- timeouts ---------------------------------------------------------------------

def test_commit_requires_timeout(monkeypatch, capsys):
    decision = run_check(hook.add_timeout_to_git_commit, "git commit -m 'x'",
                         monkeypatch, capsys)
    assert decision is not None
    assert "900000" in decision["reason"]


def test_commit_with_timeout_allowed(monkeypatch, capsys):
    assert run_check(hook.add_timeout_to_git_commit, "git commit -m 'x'",
                     monkeypatch, capsys, timeout=900000) is None


def test_quoted_git_commit_no_timeout_required(monkeypatch, capsys):
    assert run_check(hook.add_timeout_to_git_commit, 'echo "git commit"',
                     monkeypatch, capsys) is None


@pytest.mark.parametrize("prefix", GIT_WRAPPER_PREFIXES)
def test_commit_requires_timeout_via_wrapper(prefix, monkeypatch, capsys):
    # Why: the commit timeout requirement must fire for wrapper commits too,
    # or wrapper-routed commits silently lose the long-timeout protection
    # (sc-1266).
    decision = run_check(hook.add_timeout_to_git_commit, f"{prefix} commit -m 'x'",
                         monkeypatch, capsys)
    assert decision is not None
    assert "900000" in decision["reason"]


@pytest.mark.parametrize("prefix", GIT_WRAPPER_PREFIXES)
def test_commit_with_timeout_allowed_via_wrapper(prefix, monkeypatch, capsys):
    # Why: wrapper commits carrying the required timeout pass unchanged
    # (sc-1266).
    assert run_check(hook.add_timeout_to_git_commit, f"{prefix} commit -m 'x'",
                     monkeypatch, capsys, timeout=900000) is None


def test_push_requires_timeout(monkeypatch, capsys):
    decision = run_check(hook.add_timeout_to_git_push, "git push origin x",
                         monkeypatch, capsys)
    assert decision is not None
    assert "900000" in decision["reason"]


def test_push_with_timeout_allowed(monkeypatch, capsys):
    assert run_check(hook.add_timeout_to_git_push, "git push origin x",
                     monkeypatch, capsys, timeout=900000) is None


@pytest.mark.parametrize("prefix", GIT_WRAPPER_PREFIXES)
def test_push_requires_timeout_via_wrapper(prefix, monkeypatch, capsys):
    # Why: the push timeout requirement must fire for wrapper pushes too
    # (sc-1266).
    decision = run_check(hook.add_timeout_to_git_push, f"{prefix} push origin x",
                         monkeypatch, capsys)
    assert decision is not None
    assert "900000" in decision["reason"]


@pytest.mark.parametrize("prefix", GIT_WRAPPER_PREFIXES)
def test_push_with_timeout_allowed_via_wrapper(prefix, monkeypatch, capsys):
    # Why: wrapper pushes carrying the required timeout pass unchanged
    # (sc-1266).
    assert run_check(hook.add_timeout_to_git_push, f"{prefix} push origin x",
                     monkeypatch, capsys, timeout=900000) is None


def test_gh_run_watch_requires_timeout(monkeypatch, capsys):
    decision = run_check(hook.add_timeout_to_gh_run_watch, "gh run watch 123",
                         monkeypatch, capsys)
    assert decision is not None
    assert "1800000" in decision["reason"]


def test_gh_run_watch_with_timeout_allowed(monkeypatch, capsys):
    assert run_check(hook.add_timeout_to_gh_run_watch, "gh run watch 123",
                     monkeypatch, capsys, timeout=1800000) is None


def test_quoted_gh_run_watch_no_timeout_required(monkeypatch, capsys):
    assert run_check(hook.add_timeout_to_gh_run_watch, 'echo "gh run watch"',
                     monkeypatch, capsys) is None


@pytest.mark.parametrize("prefix", GH_WRAPPER_PREFIXES)
def test_gh_run_watch_requires_timeout_via_wrapper(prefix, monkeypatch, capsys):
    # Why: the run-watch timeout requirement must fire when routed through
    # ghp / gh-as-app.sh (sc-1266).
    decision = run_check(hook.add_timeout_to_gh_run_watch, f"{prefix} run watch 123",
                         monkeypatch, capsys)
    assert decision is not None
    assert "1800000" in decision["reason"]


@pytest.mark.parametrize("prefix", GH_WRAPPER_PREFIXES)
def test_gh_run_watch_with_timeout_allowed_via_wrapper(prefix, monkeypatch, capsys):
    # Why: wrapper run-watch carrying the required timeout passes unchanged
    # (sc-1266).
    assert run_check(hook.add_timeout_to_gh_run_watch, f"{prefix} run watch 123",
                     monkeypatch, capsys, timeout=1800000) is None


def test_quoted_wrapper_run_watch_no_timeout_required(monkeypatch, capsys):
    # Why: quoted wrapper mention must not trigger the timeout requirement
    # (sc-1266).
    assert run_check(hook.add_timeout_to_gh_run_watch, 'echo "ghp run watch"',
                     monkeypatch, capsys) is None
