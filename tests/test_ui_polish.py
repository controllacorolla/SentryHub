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


MIN_KEY_GAP = 8      # px of bare rail between two keys' text (was ~2 across the old strip)


# ================================================================ U1 nav keys
@pytest.mark.parametrize("mode", THEMES)
def test_u1_every_nav_key_places_its_two_lines_on_the_same_baselines(mode):
    """'spectrum' (descender) and 'map' / 'survey' sat at different heights, so a label read as
    belonging to the neighbouring key. Every key now places both lines on the same baselines,
    current page or not, and each key's ink stays inside it."""
    from palisade_qt.ops import CALLSIGNS
    hub = _big_hub(mode)
    try:
        for current in ("OPS", "PRISM"):
            hub.topbar.set_active_page(current)
            _pump(40)
            keys = hub.topbar.nav_keys
            bases = {n: keys[n].baselines() for n, _ in CALLSIGNS if n in keys}
            assert None not in [b for pair in bases.values() for b in pair], bases
            assert len(set(bases.values())) == 1, (mode, current, bases)
            for n in bases:
                call, label = _text_rects(keys[n])
                assert call.bottom() < label.top(), (n, call, label)
                assert call.top() >= 0 and label.bottom() < keys[n].height(), n
                assert call.left() >= 0 and call.right() < keys[n].width(), n
                assert label.left() >= 0 and label.right() < keys[n].width(), n
    finally:
        _close(hub)


@pytest.mark.parametrize("mode", THEMES)
def test_u1_neighbouring_nav_keys_never_run_together(mode):
    """'4 PROWL5 RECON': text of two keys touched. In the left rail there are at least
    MIN_KEY_GAP px of bare rail between one key's label ink and the next key's callsign ink."""
    hub = _big_hub(mode)
    try:
        keys = sorted(hub.topbar.nav_keys.values(), key=lambda k: k.y())
        assert len(keys) >= 7
        for a, b in zip(keys, keys[1:]):
            a_bot = a.mapTo(hub, QtCore.QPoint(0, _text_rects(a)[1].bottom())).y()
            b_top = b.mapTo(hub, QtCore.QPoint(0, _text_rects(b)[0].top())).y()
            assert b_top - a_bot - 1 >= MIN_KEY_GAP, (mode, a.callsign, b.callsign)
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


# ================================================================ U8 left page rail
def test_u8_page_keys_are_stacked_down_the_left_and_1_to_7_still_work():
    """Owner 2026-11-17: 'I would rather have OPS, RECON etc. vertically stacked on the left'."""
    from palisade_qt.ops import CALLSIGNS
    hub = _big_hub()
    try:
        rail = hub.nav_rail
        assert rail is not None and rail.isVisible()
        assert hub.topbar.nav_keys and all(k.parentWidget() is rail
                                           for k in hub.topbar.nav_keys.values())
        keys = [hub.topbar.nav_keys[n] for n, _ in CALLSIGNS if n in hub.topbar.nav_keys]
        xs = {k.mapTo(hub, QtCore.QPoint(0, 0)).x() for k in keys}
        ys = [k.mapTo(hub, QtCore.QPoint(0, 0)).y() for k in keys]
        assert len(xs) == 1 and ys == sorted(ys) and len(set(ys)) == len(ys)
        assert rail.mapTo(hub, QtCore.QPoint(0, 0)).x() <= 8          # the left edge
        assert hub.stack.mapTo(hub, QtCore.QPoint(0, 0)).x() >= rail.width()
        assert keys[-1].geometry().bottom() < rail.height()          # all seven fit 720 px
        for k in keys:                                               # text inside the key
            for r in _text_rects(k):
                assert r.left() >= 0 and r.right() < k.width(), k.callsign
        # number keys still switch pages; the strip title follows
        _press(hub, "2")
        assert hub._current == "ATLAS" and "ATLAS" in hub.topbar.page_title.text()
        _press(hub, "1")
        assert hub._current == "OPS"
        # a click on a rail key opens its page
        hub.topbar.nav_keys["ATLAS"].click()
        _pump(80)
        assert hub._current == "ATLAS"
    finally:
        _close(hub)


def test_u8_f_takes_the_page_rail_with_the_side_panels_and_page_switch_restores_it():
    hub = _big_hub()
    try:
        _page, atlas = _atlas(hub)
        _press(hub, "f")
        assert hub.nav_rail.isHidden()
        assert atlas.map.width() >= 1240
        _press(hub, "3")                                 # PRISM: no map -> the rail is back
        assert hub._current == "PRISM" and hub.nav_rail.isVisible()
        _press(hub, "2")                                 # ATLAS remembers it was full-map
        assert hub.nav_rail.isHidden() and atlas.side_hidden()
        _press(hub, "f")
        assert hub.nav_rail.isVisible()
    finally:
        _close(hub)


# ================================================================ U9 OPS fed from launch
def test_u9_demo_ops_draws_contacts_without_atlas_ever_being_opened():
    """Device 2026-11-17 (--demo): the OPS map stayed empty — ATLAS's worker is the contact
    source and it only started when ATLAS was opened."""
    import time
    hub = _big_hub(demo=True)
    try:
        assert hub._current == "OPS"
        assert hub.start_background_feeds() is True
        t = time.time()
        while time.time() - t < 6 and not hub.ops.ppi.track_spots:
            _pump(100)
            hub.ops._refresh_ppi()
        assert hub._current == "OPS", "starting the feed must not switch page"
        assert len(hub.ops.ppi.track_spots) >= 3
    finally:
        _close(hub)


def test_u9_hidden_live_atlas_worker_runs_passive_feeds_only(monkeypatch):
    """Hidden, the live worker publishes the passive (file) feeds; it never starts the BLE scan
    and never takes a lease."""
    from palisade_qt import atlas as A, eventbus
    w = A.AtlasLiveWorker()
    w._hidden = True
    calls = []
    monkeypatch.setattr(w, "_ensure_sources", lambda: calls.append("ensure"))
    monkeypatch.setattr(w, "_adsb_contacts", lambda: [eventbus.contact("ADS-B", "H1", 1.0, 2.0,
                                                                        kind="aircraft")])
    monkeypatch.setattr(w, "_reconcile_rid", lambda: calls.append("rid"))
    monkeypatch.setattr(A, "balloon_contacts", lambda: [])
    monkeypatch.setattr(A, "df_contacts", lambda: [])
    got = []
    eventbus.bus.published.connect(got.append)
    try:
        w.step()
    finally:
        eventbus.bus.published.disconnect(got.append)
    assert "rid" not in calls and "ensure" in calls
    assert any(e["payload"]["id"] == "H1" for e in got)
    assert not w._lease_srcs


# ================================================================ U10 track symbols
def _render_one(c, mode="dark"):
    from palisade_qt.kit import mappanel, tracksym
    tracksym.AIR_SIZE = 80                       # big enough to measure its shape
    m = mappanel.MapPanel(span_nm=20, mode=mode, home_lat=None, home_lon=None)
    m.resize(400, 400)
    m.show()
    _pump(80)
    m.set_tracks([c])
    m._place_labels([], [])
    _pump(80)
    img = m.plot.grab().toImage()
    m.close()
    tracksym.AIR_SIZE = 20
    return img


def _ink(img, rgb, tol=40):
    pts = []
    for y in range(img.height()):
        for x in range(img.width()):
            q = img.pixelColor(x, y)
            if abs(q.red() - rgb[0]) + abs(q.green() - rgb[1]) + abs(q.blue() - rgb[2]) < tol:
                pts.append((x, y))
    return pts


@pytest.mark.parametrize("hdg,axis,sign", ((0, 1, -1), (90, 0, 1), (180, 1, 1), (270, 0, -1)))
def test_u10_aircraft_glyph_points_along_its_course_and_its_leader(hdg, axis, sign):
    """The nose (the glyph's narrow end) and the leader both point along the reported course."""
    from palisade_qt.kit import tracksym
    c = {"id": "A", "x": 0.0, "y": 0.0, "kind": "aircraft", "track": hdg, "spd": 0}
    pts = _ink(_render_one(c), (0x5A, 0xB8, 0xFF))
    assert len(pts) > 30
    lo = min(p[axis] for p in pts)
    hi = max(p[axis] for p in pts)
    mid = (lo + hi) / 2.0
    cen = sum(p[axis] for p in pts) / len(pts)
    # the delta's mass sits toward its tail, so the centroid is on the side away from the nose
    assert (cen - mid) * sign < 0, (hdg, cen, mid)
    # and the leader goes the same way (nm frame: north = +y)
    ld = tracksym.leader(dict(c, spd=300))
    dx, dy = ld[2] - ld[0], ld[3] - ld[1]
    screen = (dx, -dy)                                # screen y grows downward
    assert screen[axis] * sign > 0


def test_u10_colour_by_type_and_no_heading_means_no_direction():
    from palisade_qt.kit import tracksym as T
    base = {"id": "x", "x": 0, "y": 0}
    assert T.classify(dict(base, kind="aircraft")) == "plane"
    assert T.classify(dict(base, kind="aircraft", category="A7")) == "helo"
    assert T.classify(dict(base, kind="aircraft", dbflags=1)) == "mil"
    assert T.classify(dict(base, kind="aircraft", mil=True, category="A7")) == "mil"
    assert T.classify(dict(base, kind="drone")) == "drone"
    assert T.classify(dict(base, kind="vessel")) == "vessel"
    assert T.classify(dict(base, kind="station")) == "station"
    cols = {T.CLASS_COLOR[k] for k in ("plane", "helo", "mil", "drone", "vessel", "station",
                                       "balloon", "df")}
    assert len(cols) == 8, "every legend class has its own colour"
    assert T.color(dict(base, kind="aircraft", severity="alert")) == T.EMERGENCY
    assert T.color(dict(base, kind="drone", trust="unconfirmed")) == T.UNCONFIRMED
    # no heading -> the ring (no direction drawn), and no leader
    assert T.glyph(dict(base, kind="aircraft")) is T.symbol("ring", None)
    assert T.leader(dict(base, kind="aircraft", spd=400)) is None
    assert T.leader(dict(base, kind="aircraft", track=45, spd=0)) is None
    # data block: callsign + flight level
    assert T.data_block(dict(base, kind="aircraft", label="UAL1", alt=12049)) == "UAL1 FL120"
    assert T.data_block(dict(base, kind="vessel", label="MMSI")) == "MMSI"
    # every class in the legend
    html = T.legend_html()
    for _k, name in T.LEGEND:
        assert name in html


def test_u10_adsb_military_and_rotorcraft_flags_reach_the_contact():
    from palisade_qt import atlas as A
    ev = A.adsb_to_contact({"hex": "ae1234", "flight": "RCH1 ", "lat": 39.0, "lon": -104.0,
                            "alt_baro": 20000, "track": 270.5, "gs": 300, "category": "A7",
                            "dbFlags": 1})
    pl = ev["payload"]
    assert pl["category"] == "A7" and pl["dbflags"] == 1 and pl["track"] == 270.5
    from palisade_qt.kit import tracksym as T
    assert T.classify(dict(pl, x=0, y=0)) == "mil"
    ev2 = A.adsb_to_contact({"hex": "a1", "lat": 39.0, "lon": -104.0, "dbFlags": "junk"})
    assert ev2["payload"]["dbflags"] is None


def test_u10_atlas_and_ops_draw_tracks_with_leaders_trails_and_a_legend():
    import time
    from palisade_qt import eventbus
    eventbus.set_home((39.7, -104.9), "test")
    hub = _big_hub()
    try:
        _page, atlas = _atlas(hub)
        assert atlas.map.legend.isVisible() and "PLANE" in atlas.map.legend.text()
        for i, (lat, lon) in enumerate(((39.80, -104.80), (39.81, -104.79), (39.82, -104.78))):
            ev = eventbus.contact("ADS-B", "T1", lat, lon, alt=12000, kind="aircraft",
                                  track=45, spd=300, label="T1")
            ev["ts"] = time.time()
            atlas._on_event(ev)
            hub.ops._on_event(ev)
        atlas._render()
        hub.ops._refresh_ppi()
        assert len(atlas.map.track_spots) == 1 and atlas.map.leader_count == 1
        assert atlas.map.trail_count == 2
        assert len(hub.ops.ppi.track_spots) == 1
        assert any("FL120" in lbl.textItem.toPlainText() for lbl in atlas.map._contact_labels)
    finally:
        eventbus.set_home(None)
        _close(hub)
