"""Tests for the Sky tabbed shell's pure routing logic (Phase 1b). No Tk required."""
import sky


class _FakeWS:
    def __init__(self, key, keys=None, alive=True):
        self.key = key
        self.keys = keys or {}
        self.alive = alive


class _FakeHost:
    def __init__(self, active):
        self.active = active


def test_tabs_table_well_formed():
    assert sky.TABS[0][0] == "Aircraft"
    labels = [t[0] for t in sky.TABS]
    assert "Balloons" in labels
    for label, mod, entry in sky.TABS:
        assert isinstance(label, str) and mod and entry


def test_dispatch_routes_to_front_tab_when_sky_is_front():
    fired = []
    ts = sky._TabShell(root=None, host_shell=_FakeHost(active="sky"), my_key="sky")
    ws = _FakeWS("sky:aircraft", {"<space>": lambda e: fired.append(e) or "ok"})
    ts.tabs["sky:aircraft"] = ws
    ts.active_tab = "sky:aircraft"
    assert ts._dispatch("<space>", "evt") == "ok"
    assert fired == ["evt"]


def test_dispatch_ignored_when_other_workspace_is_front():
    ts = sky._TabShell(root=None, host_shell=_FakeHost(active="ops"), my_key="sky")
    ws = _FakeWS("sky:aircraft", {"<space>": lambda e: "should-not-fire"})
    ts.tabs["sky:aircraft"] = ws
    ts.active_tab = "sky:aircraft"
    assert ts._dispatch("<space>", "evt") is None


def test_dispatch_standalone_always_routes():
    ts = sky._TabShell(root=None, host_shell=None, my_key=None)
    ws = _FakeWS("sky:aircraft", {"x": lambda e: 42})
    ts.tabs["sky:aircraft"] = ws
    ts.active_tab = "sky:aircraft"
    assert ts._dispatch("x", "evt") == 42


def test_dispatch_dead_or_unknown_tab_is_safe():
    ts = sky._TabShell(root=None, host_shell=None, my_key=None)
    ts.tabs["sky:aircraft"] = _FakeWS("sky:aircraft", {"x": lambda e: 1}, alive=False)
    ts.active_tab = "sky:aircraft"
    assert ts._dispatch("x", "evt") is None          # dead workspace
    ts.active_tab = "sky:nope"
    assert ts._dispatch("x", "evt") is None          # unknown tab


def test_closed_removes_tab_and_clears_active():
    ts = sky._TabShell(root=None, host_shell=None, my_key=None)
    ws = _FakeWS("sky:balloons")
    ts.tabs["sky:balloons"] = ws
    ts.active_tab = "sky:balloons"
    ts.closed(ws)
    assert "sky:balloons" not in ts.tabs
    assert ts.active_tab is None
