"""Stage 2 of the device-run-2 fix plan (plan/briefs/device-fix-plan.md, 2026-11-18): OPS + maps.

7 maps: with NET OFFLINE (the default) every tile fetch was refused and swallowed, so the map was
black with no word why. Now the map says why, offers a one-tap DOWNLOAD MAP (owner's pick: fetch this
view once, logged as granted, NET unchanged) and refetches when NET changes.
8 OPS: every card opens its page; an empty map says why (ATLAS feed health); NEXT PASS is real or
says why not. 9 legend: one tight row along the bottom of the scope. 10 SKY DOME explains itself.
Headless (Qt offscreen), real hub at 1280x720, no network.
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

from PySide6 import QtCore, QtGui, QtWidgets  # noqa: E402

from test_cl1_screen import _pump, _hub, _isolate  # noqa: E402

_isolate = _isolate


@pytest.fixture
def home():
    from palisade_qt import eventbus
    saved = (eventbus.HOME, eventbus.HOME_SOURCE)
    eventbus.set_home((39.6261, -104.968), "settings")
    yield
    eventbus.HOME, eventbus.HOME_SOURCE = saved


@pytest.fixture
def offline():
    import netpolicy
    netpolicy.reset_for_tests()
    netpolicy.set_mode("OFFLINE", persist=False)
    yield netpolicy
    netpolicy.reset_for_tests()


def _big_hub(demo=False):
    hub = _hub(demo=demo)
    hub.resize(1280, 720)
    _pump(200)
    return hub


def _close(hub):
    hub.close()
    _pump(150)


def _click(w):
    pos = QtCore.QPointF(w.width() / 2, w.height() / 2)
    for t in (QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseButtonRelease):
        ev = QtGui.QMouseEvent(t, pos, w.mapToGlobal(pos), QtCore.Qt.LeftButton,
                               QtCore.Qt.LeftButton, QtCore.Qt.NoModifier)
        QtWidgets.QApplication.sendEvent(w, ev)
    _pump(120)


# ---------------------------------------------------------------- 7 maps
def test_s2_7_imagery_state_names_the_reason():
    from palisade_qt.kit.tiles import imagery_state
    assert imagery_state({}) == ("none", "")
    assert imagery_state({"tiles": 4, "shown": 4}) == ("ok", "")
    st, text = imagery_state({"tiles": 4, "shown": 0, "blocked": 4})
    assert st == "offline" and "NET is OFFLINE" in text and "DOWNLOAD MAP" in text
    st, text = imagery_state({"tiles": 4, "shown": 2, "blocked": 2})
    assert st == "partial" and "DOWNLOAD MAP" in text
    st, text = imagery_state({"tiles": 4, "shown": 0, "failed": 4, "error": "timed out"})
    assert st == "failed" and "timed out" in text


def test_s2_7_fetch_counts_refusals_and_a_granted_fetch_is_logged(tmp_path, offline,
                                                                  monkeypatch):
    """OFFLINE refuses a tile and says so (it used to be swallowed); the operator's one tap
    passes, is logged as granted, and NET stays OFFLINE. No network: urllib is stubbed."""
    import urllib.request
    from palisade_qt.kit import tiles

    class Resp:
        def read(self):
            return b"PNGDATA"
    calls = []
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, **kw: calls.append(req) or Resp())
    why = {}
    tpl = "https://tiles.example.test/{z}/{y}/{x}.png"
    assert tiles._fetch_one(tpl, 5, 1, 2, tmp_path, why) is None
    assert why.get("blocked") == 1 and not calls
    assert any(e[2] == "blocked" and e[4] == "map tiles" for e in offline.log())
    assert tiles._fetch_one(tpl, 5, 1, 2, tmp_path, why, granted=True) == b"PNGDATA"
    assert len(calls) == 1 and (tmp_path / "1_2.png").read_bytes() == b"PNGDATA"
    assert offline.mode() == "OFFLINE"
    granted = [e for e in offline.log() if e[2] == "granted"]
    assert granted and granted[-1][1] == "OFFLINE" and "operator" in granted[-1][4]
    # cached: the next (ungranted, OFFLINE) build reads it from disk
    why2 = {}
    assert tiles._fetch_one(tpl, 5, 1, 2, tmp_path, why2) == b"PNGDATA" and not why2


def test_s2_7_a_granted_build_is_one_shot(monkeypatch, tmp_path):
    from palisade_qt.kit import tiles
    monkeypatch.setattr(tiles, "CACHE_ROOT", tmp_path)
    seen = []
    monkeypatch.setattr(tiles, "_fetch_one", lambda *a, **kw: seen.append(kw.get("granted")))
    lay = tiles.TileLayer(home_lat=39.6, home_lon=-104.9, span_nm=10)
    lay._grant_next = True
    lay._work("satellite")
    assert seen and all(seen)
    seen.clear()
    lay._work("satellite")
    assert seen and not any(seen), "the grant covers one build only"


def test_s2_7_map_says_why_it_is_blank_and_offers_download(home):
    hub = _big_hub()
    try:
        hub.open_callsign("ATLAS")
        _pump(200)
        base = hub.page_app("ATLAS").map._base
        from palisade_qt.kit.tiles import imagery_state
        base._on_imagery(*imagery_state({"tiles": 6, "shown": 0, "blocked": 6}))
        _pump(50)
        assert base.banner.isVisible() and "OFFLINE" in base.banner.text()
        assert base.download_btn.isVisible()
        r = base.banner.geometry()
        assert base.plot.rect().contains(r) and r.height() >= base.banner.sizeHint().height() - 2
        asked = []
        base.tiles.download = lambda style: asked.append(style)
        base.download_btn.click()
        assert asked and not base.download_btn.isEnabled()
        base._on_imagery("ok", "")
        assert not base.banner.isVisible() and not base.download_btn.isVisible()
        # a network failure has no download button (a tap would not help)
        base._on_imagery(*imagery_state({"tiles": 6, "shown": 0, "failed": 6, "error": "x"}))
        assert base.banner.isVisible() and not base.download_btn.isVisible()
    finally:
        _close(hub)


def test_s2_7_net_change_refetches_maps_that_had_no_imagery(home):
    from palisade_qt.kit.mappanel import BaseMap
    hub = _big_hub()
    try:
        hub.open_callsign("ATLAS")
        _pump(200)
        maps = hub.findChildren(BaseMap)
        assert len(maps) >= 2                         # ATLAS map + the OPS scope
        hits = []
        for b in maps:
            b.refresh = (lambda b=b: hits.append(b))
        maps[0].imagery = ("offline", "x")
        maps[1].imagery = ("ok", "")
        hub._on_net()
        assert hits == [maps[0]]
    finally:
        _close(hub)


# ---------------------------------------------------------------- 8 OPS
def test_s2_8_ops_cards_open_their_pages():
    hub = _big_hub(demo=True)
    try:
        ops = hub.ops
        _click(ops.card_babel)
        assert hub._current == "PROWL" and hub.pages["PROWL"].current_subtab() == "DECODE"
        hub.open_callsign("OPS")
        _click(ops.mini_pass[0])
        assert hub._current == "ATLAS" and hub.pages["ATLAS"].current_subtab() == "PASSES"
        hub.open_callsign("OPS")
        _click(ops.mini_pwr[0])
        assert hub._current == "SYSTEM" and hub.pages["SYSTEM"].current_subtab() == "SETTINGS"
        hub.open_callsign("OPS")
        _click(ops.card_prism)
        assert hub._current == "PRISM"
        hub.open_callsign("OPS")
        _click(ops.big)
        assert hub._current == "ATLAS"
        hub.open_callsign("OPS")
        _click(ops.card_alert)
        assert hub.alerts_drawer.isVisible()
        for c in (ops.card_prism, ops.card_babel, ops.card_alert, ops.mini_pass[0],
                  ops.mini_pwr[0]):
            assert c.toolTip() and c.cursor().shape() == QtCore.Qt.PointingHandCursor
    finally:
        _close(hub)


def test_s2_8_an_empty_ops_map_says_why(home):
    hub = _big_hub()
    try:
        ops = hub.ops
        ops._refresh_ppi()
        assert ops.big.text() == "0" and "contact feeds not running" in ops.sub.text()
        hub.start_background_feeds()
        _pump(1600)
        ops._refresh_ppi()
        assert ops.sub.text().startswith("no contacts · ") and "ADS-B" in ops.sub.text(), \
            ops.sub.text()
    finally:
        _close(hub)


def test_s2_8_empty_reason_without_home():
    from palisade_qt import eventbus
    saved = (eventbus.HOME, eventbus.HOME_SOURCE)
    eventbus.HOME, eventbus.HOME_SOURCE = None, None
    hub = _big_hub()
    try:
        hub.ops._refresh_ppi()
        assert "HOME NOT SET" in hub.ops.sub.text()
    finally:
        _close(hub)
        eventbus.HOME, eventbus.HOME_SOURCE = saved


def test_s2_8_next_pass_is_real_or_says_why(home):
    import time
    from palisade_qt import eventbus
    hub = _big_hub()
    try:
        ops = hub.ops
        ops.pass_state = lambda: "no-tle"
        ops._refresh_ppi()
        assert ops.mini_pass[1].text() == "NO TLE"
        ops.pass_state = lambda: None
        ops._refresh_ppi()
        assert ops.mini_pass[1].text() == "predicting…"
        aos = time.time() + 600
        eventbus.bus.publish(eventbus.alert("OVERWATCH", "next pass: NOAA-19", severity="info",
                                            sat="NOAA-19", aos=aos))
        _pump(50)
        assert ops.mini_pass[1].text().startswith("NOAA-19 ")
        ops._next_pass["aos"] = time.time() - 3600           # that pass is long over
        ops._refresh_ppi()
        assert ops.mini_pass[1].text() == "predicting…"
    finally:
        _close(hub)


def test_s2_8_background_feeds_start_pass_prediction(home):
    hub = _big_hub()
    try:
        hub.start_background_feeds()
        _pump(400)
        from palisade_qt.overwatch import OverwatchApp
        ow = [c for c in hub.pages["ATLAS"].children_apps() if isinstance(c, OverwatchApp)]
        assert ow and ow[0]._started
        assert hub._pass_state() == getattr(ow[0], "pass_state", None)
    finally:
        _close(hub)


# ---------------------------------------------------------------- 9 legend
def test_s2_9_ops_legend_is_one_tight_row_across_the_bottom():
    from palisade_qt.kit import tracksym
    from palisade_qt.kit.mappanel import LegendRow
    hub = _big_hub(demo=True)
    try:
        ppi = hub.ops.ppi
        _pump(100)
        leg = ppi.legend
        assert isinstance(leg, LegendRow) and len(leg.items) == len(tracksym.LEGEND)
        ys = {it.y() for it in leg.items}
        assert len(ys) == 1, "one row"
        assert leg.height() <= 30
        g = leg.geometry()
        assert g.left() >= 0 and g.right() <= ppi.width() and g.bottom() <= ppi.height()
        assert g.width() >= ppi.width() - 24, "spread across the map, not a box in the corner"
        assert ppi.height() - g.bottom() <= 12, "on the bottom edge"
        assert all(it.geometry().right() <= leg.width() for it in leg.items), "nothing cut off"
    finally:
        _close(hub)


# ---------------------------------------------------------------- 10 SKY DOME
def test_s2_10_sky_dome_explains_itself():
    hub = _big_hub(demo=True)
    try:
        hub.open_callsign("ATLAS", "SKY DOME")
        _pump(800)
        from palisade_qt.overwatch import OverwatchApp
        ow = next(c for c in hub.pages["ATLAS"].children_apps() if isinstance(c, OverwatchApp))
        assert ow.dome_help.isVisible()
        t = ow.dome_help.text()
        assert "overhead" in t and "horizon" in t and "north" in t
        key = ow.dome_key.text()
        for word in ("sun", "moon", "satellite up now", "pass track", "horizon"):
            assert word in key
        heads = [ow.obj_feed.model.headerData(i, QtCore.Qt.Horizontal)
                 for i in range(ow.obj_feed.model.columnCount())]
        assert "ELEVATION °" in heads and "BEARING °" in heads
        _pump(1500)
        assert ow.dome_next.text().startswith("Next pass: ") and "(demo)" in ow.dome_next.text()
        # the rings are labelled on the dome itself
        img = ow.dome.grab().toImage()
        assert not img.isNull()
    finally:
        _close(hub)
