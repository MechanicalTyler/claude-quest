"""Token-based gating for the non-branch checks: commit-to-main, --no-verify,
boilerplate, and timeout enforcement."""

import importlib.util
import json
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
    monkeypatch.setattr(hook, "get_current_branch", lambda git_dir=None: branch)
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
