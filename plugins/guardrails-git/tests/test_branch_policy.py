import importlib.util
import json
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "guardrails_hook",
    Path(__file__).resolve().parent.parent / "hooks" / "guardrails_git_pre_tool_use.py",
)
hook = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(hook)


def run_policy(command, current_branch, monkeypatch, capsys):
    """Run the branch policy check. Returns the block decision dict, or None if allowed."""
    monkeypatch.setattr(hook, "get_current_branch", lambda git_dir=None: current_branch)
    try:
        hook.check_git_branch_policy("Bash", {"command": command})
    except SystemExit:
        return json.loads(capsys.readouterr().out)
    return None


BLOCKED_CREATION_OFF_MAIN = [
    "git checkout -b feature/new-thing",
    "git checkout -B feature/new-thing",
    "git checkout --orphan feature/new-thing",
    "git branch chore/sc-1056-disable-faro-telemetry origin/main",
    "git branch feature/new-thing",
    "git branch -f feature/new-thing origin/main",
    "git switch -c feature/new-thing",
    "git switch -C feature/new-thing",
    "git switch --create feature/new-thing",
    "git switch --force-create feature/new-thing",
    "echo hi && git branch x y",
    "ls; git switch -c feature/new-thing",
    "git fetch | git branch feature/new-thing",
    "GIT_TRACE=1 git branch feature/new-thing",
    "env git branch feature/new-thing",
    "git checkout -bfeature/new-thing",
    "git checkout -Bfeature/new-thing",
    "git switch -cfeature/new-thing",
    "git switch -Cfeature/new-thing",
    "git switch -c=feature/new-thing",
    "git switch --create=feature/new-thing",
]


@pytest.mark.parametrize("command", BLOCKED_CREATION_OFF_MAIN)
def test_branch_creation_blocked_off_main(command, monkeypatch, capsys):
    decision = run_policy(command, "feature/existing", monkeypatch, capsys)
    assert decision is not None, f"expected block: {command}"
    assert decision["decision"] == "block"
    assert "New branches should only be created from 'main'" in decision["reason"]
    assert "feature/existing" in decision["reason"]


@pytest.mark.parametrize("command", BLOCKED_CREATION_OFF_MAIN)
def test_branch_creation_allowed_on_main(command, monkeypatch, capsys):
    assert run_policy(command, "main", monkeypatch, capsys) is None


ALLOWED_NON_CREATION = [
    "git branch",
    "git branch -a",
    "git branch -l",
    "git branch --list 'feature/*'",
    "git branch -vv",
    "git branch --show-current",
    "git branch -D feature/old",
    "git branch -d feature/old",
    "git branch --delete feature/old",
    "git branch -m old new",
    "git branch -M old new",
    "git branch -c old new",
    "git branch --copy old new",
    "git branch --merged main",
    "git branch --no-merged",
    "git branch --contains abc123",
    "git branch -u origin/feature/x",
    "git branch --set-upstream-to=origin/feature/x",
    "git branch --unset-upstream",
    "git branch --sort=-committerdate --list",
    "git branch --edit-description",
    "git branch -uorigin/feature/x mybranch",
    "git branch -c=old new",
    "git checkout feature/existing-branch",
    "git switch feature/existing-branch",
    "git switch -",
    "git status && git log --oneline",
    'echo "git branch x"',
    "git stash list",
]


@pytest.mark.parametrize("command", ALLOWED_NON_CREATION)
def test_non_creation_forms_allowed(command, monkeypatch, capsys):
    assert run_policy(command, "feature/existing", monkeypatch, capsys) is None


BLOCKED_MAIN_CHECKOUT = [
    "git checkout main",
    "git switch main",
    "git checkout -q main",
    "cd /repo && git checkout main",
]


@pytest.mark.parametrize("command", BLOCKED_MAIN_CHECKOUT)
def test_checkout_main_blocked(command, monkeypatch, capsys):
    decision = run_policy(command, "feature/existing", monkeypatch, capsys)
    assert decision is not None, f"expected block: {command}"
    assert "checkout the main branch" in decision["reason"]


BLOCKED_WORKTREE = [
    "git worktree add ../wt",
    "git worktree add ../wt -b feature/new",
    "git worktree add --detach ../wt",
    "git worktree list",
    "git worktree remove ../wt",
    "git worktree prune",
    "git worktree",
]


@pytest.mark.parametrize("command", BLOCKED_WORKTREE)
def test_all_worktree_commands_blocked(command, monkeypatch, capsys):
    decision = run_policy(command, "feature/existing", monkeypatch, capsys)
    assert decision is not None, f"expected block: {command}"
    assert "worktree" in decision["reason"]


def test_git_dash_c_dir_passed_to_branch_lookup(monkeypatch, capsys):
    seen = {}

    def fake_lookup(git_dir=None):
        seen["git_dir"] = git_dir
        return "feature/existing"

    monkeypatch.setattr(hook, "get_current_branch", fake_lookup)
    with pytest.raises(SystemExit):
        hook.check_git_branch_policy("Bash", {"command": "git -C /some/dir branch x"})
    capsys.readouterr()
    assert seen["git_dir"] == "/some/dir"


def test_unparseable_command_allowed(monkeypatch, capsys):
    # Unbalanced quoting can't be tokenized; the shell rejects it anyway.
    assert run_policy('echo "unclosed', "feature/existing", monkeypatch, capsys) is None


def test_non_bash_tool_ignored(monkeypatch, capsys):
    assert run_policy("", "feature/existing", monkeypatch, capsys) is None
    monkeypatch.setattr(hook, "get_current_branch", lambda git_dir=None: "feature/x")
    assert hook.check_git_branch_policy("Edit", {"command": "git branch x"}) is None


def test_branch_lookup_failure_allows(monkeypatch, capsys):
    assert run_policy("git branch new-thing", None, monkeypatch, capsys) is None
