# tests/test_hub_client.py
import importlib.util
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


def load_client():
    spec = importlib.util.spec_from_file_location(
        "attention_hub_client",
        Path(__file__).parent.parent / "hooks" / "attention_hub_client.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(autouse=True)
def isolated_dev_workflow_state(tmp_path, monkeypatch):
    """Redirect DEV_WORKFLOW_STATE_DIR on every loaded client to a tmp_path
    dir so no test ever globs the developer's real ~/.claude checkpoints —
    the constant binds Path.home() at module exec, which happens inside each
    test via load_client(), so the redirect wraps load_client itself."""
    state_dir = tmp_path / "dev-workflow-state-default"
    original = load_client

    def load_redirected():
        mod = original()
        mod.DEV_WORKFLOW_STATE_DIR = state_dir
        return mod

    monkeypatch.setattr(sys.modules[__name__], "load_client", load_redirected)
    return state_dir


# --- Payload identity fields ---

def test_payload_contains_identity_fields(monkeypatch):
    # Why: the dashboard can only label a row if every event identifies the session,
    # project, host, state, and time. Guards against silently dropping a field the
    # hub needs to render "which instance is waiting on me".
    monkeypatch.delenv("CLAUDE_HOST_LABEL", raising=False)
    client = load_client()
    payload = client.build_event_payload(
        "sess-1", "/home/user/my-project", "waiting", "Need permission?"
    )
    assert payload["session_id"] == "sess-1"
    assert payload["project"] == "my-project"
    assert payload["state"] == "waiting"
    assert payload["message"] == "Need permission?"
    assert payload["host"]  # non-empty hostname fallback
    assert payload["timestamp"]


def test_payload_host_label_env_override(monkeypatch):
    # Why: docker containers and remote servers need friendly names instead of
    # generated hostnames; CLAUDE_HOST_LABEL must win over the machine hostname.
    monkeypatch.setenv("CLAUDE_HOST_LABEL", "docker-build-box")
    client = load_client()
    payload = client.build_event_payload("s", "/srv/app", "working", None)
    assert payload["host"] == "docker-build-box"


def test_payload_truncates_long_message(monkeypatch):
    # Why: dashboard rows show a snippet, not a full transcript; unbounded messages
    # would bloat hub state and the JSON persistence file.
    monkeypatch.delenv("CLAUDE_HOST_LABEL", raising=False)
    client = load_client()
    payload = client.build_event_payload("s", "/srv/app", "needs_input", "x" * 1000)
    assert len(payload["message"]) <= 200


def test_payload_empty_message_allowed(monkeypatch):
    # Why: working/removed states carry no snippet; payload building must not
    # require one. Guards the None-message path used by UserPromptSubmit.
    monkeypatch.delenv("CLAUDE_HOST_LABEL", raising=False)
    client = load_client()
    payload = client.build_event_payload("s", "/srv/app", "working", None)
    assert payload["message"] == ""


# --- Session name resolution ---

def write_transcript(tmp_path, records):
    path = tmp_path / "transcript.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    return str(path)


def test_session_name_from_hook_input_field():
    # Why: when Claude Code passes the session title directly in hook input, the
    # client must use it without touching the transcript — cheapest, freshest source.
    client = load_client()
    assert client.get_session_name({"session_title": "tester"}) == "tester"
    assert client.get_session_name({"custom_title": "tester"}) == "tester"


def test_session_name_from_transcript_last_custom_title(tmp_path):
    # Why: /rename writes {"type":"custom-title"} records into the transcript; the
    # LAST one is the current name. Picking the first would show stale names after
    # a re-rename.
    client = load_client()
    path = write_transcript(tmp_path, [
        {"type": "user", "message": {"role": "user", "content": "hi"}},
        {"type": "custom-title", "customTitle": "old-name", "sessionId": "s1"},
        {"type": "custom-title", "customTitle": "tester", "sessionId": "s1"},
        {"type": "assistant", "message": {"role": "assistant", "content": []}},
    ])
    assert client.get_session_name({"transcript_path": path}) == "tester"


def test_session_name_absent_returns_empty(tmp_path):
    # Why: unnamed sessions are the norm; the client must return "" (not None, not
    # an error) so the hub falls back to the project label. Guards the missing-file
    # path too — get_session_name must never raise inside a hook.
    client = load_client()
    path = write_transcript(tmp_path, [
        {"type": "user", "message": {"role": "user", "content": "hi"}},
    ])
    assert client.get_session_name({"transcript_path": path}) == ""
    assert client.get_session_name({"transcript_path": str(tmp_path / "missing.jsonl")}) == ""
    assert client.get_session_name({}) == ""


def test_payload_includes_session_name(monkeypatch):
    # Why: the hub can only display a session's name if every event carries it;
    # dropping the field would silently revert rows to project-only labels.
    monkeypatch.delenv("CLAUDE_HOST_LABEL", raising=False)
    client = load_client()
    payload = client.build_event_payload(
        "s", "/srv/app", "working", None, session_name="tester"
    )
    assert payload["session_name"] == "tester"


def test_payload_session_name_defaults_empty(monkeypatch):
    # Why: callers that pass no name must still produce a valid payload with an
    # empty session_name — unnamed sessions stay on the project label.
    monkeypatch.delenv("CLAUDE_HOST_LABEL", raising=False)
    client = load_client()
    payload = client.build_event_payload("s", "/srv/app", "working", None)
    assert payload["session_name"] == ""


def test_report_state_posts_session_name(monkeypatch):
    # Why: report_state is the single delivery path for all hooks; if it drops the
    # session_name kwarg, no hook can ever surface a name on the dashboard.
    monkeypatch.setenv("CLAUDE_ATTENTION_HUB_URL", "http://hub.example:8765")
    monkeypatch.delenv("CLAUDE_HOST_LABEL", raising=False)
    client = load_client()
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["body"] = json.loads(req.data.decode("utf-8"))
        return MagicMock(status=200)

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        client.report_state("s", "/work/proj", "working", session_name="tester")

    assert captured["body"]["session_name"] == "tester"


# --- Container detection ---

EXT4_ROOT_MOUNTINFO = (
    "25 0 8:1 / / rw,relatime shared:1 - ext4 /dev/sda1 rw\n"
    "26 25 0:5 / /dev rw,nosuid shared:2 - devtmpfs devtmpfs rw\n"
)
OVERLAY_ROOT_MOUNTINFO = (
    "1573 1280 0:211 / / rw,relatime - overlay overlay "
    "rw,lowerdir=/var/lib/docker/overlay2/l/AAA,upperdir=/var/lib/docker/"
    "overlay2/x/diff,workdir=/var/lib/docker/overlay2/x/work\n"
    "1574 1573 0:215 / /proc rw,nosuid,nodev,noexec,relatime - proc proc rw\n"
)


def neutralize_container_signals(client, monkeypatch, tmp_path):
    """Point every detection signal at a clean (non-container) source so tests
    are deterministic even when the suite itself runs inside a container."""
    monkeypatch.setattr(client, "CONTAINER_MARKER_FILES",
                        (str(tmp_path / "no-dockerenv"),
                         str(tmp_path / "no-containerenv")))
    mountinfo = tmp_path / "mountinfo"
    mountinfo.write_text(EXT4_ROOT_MOUNTINFO, encoding="utf-8")
    monkeypatch.setattr(client, "MOUNTINFO_PATH", str(mountinfo))
    monkeypatch.delenv("container", raising=False)
    monkeypatch.delenv("KUBERNETES_SERVICE_HOST", raising=False)


def test_container_detection_clean_environment_false(monkeypatch, tmp_path):
    # Why: a plain laptop/VM session must NOT be badged as a container — false
    # positives would make the badge meaningless across a mixed fleet.
    client = load_client()
    neutralize_container_signals(client, monkeypatch, tmp_path)
    assert client.detect_container() is False


def test_container_detection_dockerenv_marker(monkeypatch, tmp_path):
    # Why: /.dockerenv is the canonical Docker marker; its presence alone must
    # flag the session as containerized.
    client = load_client()
    neutralize_container_signals(client, monkeypatch, tmp_path)
    marker = tmp_path / "dockerenv"
    marker.touch()
    monkeypatch.setattr(client, "CONTAINER_MARKER_FILES",
                        (str(marker), str(tmp_path / "no-containerenv")))
    assert client.detect_container() is True


def test_container_detection_containerenv_marker(monkeypatch, tmp_path):
    # Why: Podman writes /run/.containerenv instead of /.dockerenv; either
    # marker file alone must trigger detection.
    client = load_client()
    neutralize_container_signals(client, monkeypatch, tmp_path)
    marker = tmp_path / "containerenv"
    marker.touch()
    monkeypatch.setattr(client, "CONTAINER_MARKER_FILES",
                        (str(tmp_path / "no-dockerenv"), str(marker)))
    assert client.detect_container() is True


def test_container_detection_container_env_var(monkeypatch, tmp_path):
    # Why: Podman and systemd-nspawn export container=...; the env var alone
    # must trigger detection even with no marker files.
    client = load_client()
    neutralize_container_signals(client, monkeypatch, tmp_path)
    monkeypatch.setenv("container", "podman")
    assert client.detect_container() is True


def test_container_detection_kubernetes_env(monkeypatch, tmp_path):
    # Why: Kubernetes pods expose KUBERNETES_SERVICE_HOST but may lack Docker/
    # Podman markers; the variable alone must trigger detection.
    client = load_client()
    neutralize_container_signals(client, monkeypatch, tmp_path)
    monkeypatch.setenv("KUBERNETES_SERVICE_HOST", "10.96.0.1")
    assert client.detect_container() is True


def test_container_detection_overlay_root_fallback(monkeypatch, tmp_path):
    # Why: some dev containers (verified empirically in this repo's own dev
    # container) expose no marker or env signal, but their root filesystem is
    # an overlayfs mount — the mountinfo fallback must catch them.
    client = load_client()
    neutralize_container_signals(client, monkeypatch, tmp_path)
    mountinfo = tmp_path / "mountinfo-overlay"
    mountinfo.write_text(OVERLAY_ROOT_MOUNTINFO, encoding="utf-8")
    monkeypatch.setattr(client, "MOUNTINFO_PATH", str(mountinfo))
    assert client.detect_container() is True


def test_container_detection_unreadable_mountinfo_false(monkeypatch, tmp_path):
    # Why: detection runs inside hooks, which must never raise; an unreadable
    # or missing mountinfo (non-Linux hosts) degrades to "not a container".
    client = load_client()
    neutralize_container_signals(client, monkeypatch, tmp_path)
    monkeypatch.setattr(client, "MOUNTINFO_PATH", str(tmp_path / "missing"))
    assert client.detect_container() is False


def test_payload_carries_container_flag_true(monkeypatch, tmp_path):
    # Why: the hub can only badge a session if every event carries the flag;
    # build_event_payload is the single payload source for all hooks.
    monkeypatch.delenv("CLAUDE_HOST_LABEL", raising=False)
    client = load_client()
    neutralize_container_signals(client, monkeypatch, tmp_path)
    monkeypatch.setenv("KUBERNETES_SERVICE_HOST", "10.96.0.1")
    payload = client.build_event_payload("s", "/srv/app", "working", None)
    assert payload["is_container"] is True


def test_payload_carries_container_flag_false(monkeypatch, tmp_path):
    # Why: non-container sessions must send an explicit False (not omit the
    # field) so the hub never has to guess.
    monkeypatch.delenv("CLAUDE_HOST_LABEL", raising=False)
    client = load_client()
    neutralize_container_signals(client, monkeypatch, tmp_path)
    payload = client.build_event_payload("s", "/srv/app", "working", None)
    assert payload["is_container"] is False


# --- Hub URL resolution ---

def test_hub_url_default(monkeypatch):
    # Why: with no configuration the hooks must target the documented default
    # http://localhost:8765 so local setups work out of the box.
    monkeypatch.delenv("CLAUDE_ATTENTION_HUB_URL", raising=False)
    client = load_client()
    assert client.get_hub_url() == "http://localhost:8765"


def test_hub_url_env_override(monkeypatch):
    # Why: docker containers and remote servers reach the hub via a configurable
    # address; the env var must override the default and tolerate trailing slashes.
    monkeypatch.setenv("CLAUDE_ATTENTION_HUB_URL", "http://10.0.0.5:9999/")
    client = load_client()
    assert client.get_hub_url() == "http://10.0.0.5:9999"


# --- Graceful degradation ---

def test_report_state_unreachable_hub_no_exception(monkeypatch):
    # Why: an unreachable hub must never block or error a Claude session — the
    # core graceful-degradation guarantee of the whole feature.
    monkeypatch.setenv("CLAUDE_ATTENTION_HUB_URL", "http://127.0.0.1:1")
    client = load_client()
    result = client.report_state("s", "/srv/app", "waiting", "msg")
    assert result is False


def test_remove_session_unreachable_hub_no_exception(monkeypatch):
    # Why: SessionEnd must exit cleanly even when the hub is down; a raised
    # exception here would surface as a hook error in Claude Code.
    monkeypatch.setenv("CLAUDE_ATTENTION_HUB_URL", "http://127.0.0.1:1")
    client = load_client()
    result = client.remove_session("s")
    assert result is False


def test_report_state_posts_event_to_hub(monkeypatch):
    # Why: the hub contract is POST {hub}/api/events with the JSON payload; if the
    # path or body encoding drifts, every hook silently stops reporting.
    monkeypatch.setenv("CLAUDE_ATTENTION_HUB_URL", "http://hub.example:8765")
    monkeypatch.delenv("CLAUDE_HOST_LABEL", raising=False)
    client = load_client()
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["body"] = json.loads(req.data.decode("utf-8"))
        captured["method"] = req.get_method()
        return MagicMock(status=200)

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        ok = client.report_state("sess-9", "/work/proj", "waiting", "hello")

    assert ok is True
    assert captured["url"] == "http://hub.example:8765/api/events"
    assert captured["method"] == "POST"
    assert captured["body"]["session_id"] == "sess-9"
    assert captured["body"]["state"] == "waiting"


def test_report_state_slow_hub_no_exception(monkeypatch):
    # Why: a hub that accepts the connection but never answers (slow DNS/network)
    # must surface as a swallowed timeout, never an exception in the hook.
    import socket
    monkeypatch.setenv("CLAUDE_ATTENTION_HUB_URL", "http://hub.example:8765")
    client = load_client()
    with patch("urllib.request.urlopen", side_effect=socket.timeout("timed out")):
        assert client.report_state("s", "/srv/app", "waiting", "msg") is False


def test_report_state_bounded_total_wall_clock(monkeypatch):
    # Why: AC4 "never block Claude" — DNS resolution runs before urlopen's socket
    # timeout applies, so a black-holed hub URL could stall every UserPromptSubmit
    # for seconds. Total hub-report time must stay bounded by the timeout budget
    # even when urlopen itself hangs indefinitely.
    import time
    monkeypatch.setenv("CLAUDE_ATTENTION_HUB_URL", "http://hub.example:8765")
    client = load_client()
    client.HUB_TIMEOUT_SECONDS = 0.2

    def hanging_urlopen(req, timeout=None):
        time.sleep(10)
        return MagicMock(status=200)

    start = time.monotonic()
    with patch("urllib.request.urlopen", side_effect=hanging_urlopen):
        result = client.report_state("s", "/srv/app", "waiting", "msg")
    elapsed = time.monotonic() - start

    assert result is False
    assert elapsed < 2.0


def test_remove_session_quotes_special_characters(monkeypatch):
    # Why: session IDs are interpolated into the URL path; reserved characters
    # must be percent-encoded or the hub can never delete what it stored.
    monkeypatch.setenv("CLAUDE_ATTENTION_HUB_URL", "http://hub.example:8765")
    client = load_client()
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        return MagicMock(status=200)

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        client.remove_session("odd id/1")

    assert captured["url"] == "http://hub.example:8765/api/sessions/odd%20id%2F1"


def test_remove_session_sends_delete(monkeypatch):
    # Why: SessionEnd removal must target DELETE /api/sessions/{id}; a wrong verb
    # or path would leave dead rows on the dashboard forever.
    monkeypatch.setenv("CLAUDE_ATTENTION_HUB_URL", "http://hub.example:8765")
    client = load_client()
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["method"] = req.get_method()
        return MagicMock(status=200)

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        ok = client.remove_session("sess-9")

    assert ok is True
    assert captured["url"] == "http://hub.example:8765/api/sessions/sess-9"
    assert captured["method"] == "DELETE"


# --- Marker JSON record format + legacy fallback ---

def test_read_marker_parses_json_record(hub_client, active_subagent_home):
    # Why: _read_marker is the single source of truth every other marker
    # function relies on -- it must round-trip a well-formed JSON record.
    active_subagent_home.mkdir(parents=True, exist_ok=True)
    marker = active_subagent_home / "m1"
    marker.write_text('{"id": "m1", "kind": "bash", "label": "x", '
                       '"status": "active", "started_at": 123.0}')
    record = hub_client._read_marker(marker)
    assert record == {"id": "m1", "kind": "bash", "label": "x",
                       "status": "active", "started_at": 123.0}


def test_read_marker_legacy_empty_file_falls_back(hub_client, active_subagent_home):
    # Why: markers created before this story (empty touch files) must still
    # be treated as valid task-kind, active-status records, not crash or
    # silently vanish, so rollout never loses in-flight tracking.
    active_subagent_home.mkdir(parents=True, exist_ok=True)
    marker = active_subagent_home / "legacy-marker"
    marker.touch()
    record = hub_client._read_marker(marker)
    assert record["id"] == "legacy-marker"
    assert record["kind"] == "task"
    assert record["label"] == ""
    assert record["status"] == "active"
    assert isinstance(record["started_at"], float)


# --- Active work tracking ---

def test_build_event_payload_includes_active_work_when_present():
    client = load_client()
    payload = client.build_event_payload(
        "s1", "/tmp/proj", "working", active_work=[{"kind": "task", "status": "active"}]
    )
    assert payload["active_work"] == [{"kind": "task", "status": "active"}]


def test_build_event_payload_omits_active_work_when_empty():
    # Why: keep normal-state payloads unchanged in shape when nothing is
    # tracked, matching every other optional field's omit-when-empty style.
    client = load_client()
    payload = client.build_event_payload("s1", "/tmp/proj", "done")
    assert "active_work" not in payload


# --- Dev-workflow stage ---

def test_default_state_dir_isolated_from_real_home(isolated_dev_workflow_state):
    # Why: DEV_WORKFLOW_STATE_DIR binds Path.home() at import, so any payload
    # test would read the developer's real checkpoints; the autouse fixture
    # must demonstrably redirect every load_client() to a tmp_path dir.
    client = load_client()
    assert client.DEV_WORKFLOW_STATE_DIR == isolated_dev_workflow_state


def make_stage_client(monkeypatch, tmp_path):
    client = load_client()
    state_dir = tmp_path / "dev-workflow-state"
    state_dir.mkdir()
    monkeypatch.setattr(client, "DEV_WORKFLOW_STATE_DIR", state_dir)
    return client, state_dir


def write_checkpoint(state_dir, name, body):
    path = state_dir / name
    path.write_text(json.dumps(body), encoding="utf-8")
    return path


def test_stage_single_repo_checkpoint(monkeypatch, tmp_path):
    # Why: the dashboard's stage line reads "repo:stage" from the checkpoint
    # whose repos dict names this cwd's repo; the basic lookup must work.
    client, state_dir = make_stage_client(monkeypatch, tmp_path)
    write_checkpoint(state_dir, "story-1.json",
                     {"repos": {"my-project": {"stage": "review"}}})
    assert client.get_dev_workflow_stage("/home/user/my-project") == "my-project:review"


def test_stage_multi_repo_checkpoint_lists_all_repos(monkeypatch, tmp_path):
    # Why: a multi-repo story's card should show the whole pipeline picture,
    # not just this session's own repo — every entry joins in insertion order.
    client, state_dir = make_stage_client(monkeypatch, tmp_path)
    write_checkpoint(state_dir, "story-1.json",
                     {"repos": {"my-project": {"stage": "review"},
                                "other-repo": {"stage": "testing"}}})
    assert (client.get_dev_workflow_stage("/home/user/my-project")
            == "my-project:review, other-repo:testing")


def test_stage_no_matching_checkpoint_returns_empty(monkeypatch, tmp_path):
    # Why: sessions outside any dev-workflow story must get "" (never None,
    # never a raise) so the payload stays valid and the card shows two lines.
    client, state_dir = make_stage_client(monkeypatch, tmp_path)
    write_checkpoint(state_dir, "story-1.json",
                     {"repos": {"unrelated": {"stage": "review"}}})
    assert client.get_dev_workflow_stage("/home/user/my-project") == ""
    payload = client.build_event_payload("s", "/home/user/my-project", "working")
    assert payload["stage"] == ""


def test_stage_missing_state_dir_returns_empty(monkeypatch, tmp_path):
    # Why: hosts that never ran dev-workflow have no state dir at all; the
    # lookup must treat that as "no checkpoints", not an error.
    client = load_client()
    monkeypatch.setattr(client, "DEV_WORKFLOW_STATE_DIR", tmp_path / "absent")
    assert client.get_dev_workflow_stage("/home/user/my-project") == ""


def test_stage_malformed_file_skipped_without_raise(monkeypatch, tmp_path):
    # Why: checkpoint files are written by another tool and may be corrupt
    # mid-write; one bad file must not abort the scan or break the hook.
    client, state_dir = make_stage_client(monkeypatch, tmp_path)
    (state_dir / "broken.json").write_text("{not json", encoding="utf-8")
    write_checkpoint(state_dir, "story-1.json",
                     {"repos": {"my-project": {"stage": "development"}}})
    assert (client.get_dev_workflow_stage("/home/user/my-project")
            == "my-project:development")


def test_stage_most_recent_matching_checkpoint_wins(monkeypatch, tmp_path):
    # Why: a repo can appear in several stories' checkpoints; the freshest
    # file (mtime) reflects the pipeline actually running now.
    client, state_dir = make_stage_client(monkeypatch, tmp_path)
    old = write_checkpoint(state_dir, "story-old.json",
                           {"repos": {"my-project": {"stage": "spec"}}})
    new = write_checkpoint(state_dir, "story-new.json",
                           {"repos": {"my-project": {"stage": "review"}}})
    os.utime(old, (1000, 1000))
    os.utime(new, (2000, 2000))
    assert client.get_dev_workflow_stage("/home/user/my-project") == "my-project:review"
    os.utime(old, (3000, 3000))
    assert client.get_dev_workflow_stage("/home/user/my-project") == "my-project:spec"


def test_stage_non_dict_repos_skipped(monkeypatch, tmp_path):
    # Why: a checkpoint whose repos is a list, missing, or whose body is not
    # an object doesn't match the schema — skip it, don't crash on it.
    client, state_dir = make_stage_client(monkeypatch, tmp_path)
    write_checkpoint(state_dir, "list-repos.json", {"repos": ["my-project"]})
    write_checkpoint(state_dir, "no-repos.json", {"other": 1})
    write_checkpoint(state_dir, "non-dict.json", ["my-project"])
    assert client.get_dev_workflow_stage("/home/user/my-project") == ""
    write_checkpoint(state_dir, "valid.json",
                     {"repos": {"my-project": {"stage": "review"}}})
    assert client.get_dev_workflow_stage("/home/user/my-project") == "my-project:review"


def test_stage_non_string_stage_entry_skipped(monkeypatch, tmp_path):
    # Why: an entry with a missing or non-string stage can't render as
    # "repo:stage"; drop that entry but keep the rest of the winner's repos.
    client, state_dir = make_stage_client(monkeypatch, tmp_path)
    write_checkpoint(state_dir, "story-1.json",
                     {"repos": {"my-project": {"stage": "review"},
                                "numeric": {"stage": 3},
                                "stageless": {}}})
    assert client.get_dev_workflow_stage("/home/user/my-project") == "my-project:review"


def test_stage_empty_cwd_returns_empty(monkeypatch, tmp_path):
    # Why: hooks can fire with no cwd; there is no repo to match, so the
    # lookup must short-circuit to "" instead of guessing.
    client, state_dir = make_stage_client(monkeypatch, tmp_path)
    write_checkpoint(state_dir, "story-1.json",
                     {"repos": {"my-project": {"stage": "review"}}})
    assert client.get_dev_workflow_stage("") == ""
    assert client.get_dev_workflow_stage(None) == ""


def test_payload_always_includes_stage_key(monkeypatch, tmp_path):
    # Why: the store treats stage as non-sticky, so every payload must carry
    # the key — even "" — or a stale stage would linger on the card.
    client = load_client()
    monkeypatch.setattr(client, "DEV_WORKFLOW_STATE_DIR", tmp_path / "absent")
    payload = client.build_event_payload("s", "/srv/app", "working")
    assert payload["stage"] == ""


def test_payload_carries_matching_stage(monkeypatch, tmp_path):
    # Why: the stage line is only visible if the payload actually delivers the
    # looked-up value to the hub on ordinary state events.
    client, state_dir = make_stage_client(monkeypatch, tmp_path)
    write_checkpoint(state_dir, "story-1.json",
                     {"repos": {"my-project": {"stage": "development"}}})
    payload = client.build_event_payload("s", "/home/user/my-project", "working")
    assert payload["stage"] == "my-project:development"
