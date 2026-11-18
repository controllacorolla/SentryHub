"""Stage 2 of the device-run-2 fix plan (plan/briefs/device-fix-plan.md, 2026-11-18): OPS + maps.

7 maps: with NET OFFLINE (the default) every tile fetch was refused and swallowed, so the map was
black with no word why. Now the map says why, offers a one-tap DOWNLOAD MAP (owner's pick: fetch this
view once, logged as granted, NET unchanged) and refetches when NET changes.
8 OPS: every card opens its page; an empty map says why (ATLAS feed health); NEXT PASS is real or
says why not. 9 legend: one tight row along the bottom of the scope. 10 SKY DOME explains itself.
Headless (Qt offscreen), real hub at 1280x720, no network.
"""
import os
import time
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

from PySide6 import QtCore, QtGui, QtTest, QtWidgets  # noqa: E402

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
    tpl = "https://server.arcgisonline.com/tile/{z}/{y}/{x}"     # a registered tile host
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
        # a network failure offers RETRY (the same one-shot logged grant; RA-S2 N6), and the raw
        # error is in the tooltip, not on the map
        base._on_imagery(*imagery_state({"tiles": 6, "shown": 0, "failed": 6,
                                         "error": "<urlopen error [Errno -3] x>"}))
        assert base.banner.isVisible() and base.download_btn.text() == "RETRY"
        assert "urlopen" not in base.banner.text() and "urlopen" in base.banner.toolTip()
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



# ---------------------------------------------------------------- RA-S2 follow-ups
def test_ra_s2_n1_next_pass_reads_overwatch_predictions_not_the_hourly_alert(home):
    hub = _big_hub()
    try:
        now = time.time()
        hub.ops._next_pass = None                     # the alert's pass is long gone
        hub.ops.pass_state = lambda: "live"
        hub.ops.next_pass = lambda: {"sat": "NOAA 19", "aos": now + 3600, "los": now + 4200}
        assert hub.ops._pass_text().startswith("NOAA 19 ")
        hub.ops.next_pass = lambda: {"sat": "NOAA 19", "aos": now - 60, "los": now + 400}
        assert hub.ops._pass_text() == "NOAA 19 NOW"
        hub.ops.next_pass = lambda: None
        assert hub.ops._pass_text() == "none in 24 h"
        # the shell's source: OVERWATCH's own list, earliest pass not over yet
        class OW:
            passes = [{"sat": "A", "aos": now - 3000, "los": now - 2400},
                      {"sat": "B", "aos": now + 900, "los": now + 1500},
                      {"sat": "C", "aos": now + 300, "los": now + 900}]
        hub._overwatch = lambda: OW()
        assert hub._next_pass(now)["sat"] == "C"
    finally:
        _close(hub)


def test_ra_s2_n2_imagery_strip_stays_out_of_the_map_centre_and_can_be_put_away(home):
    from palisade_qt.kit.tiles import imagery_state
    hub = _big_hub()
    try:
        for page in ("OPS", "ATLAS"):
            hub.open_callsign(page)
            _pump(200)
            base = hub.ops.ppi._base if page == "OPS" and hasattr(hub.ops.ppi, "_base") else None
            if base is None:
                from palisade_qt.kit.mappanel import BaseMap
                base = next(b for b in hub.findChildren(BaseMap) if b.plot.isVisible())
            base.can_fetch = True
            base._on_imagery(*imagery_state({"tiles": 6, "shown": 0, "blocked": 6}))
            _pump(50)
            ph = base.plot.height()
            for wdg in (base.banner, base.download_btn):
                g = wdg.geometry()
                assert base.plot.rect().contains(g), (page, g)
                assert g.bottom() < ph * 0.35 or g.top() > ph * 0.65, (page, g, ph)
                for r in base._overlay_rects():          # never over the map's own controls
                    assert not g.intersects(r), (page, g, r)
            assert base.banner.height() <= 48                   # one line (RA-S2 N3)
            QtTest.QTest.mouseClick(base.banner, QtCore.Qt.LeftButton)
            # folded to a small chip, never gone (RA-S2b N8)
            assert base.banner.isVisible() and base.banner.text() == "NO IMAGERY ▸"
            assert not base.download_btn.isVisible()
            # a new blank area with the same reason (HOME moved, zoomed): still says so
            base._on_imagery(*imagery_state({"tiles": 9, "shown": 0, "blocked": 9}))
            assert base.banner.isVisible() and "NO IMAGERY" in base.banner.text()
            QtTest.QTest.mouseClick(base.banner, QtCore.Qt.LeftButton)       # unfold
            assert "NET OFFLINE" in base.banner.text() and base.download_btn.isVisible()
    finally:
        _close(hub)


def test_ra_s2_n4_a_grant_reaches_only_the_registered_tile_hosts(offline, monkeypatch):
    import urllib.request
    from palisade_qt.kit import tiles
    tiles._netpolicy()
    calls = []
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, **kw: calls.append(req))
    with pytest.raises(offline.NetBlocked):
        offline.urlopen("https://example.com/x", purpose="anything", granted=True)
    assert not calls and offline.mode() == "OFFLINE"


def test_ra_s2_n7_sky_table_does_not_claim_everything_is_above_the_horizon():
    import inspect
    from palisade_qt import overwatch
    src = inspect.getsource(overwatch)
    assert 'micro("ABOVE THE HORIZON")' not in src
    assert "BELOW 0° = UNDER THE HORIZON" in src



# ---------------------------------------------------------------- RA-S2b follow-ups
def test_ra_s2b_n9_an_old_alert_never_overrides_the_prediction_list(home):
    hub = _big_hub()
    try:
        now = time.time()
        hub.ops._next_pass = {"sat": "NOAA-19", "aos": now + 60}
        hub.ops.next_pass = lambda: None
        hub.ops.pass_state = lambda: "no-home"
        assert hub.ops._pass_text() == "HOME NOT SET"
    finally:
        _close(hub)


def test_ra_s2b_n10_refused_grants_are_logged_https_only_and_only_tiles_use_grants(offline,
                                                                                     monkeypatch):
    import re
    import urllib.request
    from palisade_qt.kit import tiles
    tiles._netpolicy()
    calls = []
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, **kw: calls.append(req))
    for url in ("https://example.com/x", "http://server.arcgisonline.com/x"):
        with pytest.raises(offline.NetBlocked):
            offline.urlopen(url, purpose="p", granted=True)
    assert not calls
    assert sum(1 for e in offline.log() if e[2] == "blocked" and "grant refused" in e[4]) == 2
    # only the map tiles may ask for a grant
    root = os.path.dirname(HERE) if "HERE" in globals() else os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))
    users = []
    for d, _dirs, files in os.walk(root):
        if any(x in d for x in (".git", "tests", "plan", "venv")):
            continue
        for f in files:
            if f.endswith(".py"):
                src = open(os.path.join(d, f), encoding="utf-8", errors="ignore").read()
                if re.search(r"granted\s*=\s*(True|getattr)|allow_grant\(", src):
                    users.append(os.path.relpath(os.path.join(d, f), root))
    assert sorted(users) == ["netpolicy.py", os.path.join("palisade_qt", "kit", "tiles.py")], users
