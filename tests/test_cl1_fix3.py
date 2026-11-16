"""CL1-fix3: regression tests for what RA-CL1c found (plan/briefs/CL1-fix3.md).

F1 the nav-key focus cue never paints over a glyph · F2 the strip fits 1280 at any scope size ·
F3 a fit-to-viewport FeedTable refits when its viewport changes · F4 a lost ATLAS contact is never
shown as current. Headless (Qt offscreen).
"""
import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")

HERE = os.path.dirname(os.path.abspath(__file__))
SUITE_DIR = os.path.dirname(HERE)
for p in (SUITE_DIR, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

from PySide6 import QtCore, QtWidgets  # noqa: E402

from test_cl1_screen import _app, _pump, _hub, _isolate, THEMES  # noqa: E402

_isolate = _isolate          # autouse isolation fixture applies here too


# ================================================================ F1 focus never covers a glyph
def _text_rects(key):
    """Each line's text rect in key coordinates: its advance box widened to its ink, over its ink
    rows (the two line boxes overlap by design; only the ink rows belong to a line)."""
    out = []
    for w in (key.call, key.label):
        fm = w.fontMetrics()
        tb = fm.tightBoundingRect(w.text())
        adv = fm.horizontalAdvance(w.text())
        x0 = w.x() + (w.width() - adv) // 2                     # AlignHCenter
        left, right = min(x0, x0 + tb.left()), max(x0 + adv - 1, x0 + tb.right())
        base = w.y() + fm.ascent()
        out.append(QtCore.QRect(QtCore.QPoint(left, base + tb.top()),
                                QtCore.QPoint(right, base + tb.bottom())))
    return out


def _grab_key(hub, key):
    return hub.grab(QtCore.QRect(key.mapTo(hub, QtCore.QPoint(0, 0)), key.size())).toImage()


@pytest.mark.parametrize("mode", THEMES)
@pytest.mark.parametrize("on", (False, True), ids=("off", "on"))
def test_nav_key_focus_cue_never_paints_inside_the_text_rect(mode, on):
    """RA-CL1c F1: in SUN the 4 px focus ring sat on the first/last glyph columns ('8 SYSTEM' read
    '3 SYSTEM'). For every key, current page or not, every pixel inside both text rects is the same
    focused and unfocused, and the focus cue is still visible somewhere on the key."""
    from palisade_qt.ops import CALLSIGNS
    hub = _hub(mode=mode, demo=True)
    try:
        hub.resize(1280, 720)
        _pump(100)
        keys = hub.topbar.nav_keys
        names = [n for n, _ in CALLSIGNS]
        for name in names:
            key = keys[name]
            other = keys[names[(names.index(name) + 1) % len(names)]]
            hub.topbar.set_active_page(name if on else other.callsign)
            other.setFocus()
            _pump(40)
            assert not key.hasFocus()
            a = _grab_key(hub, key)
            key.setFocus()
            _pump(40)
            assert key.hasFocus()
            b = _grab_key(hub, key)
            assert a.size() == b.size()
            for r in _text_rects(key):
                assert r.left() >= 0 and r.right() < key.width(), (name, "text wider than key")
                bad = [(x, y) for y in range(r.top(), r.bottom() + 1)
                       for x in range(r.left(), r.right() + 1) if a.pixel(x, y) != b.pixel(x, y)]
                assert not bad, (mode, name, on, "focus painted inside the text rect", bad[:6])
            changed = sum(1 for y in range(a.height()) for x in range(a.width())
                          if a.pixel(x, y) != b.pixel(x, y))
            assert changed >= key.width(), (mode, name, on, "no visible focus cue")
    finally:
        hub.close()
        _pump(150)


def test_nav_key_focus_cue_does_not_widen_the_strip():
    """F1 constraint: the SUN demo strip had 1 px spare; the focus cue may not cost width."""
    for mode in THEMES:
        hub = _hub(mode=mode, demo=True)
        try:
            before = {n: k.sizeHint().width() for n, k in hub.topbar.nav_keys.items()}
            for k in hub.topbar.nav_keys.values():
                k.setFocus()
                _pump(20)
                assert k.sizeHint().width() == before[k.callsign] == k.width(), (mode, k.callsign)
        finally:
            hub.close()
            _pump(100)


# ================================================================ F2 scope size never overflows
def test_scope_summary_caps_the_target_count():
    from palisade_qt.chrome import scope_summary
    assert scope_summary(["h%d" % i for i in range(99)]) == "99 targets"
    assert scope_summary(["h%d" % i for i in range(100)]) == "100 tgts"      # RA-MAIN-1 F1
    assert scope_summary(["h%d" % i for i in range(999)]) == "999 tgts"
    assert scope_summary(["h%d" % i for i in range(1000)]) == "999+ tgts"
    assert scope_summary(["h%d" % i for i in range(100000)]) == "999+ tgts"
    # no count form is wider than the widest single target the strip shows as itself
    from palisade_qt.chrome import SCOPE_CHARS
    for n in (1, 9, 10, 99, 100, 999, 1000, 10 ** 6):
        assert len(scope_summary(["h"] * n)) <= SCOPE_CHARS, n


STRIP_HEADROOM = 10    # RA-MAIN-1 F1: worst case was 1279 (1 px spare) on both Mac and Linux


def test_bundled_plex_fonts_are_loaded():
    """RA-MAIN-1 F2 (claim: load_fonts reads palisade_qt/fonts/ and is a no-op). Every metric
    test above measures the font the device ships, so pin that the bundled Plex really loads."""
    from PySide6 import QtGui
    from palisade_qt import theme
    _app()
    theme.load_fonts()
    fams = set(QtGui.QFontDatabase.families())
    assert {"IBM Plex Mono", "IBM Plex Sans"} <= fams, sorted(f for f in fams if "Plex" in f)
    assert QtGui.QFontInfo(QtGui.QFont("IBM Plex Mono")).family() == "IBM Plex Mono"


@pytest.mark.parametrize("mode", THEMES)
@pytest.mark.parametrize("demo", (False, True), ids=("live", "demo"))
def test_strip_fits_1280_with_a_huge_scope(mode, demo):
    """RA-CL1c F2: 1000 targets pushed the SUN demo strip to 1289 px. Through the real engine, at
    the strip's worst case otherwise (longest owner label, PERMITTED, 99+ alerts, focus on a key)."""
    import engagement
    from palisade_qt import chrome, radio_arbiter
    longest = max(radio_arbiter.OWNER_LABELS.values(), key=len)
    hub = _hub(mode=mode, demo=demo)
    try:
        hub.state.stop()
        for n in (999, 1000, 100000):
            engagement.reset()
            engagement.start("t", "ROE-1", ["10.0.%d.%d" % (i // 250, i % 250) for i in range(n)], "op")
            st = chrome.read_engagement()
            assert st[0] == "ACTIVE" and st[1] in ("999 tgts", "999+ tgts"), st
            for owner, scope_word in [(o, w) for o in ("PROWL SC", longest)
                                      for w in (st[1], "W" * chrome.SCOPE_CHARS)]:
                hub.topbar.set_state("DEMO" if demo else "LIVE", ("HELD", owner), "PERMITTED",
                                     (st[0], scope_word) + tuple(st[2:]))
                hub.topbar.set_alerts(150)
                hub.topbar.nav_keys["SYSTEM"].setFocus()
                _pump(60)
                # RA-MAIN-1 F1: keep STRIP_HEADROOM px spare for font-engine differences
                assert hub.minimumSizeHint().width() <= 1280 - STRIP_HEADROOM, (
                    mode, demo, n, owner, scope_word, hub.minimumSizeHint().width())
                assert hub.topbar.minimumSizeHint().width() <= 1280 - STRIP_HEADROOM
    finally:
        engagement.reset()
        hub.close()
        _pump(150)


# ================================================================ F3 FeedTable refits on resize
def _cols_fit(ft):
    hdr = ft.view.horizontalHeader()
    return sum(hdr.sectionSize(i) for i in range(hdr.count())), ft.view.viewport().width()


def test_feed_table_refits_when_the_viewport_gains_a_vscroll_or_narrows():
    """RA-CL1c F3 (mutation m16): without the viewport-resize refit, a table that gains a vertical
    scroll bar overflowed by 10 px and one that narrowed by 40 px by 50 px: ALT cut, no marker."""
    from palisade_qt import theme
    from palisade_qt.kit.feed import FeedTable
    app = _app()
    theme.load_fonts()
    theme.set_app_font(app)
    app.setStyleSheet(theme.qss("sun"))
    ft = FeedTable([("label", "CONTACT"), ("rng", "NM"), ("alt", "ALT")], fit_viewport=True)
    try:
        ft.resize(440, 300)
        ft.show()
        _pump(100)
        ft.model.set_rows([{"_id": i, "label": "N%d" % i, "rng": "1", "alt": "45000"} for i in range(2)])
        _pump(200)
        assert not ft.view.verticalScrollBar().isVisible()
        total, vw = _cols_fit(ft)
        assert total == vw
        ft.model.set_rows([{"_id": i, "label": "N%d" % i, "rng": "1", "alt": "45000"} for i in range(40)])
        _pump(300)
        assert ft.view.verticalScrollBar().isVisible()
        total, vw = _cols_fit(ft)
        assert total == vw, ("vscroll appeared", total, vw)
        ft.resize(400, 300)                  # a splitter / window narrows; the model does not change
        _pump(300)
        total, vw = _cols_fit(ft)
        assert total == vw, ("narrowed", total, vw)
        assert ft.view.horizontalScrollBar().maximum() == 0
    finally:
        ft.close()
        ft.deleteLater()
        _pump(50)


# ================================================================ F4 lost contact is never current
def test_atlas_detail_marks_a_vanished_selected_contact_lost():
    """RA-CL1c F4: the highlight cleared but the card kept showing the gone contact as if current."""
    import time
    hub = _hub(mode="dark", demo=True)
    try:
        hub.open_callsign("ATLAS")
        _pump(300)
        a = hub.pages["ATLAS:inner"]
        if getattr(a, "_timer", None) is not None:
            a._timer.stop()
        now = time.time()
        a._contacts = {
            "X1": {"id": "X1", "label": "N12345", "kind": "aircraft", "x": 3.0, "y": 4.0,
                   "alt": 123456, "spd": 400, "severity": "info", "_ts": now, "rng": 5.0, "brg": 37.0},
            "X2": {"id": "X2", "label": "N777", "kind": "aircraft", "x": 6.0, "y": 8.0,
                   "alt": 2000, "spd": 100, "severity": "info", "_ts": now, "rng": 10.0, "brg": 37.0}}
        a._render()
        _pump(50)
        row = next(i for i, r in enumerate(a.feed.model.rows) if r["_id"] == "X1")
        a.feed.view.setCurrentIndex(a.feed.model.index(row, 0))
        _pump(50)
        assert a._selected == "X1" and a.detail.hero.text() == "N12345"
        assert "LOST" not in a.detail.sub.text()
        del a._contacts["X1"]
        a._render()
        _pump(50)
        texts = [a.detail.hero.text(), a.detail.sub.text()] + [
            w.text() for w in a.detail.box.findChildren(QtWidgets.QLabel)]
        joined = " ".join(texts)
        assert "LOST" in a.detail.sub.text(), joined
        assert "123456" not in joined and "ft" not in joined.split(), joined   # no stale fixes shown
        # selecting another contact shows it normally again
        row = next(i for i, r in enumerate(a.feed.model.rows) if r["_id"] == "X2")
        a.feed.view.setCurrentIndex(a.feed.model.index(row, 0))
        _pump(50)
        assert a.detail.hero.text() == "N777" and "LOST" not in a.detail.sub.text()
    finally:
        hub.close()
        _pump(150)
