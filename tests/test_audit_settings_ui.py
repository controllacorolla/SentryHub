"""Regression tests for bugs fixed in settings_ui.py during the code audit (needs a display)."""
import os
import time

import pytest

tk = pytest.importorskip("tkinter")


def _walk(w):
    yield w
    for c in w.winfo_children():
        yield from _walk(c)


def test_save_and_close_removes_global_wheel_bindings(tmp_path):
    if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        pytest.skip("no display")
    import theme as T
    import settings_ui
    try:
        root, F = T.make_root("audit-settings")
    except tk.TclError:
        pytest.skip("no display")
    root.withdraw()
    try:
        schema = [("General", [{"key": "gain", "label": "Gain", "type": "int", "min": 0, "max": 49}])]
        win = settings_ui.open_settings(root, F, "t", schema, {"gain": 10}, lambda new: None,
                                        path=str(tmp_path / "x.json"))
        assert not root.bind_all("<Button-4>")       # wheel is bound on the window only
        assert win.bind("<Button-4>")
        btn = next(w for w in _walk(win) if isinstance(w, tk.Label)
                   and w.cget("text") == "Save & close")
        # run the label's <Button-1> handler directly (synthetic clicks need a mapped window,
        # which a headless-ish test run can't rely on)
        import re
        cmd = re.search(r"\[(\S+)", btn.bind("<Button-1>")).group(1)
        fields = ["0"] * 19       # tkinter's %-substitution order; %W (index 14) = widget
        fields[14] = str(btn)
        btn.tk.call(cmd, *fields)
        end = time.time() + 0.2
        while time.time() < end:
            root.update()
        assert not win.winfo_exists()
        assert not root.bind_all("<Button-4>"), "wheel still bound to a destroyed canvas"
    finally:
        root.destroy()
