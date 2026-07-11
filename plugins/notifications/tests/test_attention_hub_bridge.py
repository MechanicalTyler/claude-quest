# tests/test_attention_hub_bridge.py
import importlib.util
from pathlib import Path

HOOKS_DIR = Path(__file__).parent.parent / "hooks"


def load_bridge():
    spec = importlib.util.spec_from_file_location(
        "attention_hub_bridge", HOOKS_DIR / "attention_hub_bridge.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_list_active_work_passes_through_to_client(monkeypatch):
    bridge = load_bridge()
    monkeypatch.setattr(bridge, "_client",
                         type("StubClient", (), {"list_active_work": staticmethod(lambda sid: [{"kind": "task"}])}))
    assert bridge.list_active_work("s1") == [{"kind": "task"}]


def test_list_active_work_returns_empty_when_client_unavailable(monkeypatch):
    bridge = load_bridge()
    monkeypatch.setattr(bridge, "_client", None)
    assert bridge.list_active_work("s1") == []


def test_report_state_forwards_active_work_to_client(monkeypatch):
    bridge = load_bridge()
    captured = {}
    stub = type("StubClient", (), {
        "report_state": staticmethod(lambda *a, **kw: captured.update(kw) or True)
    })
    monkeypatch.setattr(bridge, "_client", stub)
    bridge.report_state("s1", "/tmp", "working", active_work=[{"kind": "task"}])
    assert captured["active_work"] == [{"kind": "task"}]
