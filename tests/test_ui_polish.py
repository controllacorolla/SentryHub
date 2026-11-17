"""UI polish from the first device run (plan/briefs/device-notes.md, 2026-11-17).

U1 (N-ui1) the nav keys share one baseline per line and never run together · U2 SDR held and an
active engagement read green; TX UNLOCKED stays red · U3 ATLAS gives the map more width · U4 F /
the corner toggle hides the side panels on ATLAS and OPS (layout only: feeds keep running).
Headless (Qt offscreen), real hub at 1280x720.
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

from PySide6 import QtCore, QtTest  # noqa: E402

from test_cl1_screen import _pump, _hub, _isolate, THEMES  # noqa: E402
from test_cl1_fix3 import _text_rects  # noqa: E402

_isolate = _isolate          # autouse isolation fixture applies here too


def _big_hub(mode="dark", demo=False):
    hub = _hub(mode=mode, demo=demo)
    hub.resize(1280, 720)
    hub.show()
    _pump(200)
    return hub


def _close(hub):
    hub.close()
    _pump(150)


MIN_KEY_GAP = 8      # px of bare strip between two keys' text (was ~2 on the device)


def _ink_cols(hub, key):
    """Leftmost / rightmost painted text column of a key, in strip coordinates."""
    xs = []
    for r in _text_rects(key):
        xs += [key.mapTo(hub.topbar, QtCore.QPoint(r.left(), 0)).x(),
               key.mapTo(hub.topbar, QtCore.QPoint(r.right(), 0)).x()]
    return min(xs), max(xs)


# ================================================================ U1 nav keys
@pytest.mark.parametrize("mode", THEMES)
def test_u1_every_nav_key_shares_one_callsign_and_one_label_baseline(mode):
    """'spectrum' (descender) and 'map' / 'survey' sat at different heights, so a label read as
    belonging to the neighbouring key. Every key now places both lines on common baselines, current
    page or not."""
    from palisade_qt.ops import CALLSIGNS
    hub = _big_hub(mode)
    try:
        for current in ("OPS", "PRISM"):
            hub.topbar.set_active_page(current)
            _pump(40)
            keys = hub.topbar.nav_keys
            bases = {n: keys[n].baselines() for n, _ in CALLSIGNS if n in keys}
            assert None not in [b for pair in bases.values() for b in pair], bases
            tops = {n: keys[n].mapTo(hub.topbar, QtCore.QPoint(0, 0)).y() for n in bases}
            assert len({bases[n][0] + tops[n] for n in bases}) == 1, (mode, current, bases)
            assert len({bases[n][1] + tops[n] for n in bases}) == 1, (mode, current, bases)
            # and the ink of each line still sits on its line: callsign above label, inside the key
            for n in bases:
                call, label = _text_rects(keys[n])
                assert call.bottom() < label.top(), (n, call, label)
                assert call.top() >= 0 and label.bottom() < keys[n].height(), n
    finally:
        _close(hub)


@pytest.mark.parametrize("mode", THEMES)
def test_u1_adjacent_nav_keys_have_a_visible_gap_between_their_text(mode):
    """'4 PROWL5 RECON': keys were packed at text width with 1 px each side. Now there are at least
    2 x SIDE px of empty strip between the painted text of two neighbouring keys."""
    from palisade_qt.kit.topbar import NavKey
    hub = _big_hub(mode)
    try:
        keys = sorted(hub.topbar.nav_keys.values(), key=lambda k: k.x())
        assert len(keys) >= 6
        for a, b in zip(keys, keys[1:]):
            gap = _ink_cols(hub, b)[0] - _ink_cols(hub, a)[1] - 1
            assert gap >= MIN_KEY_GAP, (mode, a.callsign, b.callsign, gap)
        assert NavKey.SIDE >= MIN_KEY_GAP // 2
    finally:
        _close(hub)


# ================================================================ U2 strip colours
@pytest.mark.parametrize("mode", THEMES)
def test_u2_sdr_held_and_engagement_active_read_green_tx_unlocked_stays_red(mode):
    from palisade_qt import theme
    t = theme.tokens(mode)
    hub = _big_hub(mode)
    try:
        hub.state.stop()
        bar = hub.topbar
        bar.set_state("LIVE", ("HELD", "PRISM"), "UNLOCKED", ("ACTIVE", "10.0.0.*", "t"))
        assert bar.slots["radio"].glyph._color == t["live"]
        assert t["live"] in bar.slots["radio"].value.styleSheet()
        assert bar.slots["engagement"].glyph._color == t["live"]
        assert bar.slots["engagement"].glyph.shape() == "diamond"      # shape still carries it
        assert t["live"] in bar.slots["engagement"].value.styleSheet()
        assert bar.slots["tx"].glyph._color == t["alert"]
        assert bar.slots["tx"].text() == "UNLOCKED"
        # the off / caution states are unchanged
        bar.set_state("LIVE", ("ACQUIRING", "PRISM"), "OFF", ("EXPIRED", "x", "t"))
        assert bar.slots["radio"].glyph._color == t["warn"]
        assert bar.slots["engagement"].glyph._color == t["alert"]
        bar.set_state("LIVE", ("FREE", ""), "OFF", ("NONE", "", ""))
        assert bar.slots["radio"].glyph._color == t["muted"]
        assert bar.slots["engagement"].glyph._color == t["muted"]
    finally:
        _close(hub)


# ================================================================ U3 / U4 maps
def _atlas(hub):
    hub.open_callsign("ATLAS")
    _pump(250)
    atlas = hub.page_app("ATLAS")                  # the MAP child (AtlasApp)
    return atlas._host, atlas


@pytest.mark.parametrize("mode", THEMES)
def test_u3_atlas_map_gets_most_of_the_width(mode):
    """The map had 3/5 of what the rail left (~690 px of 1280). Now the side column is held to
    SIDE_W and the map takes the rest."""
    hub = _big_hub(mode)
    try:
        _page, atlas = _atlas(hub)
        assert atlas.map.width() >= 760, atlas.map.width()
        assert atlas._side.width() == atlas.SIDE_W
        # the side column's contents still fit it (no clipped layer chip)
        for b in atlas._layer_btns.values():
            assert b.width() >= b.minimumSizeHint().width(), b.text()
            assert b.geometry().right() < b.parentWidget().width(), b.text()
    finally:
        _close(hub)


def _press(hub, text):
    hub.activateWindow()
    hub.setFocus()
    _pump(20)
    QtTest.QTest.keyClick(hub, text)
    _pump(120)


@pytest.mark.parametrize("mode", THEMES)
def test_u4_f_hides_atlas_side_column_and_rail_map_runs_full_width(mode):
    hub = _big_hub(mode)
    try:
        page, atlas = _atlas(hub)
        w0 = atlas.map.width()
        _press(hub, "f")
        assert atlas.side_hidden()
        assert atlas._side.isHidden() and page._rail.isHidden()
        assert atlas.map.width() >= 1240, atlas.map.width()
        assert atlas._side_toggle.text().startswith("SHOW PANELS")
        assert atlas._side_toggle.isVisible()
        _press(hub, "f")
        assert not atlas.side_hidden()
        assert atlas._side.isVisible() and page._rail.isVisible()
        assert atlas.map.width() == w0
        # the corner button does the same as the key
        atlas._side_toggle.click()
        _pump(80)
        assert atlas.side_hidden() and atlas._side.isHidden()
        atlas._side_toggle.click()
        _pump(80)
        assert not atlas.side_hidden()
    finally:
        _close(hub)


def test_u4_rail_comes_back_on_a_tab_without_a_map_and_hides_again_on_return():
    hub = _big_hub()
    try:
        page, atlas = _atlas(hub)
        atlas.toggle_side(True)
        _pump(50)
        assert page._rail.isHidden()
        page.switch_subtab("PASSES")
        _pump(80)
        assert page._rail.isVisible(), "a tab with no map must keep its sub-tab rail"
        assert page.handle_key("f") is False                 # nothing to collapse there
        page.switch_subtab("MAP")
        _pump(80)
        assert page._rail.isHidden() and atlas._side.isHidden()
    finally:
        _close(hub)


def test_u4_hiding_the_side_column_is_layout_only_the_list_keeps_updating():
    """Collapsing never stops a worker or a feed: contacts published while the list is hidden are
    in the list when it comes back, and the worker object is untouched."""
    import time
    from palisade_qt import eventbus
    eventbus.set_home((39.7, -104.9), "test")
    hub = _big_hub(demo=True)
    try:
        _page, atlas = _atlas(hub)
        worker = atlas._worker
        layers = set(atlas._layers)
        atlas.toggle_side(True)
        _pump(50)
        ev = eventbus.contact("ADS-B", "u4x", 39.8, -104.8, alt=9000, kind="aircraft",
                              label="U4TEST")
        ev["ts"] = time.time()
        atlas._on_event(ev)
        atlas._render()
        _pump(100)
        assert atlas._worker is worker and atlas._layers == layers
        assert any("U4TEST" in str(r.get("label", "")) for r in atlas.feed.model.rows)
        atlas.toggle_side(False)
        _pump(50)
        assert any("U4TEST" in str(r.get("label", "")) for r in atlas.feed.model.rows)
    finally:
        eventbus.set_home(None)
        _close(hub)


@pytest.mark.parametrize("mode", THEMES)
def test_u4_f_hides_the_ops_rail_and_the_scope_takes_the_width(mode):
    hub = _big_hub(mode)
    try:
        hub.open_callsign("OPS")
        _pump(200)
        ops = hub.ops
        w0, h0 = ops.ppi.width(), ops.ppi.height()
        assert h0 >= 560, h0                     # the caption moved onto the count row
        _press(hub, "f")
        assert ops.side_hidden() and ops._rail_w.isHidden()
        _pump(100)
        assert ops.ppi.width() >= 1240, ops.ppi.width()
        _press(hub, "f")
        _pump(100)
        assert ops._rail_w.isVisible()
        assert abs(ops.ppi.width() - w0) <= 2, (ops.ppi.width(), w0)
    finally:
        _close(hub)


def test_u4_toggle_stays_on_top_of_the_home_not_set_cover():
    """With no HOME the map / scope is covered (N26). The F button must still be clickable."""
    from palisade_qt import eventbus
    eventbus.set_home(None)
    hub = _big_hub()
    try:
        for cs in ("OPS", "ATLAS"):
            hub.open_callsign(cs)
            _pump(200)
            app = hub.ops if cs == "OPS" else hub.page_app("ATLAS")
            tgl = app._side_toggle
            target = tgl.parentWidget()
            assert app._home_cover.shown(), cs
            app._home_cover.show(True)               # a later re-show must not bury it
            _pump(30)
            hit = target.childAt(tgl.geometry().center())
            assert hit is tgl or tgl.isAncestorOf(hit), (cs, hit)
    finally:
        _close(hub)


def test_u4_pages_without_a_map_ignore_f_and_the_key_map_lists_it():
    from palisade_qt import panels
    assert any(k == "F" and "full map" in what for k, what in panels.KEYMAP)
    hub = _big_hub()
    try:
        for cs in ("RECON", "FORGE"):
            hub.open_callsign(cs)
            _pump(150)
            page = hub.pages[cs]
            assert page.handle_key("f") is False, cs
            assert not page.side_hidden()
    finally:
        _close(hub)


def test_u4_typing_f_in_a_text_field_never_collapses():
    hub = _big_hub()
    try:
        _page, atlas = _atlas(hub)
        from PySide6 import QtWidgets
        le = QtWidgets.QLineEdit(atlas)
        le.show()
        le.setFocus()
        _pump(30)
        QtTest.QTest.keyClick(le, "f")
        _pump(60)
        assert le.text() == "f" and not atlas.side_hidden()
    finally:
        _close(hub)

