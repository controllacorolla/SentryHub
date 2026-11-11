"""Regression tests for bugs fixed in theme.py during the code audit (needs a display)."""
import os
import time

import pytest

tk = pytest.importorskip("tkinter")


@pytest.fixture
def root():
    if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        pytest.skip("no display")
    import theme as T
    try:
        r, F = T.make_root("audit-test")
    except tk.TclError:
        pytest.skip("no display")
    r.withdraw()
    yield r, F, T
    r.destroy()


def _pump(r, secs=0.1):
    end = time.time() + secs
    while time.time() < end:
        r.update()


def test_sheet_closed_before_arming_leaves_no_click_binding(root):
    r, F, T = root
    before = r.bind("<Button-1>")
    anchor = tk.Button(r, text="x")
    anchor.pack()
    panel = T.sheet(anchor, F, "t", lambda body: None)
    panel.close()            # fast double-tap: closed before the 1 ms arm ran
    _pump(r)
    assert r.bind("<Button-1>") == before


def test_sheet_double_place_arms_once(root):
    r, F, T = root
    before = r.bind("<Button-1>")
    anchor = tk.Button(r, text="x")
    anchor.pack()
    panel = T.sheet(anchor, F, "t", lambda body: None)
    panel.rebuild()          # second _place() inside the same 1 ms window
    _pump(r)
    panel.close()
    _pump(r)
    assert r.bind("<Button-1>") == before
