"""The workstation shell: apps run as workspaces in one window (needs a display)."""
import os
import sys
import types

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
pytestmark = pytest.mark.skipif(not os.environ.get("DISPLAY"), reason="needs a display")


@pytest.fixture
def shell(monkeypatch):
    import tkinter as tk
    import suite as S
    import hub
    root = tk.Tk()
    root.withdraw()
    barhost, host = tk.Frame(root), tk.Frame(root)
    sh = hub.Shell(root, S.T.fonts(root), barhost, host)
    monkeypatch.setattr(S.T, "EMBED", sh)
    sh.new_workspace("Home", key="home")
    calls = {}

    def make(name):
        m = types.ModuleType(name)

        def main():
            r, F = S.make_root(name)
            S.single_instance(name)               # must not exit or lock in-shell
            S.top_bar(r, F, name, "test")
            calls[name] = {"keys": 0, "ticks": 0, "closed": 0, "argv": list(sys.argv), "root": r}
            r.bind("x", lambda e: calls[name].__setitem__("keys", calls[name]["keys"] + 1))

            def tick():
                calls[name]["ticks"] += 1
                r.after(10, tick)
            tick()

            def on_close():
                calls[name]["closed"] += 1
                r.destroy()
            S.bind_quit(r, on_close)
            r.mainloop()                          # returns at once inside the shell
        m.main = main
        monkeypatch.setitem(sys.modules, name, m)
        return m
    for key in ("appa", "appb"):
        make(key)
        monkeypatch.setitem(hub.Shell.MODS, key, (key, "main"))
    yield sh, calls, root
    sh.closing = True
    root.destroy()


def test_workspaces_share_one_window(shell):
    sh, calls, root = shell
    assert sh.open("appa", ["--flag"]) is None and sh.open("appb") is None
    assert sh.active == "appb" and set(sh.ws) == {"home", "appa", "appb"}
    assert calls["appa"]["argv"][:2] == ["appa.py", "--flag"]
    assert calls["appa"]["root"].bar is not None             # its bar lives in the shell strip
    # a shortcut reaches only the workspace in front
    sh.dispatch("x", None)
    assert (calls["appa"]["keys"], calls["appb"]["keys"]) == (0, 1)
    sh.show("appa")
    sh.dispatch("x", None)
    assert (calls["appa"]["keys"], calls["appb"]["keys"]) == (1, 1)
    sh.modal = True
    sh.dispatch("x", None)
    assert calls["appa"]["keys"] == 1                        # palette open: shortcuts off
    sh.modal = False
    # Esc goes Home and leaves the app running
    sh.dispatch("<Escape>", None)
    assert sh.active == "home" and "appa" in sh.ws and calls["appa"]["closed"] == 0
    # hidden workspaces keep working
    n = calls["appb"]["ticks"]
    for _ in range(20):
        root.update()
        import time
        time.sleep(0.005)
    assert calls["appb"]["ticks"] > n


def test_close_runs_app_shutdown_and_stops_its_timers(shell):
    sh, calls, root = shell
    sh.open("appa")
    sh.open("appb")
    sh.close("appb")
    assert calls["appb"]["closed"] == 1 and "appb" not in sh.ws
    assert sh.active == "appa"                               # back to the previous workspace
    n = calls["appb"]["ticks"]
    import time
    for _ in range(20):
        root.update()
        time.sleep(0.005)
    assert calls["appb"]["ticks"] == n                       # no timers firing into dead widgets
    sh.close("home")
    assert "home" in sh.ws                                   # Home can't be closed
    assert sh.open("appb") is None and calls["appb"]["closed"] == 0   # reopens fresh


def test_broken_app_does_not_take_the_window_down(shell, monkeypatch):
    sh, calls, root = shell
    import hub
    bad = types.ModuleType("appbad")

    def main():
        import suite as S
        S.make_root("bad")
        raise RuntimeError("boom")
    bad.main = main
    monkeypatch.setitem(sys.modules, "appbad", bad)
    monkeypatch.setitem(hub.Shell.MODS, "appbad", ("appbad", "main"))
    err = sh.open("appbad")
    assert err and "boom" in err and "appbad" not in sh.ws and sh.active in (None, "home")


def test_helper_threads_end_with_the_workspace(shell, monkeypatch):
    """Map tile workers must not pile up every time a workspace is reopened."""
    import threading
    import time
    import hub
    import suite as S
    import tiles
    sh, calls, root = shell
    m = types.ModuleType("appmap")

    def main():
        r, F = S.make_root("map")
        tiles.TileLayer(workers=3)
        S.bind_quit(r, r.destroy)
    m.main = main
    monkeypatch.setitem(sys.modules, "appmap", m)
    monkeypatch.setitem(hub.Shell.MODS, "appmap", ("appmap", "main"))

    def workers():
        return sum(1 for t in threading.enumerate()
                   if getattr(getattr(t, "_target", None), "__qualname__", "") == "TileLayer._worker")
    base = workers()
    for _ in range(3):
        assert sh.open("appmap") is None
        assert workers() == base + 3
        sh.close("appmap")
        t0 = time.time()
        while workers() > base and time.time() - t0 < 3:
            time.sleep(0.02)
        assert workers() == base
    # a worker thread reporting to a closed workspace is ignored, not an exception
    sh.open("appmap")
    w = sh.ws["appmap"]
    sh.close("appmap")
    assert w.after(0, lambda: None) is None


def test_quit_waits_for_the_radio_to_come_back(shell, monkeypatch):
    """A holder that stops on a worker thread (Sky's scanner) must finish before exit."""
    import threading
    import time
    import suite as S
    sh, calls, root = shell

    class Held:
        who, held = "sky", True
    h = Held()
    monkeypatch.setattr(S, "_HOLDER", [h])
    threading.Timer(0.4, lambda: setattr(h, "held", False)).start()
    t0 = time.time()
    assert sh.close_all(wait_s=5) is True
    assert 0.3 < time.time() - t0 < 3
    h.held = True                                  # a holder that never lets go: bounded wait
    t0 = time.time()
    assert sh.close_all(wait_s=0.3) is False
    assert time.time() - t0 < 2


def test_settings_window_leaves_no_global_bindings(shell):
    import settings_ui
    import suite as S
    sh, calls, root = shell
    before = root.bind_all()
    win = settings_ui.open_settings(root, S.T.fonts(root), "t",
                                    [("General", [{"key": "gain", "label": "Gain", "type": "int", "min": 0, "max": 49}])], {"gain": 1},
                                    lambda d: None)
    root.update()
    assert root.bind_all() == before
    win.destroy()
    root.update()


def test_overwatch_opens_runs_and_closes_in_the_shell(shell, monkeypatch, tmp_path):
    import time
    import suite as S
    import hub
    sh, calls, root = shell
    monkeypatch.setattr(S, "CFG", str(tmp_path))
    monkeypatch.setitem(hub.Shell.MODS, "ow", ("overwatch", "main"))
    assert sh.open("ow", ["--demo", "--auto"]) is None
    end = time.time() + 3.5
    while time.time() < end:
        root.update()
        time.sleep(0.02)
    assert S.AUTOPILOT["on"] and S.AUTOPILOT["mode"] in ("air", "aprs", "sensors", "sonde")
    assert "ow" in sh.ws and len(sh.ws) == 2          # demo autopilot opens nothing else
    sh.close("ow")
    root.update()
    assert "ow" not in sh.ws and S.AUTOPILOT["on"] is False


def test_radio_code(monkeypatch):
    import suite as S

    class Held:
        who, held = "Sensors", True
    monkeypatch.setattr(S, "_HOLDER", [None])
    assert S.radio_code() == "AIR"
    monkeypatch.setattr(S, "_HOLDER", [Held()])
    assert S.radio_code() == "433"
    Held.who = "Something new"
    assert S.radio_code() == "SOME"
