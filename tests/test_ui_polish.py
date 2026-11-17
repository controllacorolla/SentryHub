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



# ================================================================ U5 basemap orientation
def _tile_png(r, g):
    """A 256 px tile: flat R/G (they name the tile), noisy B (so it is not a 'blank' tile)."""
    import numpy as np
    from PySide6 import QtGui
    rng = np.random.default_rng(r * 256 + g)
    a = np.zeros((256, 256, 4), dtype=np.uint8)
    a[..., 0], a[..., 1], a[..., 3] = r, g, 255
    a[..., 2] = rng.integers(0, 255, (256, 256), dtype=np.uint8)
    img = QtGui.QImage(a.data, 256, 256, 256 * 4, QtGui.QImage.Format.Format_RGBA8888).copy()
    buf = QtCore.QBuffer()
    buf.open(QtCore.QIODevice.WriteOnly)
    img.save(buf, "PNG")
    return bytes(buf.data())


def _fake_tiles(monkeypatch, tmp_path):
    from palisade_qt.kit import tiles
    seen = []

    def fetch(url_tpl, z, tx, ty, cache_dir):
        seen.append((url_tpl, z, tx, ty))
        return _tile_png(20 + 7 * (tx % 30), 20 + 7 * (ty % 30))
    monkeypatch.setattr(tiles, "_fetch_one", fetch)
    monkeypatch.setattr(tiles, "CACHE_ROOT", tmp_path)
    return seen


@pytest.mark.parametrize("global_order", ("col-major", "row-major"))
def test_u5_basemap_is_north_up_east_right_whatever_pyqtgraph_global_order(
        monkeypatch, tmp_path, global_order):
    """Device 2026-11-17: the ATLAS map drew rotated 90 degrees (Front Range along the bottom)
    whenever ATLAS opened before PRISM — only PRISM's scope set pyqtgraph's global
    imageAxisOrder. With the global at either value, the pixel drawn at a point's map position
    comes from that point's own tile."""
    import math
    import numpy as np
    import pyqtgraph as pg
    from palisade_qt.kit import tiles, mappanel
    _fake_tiles(monkeypatch, tmp_path)
    old = pg.getConfigOption("imageAxisOrder")
    pg.setConfigOptions(imageAxisOrder=global_order)
    try:
        home = (39.7392, -104.9903)                  # Denver
        m = mappanel.MapPanel(span_nm=80, home_lat=home[0], home_lon=home[1])
        m.resize(900, 640)
        layer = m._tiles
        arr, x0, y0, x1, y1 = layer._build("satellite")
        m._base._on_tiles(arr, x0, y0, x1, y1)
        z = tiles.tile_span(home[0], home[1], layer.view or (-80, 80, -80, 80, 800))[0]
        shown = m._tile_img.image
        cos_lat = math.cos(math.radians(home[0]))
        for dn, de in ((60, -60), (60, 60), (-60, -60), (-60, 60), (0, 0), (25, -70)):
            lat, lon = home[0] + dn / 60.0, home[1] + de / (60.0 * cos_lat)
            x, y = tiles._nm_from_home(home[0], home[1], lat, lon)
            p = m._tile_img.mapFromView(QtCore.QPointF(x, y))
            col, row = int(p.x()), int(p.y())
            assert 0 <= row < shown.shape[0] and 0 <= col < shown.shape[1], (dn, de, row, col)
            tx, ty = tiles._tile_xy(lat, lon, z)
            want = np.array([[[20 + 7 * (tx % 30), 20 + 7 * (ty % 30), 0, 255]]], dtype=np.uint8)
            want = mappanel.tint(want, "dark_sat")[0, 0]
            assert tuple(shown[row, col, :2]) == tuple(want[:2]), (global_order, dn, de)
    finally:
        pg.setConfigOptions(imageAxisOrder=old)


def test_u5_atlas_opened_first_has_a_row_major_map_image():
    """The regression in situ: a fresh hub, ATLAS opened before PRISM was ever built."""
    hub = _big_hub()
    try:
        _page, atlas = _atlas(hub)
        assert "PRISM" not in [k for k, v in hub.pages.items() if v is not None and
                               type(v).__name__ == "PrismApp"]
        assert atlas.map._tile_img.axisOrder == "row-major"
        assert hub.ops.ppi._base.img.axisOrder == "row-major"
    finally:
        _close(hub)


# ================================================================ U6 pan / zoom, tiles follow
def test_u6_map_pans_and_zooms_and_tiles_follow_the_view(monkeypatch, tmp_path):
    from palisade_qt.kit import tiles
    seen = _fake_tiles(monkeypatch, tmp_path)
    hub = _big_hub()
    try:
        _page, atlas = _atlas(hub)
        m = atlas.map
        vb = m.plot.getViewBox()
        assert vb.state["mouseEnabled"] == [True, True]
        w0, h0 = m.view_span()
        assert atlas.handle_key("+") is True
        _pump(60)
        w1, h1 = m.view_span()
        assert w1 == pytest.approx(w0 / 2, rel=0.05) and h1 == pytest.approx(h0 / 2, rel=0.05)
        atlas.handle_key("-")
        atlas.handle_key("-")
        _pump(60)
        assert m.view_span()[0] == pytest.approx(w0 * 2, rel=0.05)
        # buttons do the same; HOME puts the default range back
        m._zoom_btns[1].click()
        _pump(60)
        assert m.view_span()[0] == pytest.approx(w0, rel=0.05)
        vb.translateBy(x=40, y=-20)
        _pump(60)
        (x0, x1), _ = vb.viewRange()
        assert (x0 + x1) / 2 == pytest.approx(40, abs=1)
        m._zoom_btns[2].click()
        _pump(60)
        (x0, x1), (y0, y1) = vb.viewRange()
        assert abs((x0 + x1) / 2) < 1 and abs((y0 + y1) / 2) < 1
        # the tile range follows: zoomed in -> a higher zoom level over a smaller area
        home = (39.7, -104.9)
        z_wide = tiles.tile_span(home[0], home[1], (-160, 160, -160, 160, 1200))[0]
        z_tight = tiles.tile_span(home[0], home[1], (-10, 10, -10, 10, 1200))[0]
        assert z_tight > z_wide
        for v in ((-600, 600, -600, 600, 1280), (-1, 1, -1, 1, 1280)):
            z, a, b, c, d = tiles.tile_span(home[0], home[1], v)
            assert (c - a + 1) * (d - b + 1) <= tiles.MAX_TILES and 3 <= z <= 16
        # and the map hands its live view to the tile layer when it refreshes
        m._base.can_fetch = True
        m._base.tiles.fetch = lambda style: seen.append(("fetch", style))
        m.zoom(0.5)
        m._base.refresh()
        assert m._tiles.view[:4] == pytest.approx(
            tuple(vb.viewRange()[0]) + tuple(vb.viewRange()[1]))
        assert ("fetch", "satellite") in seen
    finally:
        _close(hub)


def test_u6_dark_and_light_tint_and_the_satellite_source_chain(monkeypatch, tmp_path):
    import numpy as np
    from palisade_qt.kit import tiles, mappanel
    a = np.full((2, 2, 4), 200, dtype=np.uint8)
    assert mappanel.tint(a, "dark_sat")[0, 0, 0] < 100
    assert mappanel.tint(a, "light_sat")[0, 0, 0] > 200
    assert [n for n, _ in tiles.TILE_SOURCES["satellite"]] == ["esri", "usgs", "eox"]
    # a source that answers blank (no coverage) falls through to the next
    calls = []


    def fetch(url_tpl, z, tx, ty, cache_dir):
        calls.append(url_tpl)
        if "arcgisonline" in url_tpl:
            return None                                  # Esri down
        if "nationalmap" in url_tpl:
            from PySide6 import QtGui
            img = QtGui.QImage(256, 256, QtGui.QImage.Format.Format_RGBA8888)
            img.fill(QtGui.QColor(0, 0, 0, 0))           # USGS: transparent = no coverage
            buf = QtCore.QBuffer()
            buf.open(QtCore.QIODevice.WriteOnly)
            img.save(buf, "PNG")
            return bytes(buf.data())
        return _tile_png(90, 140)
    monkeypatch.setattr(tiles, "_fetch_one", fetch)
    monkeypatch.setattr(tiles, "CACHE_ROOT", tmp_path)
    layer = tiles.TileLayer(home_lat=51.5, home_lon=-0.1, span_nm=20)
    arr = layer._build("satellite")[0]
    assert (arr[..., 0] == 90).any() and (arr[..., 1] == 140).any()
    assert any("eox" in c for c in calls)
    # cache is per source, so a cached Esri placeholder from before is never read again
    assert all(p.name in ("esri", "usgs", "eox") for p in (tmp_path / "satellite").iterdir())


# ================================================================ U7 GPS -> HOME (minimal)
def _settings(hub):
    hub.open_callsign("SYSTEM")
    _pump(150)
    page = hub.pages["SYSTEM"]
    page.switch_subtab("SETTINGS")
    _pump(100)
    return page.current_child()


def _wait(pred, ms=3000):
    import time
    t = time.time()
    while time.time() - t < ms / 1000:
        _pump(20)
        if pred():
            return True
    return False


def test_u7_use_gps_fills_home_but_never_saves_it(monkeypatch):
    from palisade_qt import eventbus
    eventbus.set_home(None)
    hub = _big_hub()
    try:
        more = _settings(hub)
        more.set_home.setText("")
        more._gps_reader = lambda: {"class": "TPV", "mode": 3, "lat": 39.7392, "lon": -104.9903}
        more.gps_btn.click()
        assert _wait(lambda: more.set_home.text() == "39.7392, -104.9903")
        assert "press SAVE" in more.set_msg.text()
        assert not eventbus.home_set(), "offering a fix must not set HOME"
        more._save_settings()
        assert eventbus.home() == pytest.approx((39.7392, -104.9903))
    finally:
        eventbus.set_home(None)
        _close(hub)


def test_u7_no_fix_says_so_and_keeps_manual_entry():
    from palisade_qt import eventbus
    eventbus.set_home(None)
    hub = _big_hub()
    try:
        more = _settings(hub)
        more.set_home.setText("39.7, -104.9")
        more._gps_reader = lambda: None
        more.gps_btn.click()
        assert _wait(lambda: "NO GPS FIX" in more.set_msg.text())
        assert more.set_home.text() == "39.7, -104.9" and more.gps_btn.isEnabled()
        # an automatic read never overwrites what was typed, even with a fix
        more._gps_reader = lambda: {"mode": 2, "lat": 10.0, "lon": 20.0}
        more.read_gps(auto=True)
        assert _wait(lambda: more._gps_last == (10.0, 20.0))
        assert more.set_home.text() == "39.7, -104.9"
    finally:
        eventbus.set_home(None)
        _close(hub)


def test_u7_typed_home_in_the_other_hemisphere_from_gps_is_rejected():
    """39.7, 104.9 (minus sign dropped) is in China; with a GPS fix at -104.9 it is refused."""
    from palisade_qt import eventbus
    eventbus.set_home(None)
    hub = _big_hub()
    try:
        more = _settings(hub)
        more._gps_reader = lambda: {"mode": 3, "lat": 39.74, "lon": -104.99}
        more.read_gps()
        assert _wait(lambda: more._gps_last is not None)
        more.set_home.setText("39.74, 104.99")
        more._save_settings()
        assert not eventbus.home_set()
        assert "other hemisphere" in more.set_msg.text() and "west is negative" in more.set_msg.text()
        more.set_home.setText("-39.74, -104.99")
        more._save_settings()
        assert not eventbus.home_set() and "south is negative" in more.set_msg.text()
        more.set_home.setText("39.74, -104.99")
        more._save_settings()
        assert eventbus.home() == pytest.approx((39.74, -104.99))
    finally:
        eventbus.set_home(None)
        _close(hub)
