"""Stage 1 of the device-run-2 fix plan (plan/briefs/device-fix-plan.md, 2026-11-18): the frame.

1 the window never grows past the screen (pages, F, side panels) and opens maximized on a
1280x720 screen · 2 rail: no numbers, keys spread down the full height, SYSTEM last · 3 tiles:
purple pages, light purple sub-pages · 4 strip: UTC clock label, labelled BAT slot fed by the
telemetry, ALERTS caption; OPS count named · 5 shared green/red run control · 6 volume slider.
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

from PySide6 import QtCore, QtWidgets  # noqa: E402

from test_cl1_screen import _pump, _hub, _isolate, THEMES  # noqa: E402

_isolate = _isolate


def _big_hub(mode="dark", demo=False):
    hub = _hub(mode=mode, demo=demo)
    hub.resize(1280, 720)
    hub.show()
    _pump(200)
    return hub


def _close(hub):
    hub.close()
    _pump(150)


# ---------------------------------------------------------------- 1 window
def test_s1_1_no_page_or_panel_toggle_grows_the_window():
    """Device: opening RECON, or leaving full-map mode, grew the window past 1280 px (a page's
    minimum width propagated through the stack) and knocked it out of maximized."""
    hub = _big_hub(demo=True)
    try:
        from palisade_qt import shell
        assert isinstance(hub.stack, shell.PageStack)
        assert hub.stack.minimumSizeHint().width() <= 400
        for cs in ("RECON", "PRISM", "PROWL", "FORGE", "SYSTEM", "ASSISTANT", "MESH", "ATLAS"):
            hub.open_callsign(cs)
            _pump(150)
            assert hub.size().toTuple() == (1280, 720), (cs, hub.size().toTuple())
            assert hub.minimumSizeHint().width() <= 1280 and hub.minimumSizeHint().height() <= 720
        atlas = hub.page_app("ATLAS")
        for _ in range(3):
            atlas.handle_key("f")
            _pump(80)
            atlas.handle_key("f")
            _pump(80)
            assert hub.size().toTuple() == (1280, 720)
        hub.open_callsign("OPS")
        hub.ops.handle_key("f")
        _pump(80)
        hub.ops.handle_key("f")
        _pump(80)
        assert hub.size().toTuple() == (1280, 720)
    finally:
        _close(hub)


def test_s1_1_opens_maximized_on_a_uconsole_sized_screen():
    from palisade_qt import shell

    class Scr:
        def __init__(self, w, h):
            self._g = QtCore.QRect(0, 0, w, h)

        def availableGeometry(self):
            return self._g
    hub = shell.PalisadeHub(demo=True)
    try:
        calls = []
        hub.showMaximized = lambda: calls.append("max")
        hub.show = lambda: calls.append("show")
        assert shell.show_fitted(hub, Scr(1280, 720)) == "maximized" and calls == ["max"]
        assert hub.maximumSize().toTuple() == (1280, 720)
        hub.setMaximumSize(16777215, 16777215)
        assert shell.show_fitted(hub, Scr(2560, 1440)) == "window"
    finally:
        hub.close()
        _pump(100)


# ---------------------------------------------------------------- 2 rail
def test_s1_2_rail_has_no_numbers_system_last_and_spreads_down_the_height():
    hub = _big_hub()
    try:
        keys = list(hub.topbar.nav_keys.values())
        assert all(not any(ch.isdigit() for ch in k.call.text()) for k in keys)
        assert [k.callsign for k in keys][-1] == "SYSTEM"
        from palisade_qt.ops import CALLSIGNS
        assert CALLSIGNS[-1][0] == "SYSTEM"
        rail = hub.nav_rail
        first, last = keys[0], keys[-1]
        top = first.mapTo(rail, QtCore.QPoint(0, 0)).y()
        bottom = last.mapTo(rail, QtCore.QPoint(0, last.height())).y()
        assert top < 20
        assert rail.height() - 60 <= bottom <= rail.height() - rail.BOTTOM + 1, \
            (bottom, rail.height())
        gaps = [keys[i + 1].y() - keys[i].y() for i in range(len(keys) - 1)]
        assert max(gaps) - min(gaps) <= 2, gaps          # evenly spaced
        # the digit hotkey follows the new order: the last key opens SYSTEM
        assert "key %d" % len(keys) in last.toolTip()
    finally:
        _close(hub)


# ---------------------------------------------------------------- 3 tiles
@pytest.mark.parametrize("mode", THEMES)
def test_s1_3_pages_are_purple_tiles_sub_pages_light_purple(mode):
    from palisade_qt import theme
    tok = theme.tokens(mode)
    q = theme.qss(mode)
    assert "QPushButton.navkey {" in q and tok["tile_bg"] in q and tok["tile_bd"] in q
    assert 'QWidget[nested="true"] QPushButton.subtab' in q and tok["sub_bg"] in q
    hub = _big_hub(mode)
    try:
        hub.open_callsign("ATLAS")
        _pump(200)
        sub = hub.nav_rail.subs.get("ATLAS")
        assert sub is not None and sub.property("nested") is True
        btns = [b for b in sub.findChildren(QtWidgets.QPushButton) if b.property("class") == "subtab"]
        assert btns and any(b.isChecked() for b in btns)
        on = next(k for k in hub.topbar.nav_keys.values() if k.callsign == "ATLAS")
        assert on.property("class") == "navkey_on"
        if mode != "sun":
            # rendered: an unselected page tile is not the rail's background (it IS a tile)
            img = hub.nav_rail.grab().toImage()
            k = next(k for k in hub.topbar.nav_keys.values() if k.callsign == "OPS")
            c = img.pixelColor(k.x() + 8, k.y() + k.height() // 2)
            bg = img.pixelColor(2, hub.nav_rail.height() - 4)
            assert c != bg
    finally:
        _close(hub)


# ---------------------------------------------------------------- 4 strip + OPS labels
def test_s1_4_clock_says_utc_battery_has_a_slot_alerts_are_named():
    from palisade_qt import eventbus
    hub = _big_hub()
    try:
        tb = hub.topbar
        assert tb.clock_cap.text() == "UTC" and "UTC" in tb.clock.toolTip()
        assert tb.alerts.cap.text() == "ALERTS"
        assert tb.battery.cap.text() == "BAT"
        eventbus.bus.publish(eventbus.make_event("decode", "OPS", {"kind": "telemetry",
                                                                   "batt": 57}))
        _pump(50)
        assert tb.battery.text() == "57%"
        eventbus.bus.publish(eventbus.make_event("decode", "OPS", {"kind": "telemetry",
                                                                   "batt": None}))
        _pump(50)
        assert tb.battery.text() == "—" and "no battery sensor" in tb.battery.toolTip()
        # no strip item runs off the 1280 px strip
        for w in tb.findChildren(QtWidgets.QWidget):
            if w.isVisible() and w.parent() is tb:
                assert w.geometry().right() <= tb.width(), w
        # power is no longer a bare footer chip on OPS
        assert "pwr" not in hub.ops._last_status
    finally:
        _close(hub)


def test_s1_4_ops_count_is_named_not_a_bare_numeral():
    hub = _big_hub(demo=True)
    try:
        ops = hub.ops
        assert ops.big_cap.text().upper() == "CONTACTS ON MAP"
        assert ops.big_cap.x() < ops.big.x(), "the caption comes first and names the number"
        assert ops.big.toolTip()
        assert ops.mini_pwr[1].text() in ("demo", "GPS fix", "typed", "NOT SET")
    finally:
        _close(hub)


# ---------------------------------------------------------------- 5 run state
def test_s1_5_run_controls_are_green_when_running_red_when_stopped():
    from palisade_qt.kit.components import set_run
    from palisade_qt import theme
    q = theme.qss("dark")
    assert 'QPushButton[run="on"]' in q and 'QPushButton[run="off"]' in q
    b = QtWidgets.QPushButton("RUN")
    set_run(b, False)
    assert b.property("run") == "off"
    set_run(b, True)
    assert b.property("run") == "on"
    hub = _big_hub()
    try:
        hub.open_callsign("PROWL", "DECODE")
        _pump(200)
        babel = next(w for w in hub.findChildren(QtWidgets.QWidget)
                     if type(w).__name__ == "BabelApp")
        assert babel.run_btn.property("run") == "off" and babel.run_btn.text() == "RUN"
        babel._toggle_run(True)
        assert babel.run_btn.property("run") == "on" and babel.run_btn.text() == "STOP"
        babel._untick_run()
        babel.run_btn.setChecked(True)
        babel._untick_run()
        assert babel.run_btn.property("run") == "off"
    finally:
        _close(hub)


# ---------------------------------------------------------------- 6 volume
def test_s1_6_volume_slider_has_real_travel():
    hub = _big_hub()
    try:
        v = hub.topbar.volume
        assert v.width() >= 120 and v.singleStep() <= 2 and v.maximum() - v.minimum() == 100
    finally:
        _close(hub)


# ---------------------------------------------------------------- 26 no bottom status bar
def test_s1_26_no_bottom_status_bar_warnings_become_a_notice_sdr_presence_in_the_strip():
    """Owner 2026-11-18: 'get rid of that status bar at the bottom of all the modules'. Its content
    is still reported: SDR presence in the strip's SDR slot, a new warning as a short notice, and
    everything on a click of the page name."""
    hub = _big_hub()
    try:
        for cs in ("OPS", "ATLAS", "PRISM", "PROWL", "RECON", "FORGE", "SYSTEM", "ASSISTANT",
                   "MESH"):
            hub.open_callsign(cs)
            _pump(100)
            rows = [w for w in hub.findChildren(QtWidgets.QFrame)
                    if w.objectName() == "page_status" and w.isVisible()]
            assert rows == [], cs
        hub.open_callsign("ATLAS")
        _pump(100)
        app = hub.page_app("ATLAS")
        hub.notice.hide()
        app.set_chip("probe", "PROBE WARNING — something to fix", state="warn")
        _pump(50)
        assert hub.notice.isVisible() and "PROBE WARNING" in hub.notice.text()
        hub.notice.hide()
        app.set_chip("probe", "PROBE WARNING — something to fix", state="warn")
        _pump(50)
        assert not hub.notice.isVisible(), "the same warning is not repeated"
        app.set_chip("calm", "all good", state="neutral")
        _pump(50)
        assert not hub.notice.isVisible(), "only warnings pop up"
        lines = hub.show_page_messages()
        assert hub.notice.isVisible() and any("all good" in ln for ln in lines)
        # the notice sits inside the page area, bottom right, never over the strip or the rail
        r = hub.notice.geometry()
        sr = QtCore.QRect(hub.stack.mapTo(hub.centralWidget(), QtCore.QPoint(0, 0)),
                          hub.stack.size())
        assert sr.contains(r), (r, sr)
        # SDR presence from OPS reaches the strip's SDR slot, once and labelled
        hub.ops.set_chip("sdr", "SDR ABSENT", state="warn")
        _pump(50)
        assert hub.topbar.slots["radio"].text() == "ABSENT"
        hub.ops.set_chip("sdr", "SDR PRESENT", state="neutral")
        _pump(50)
        assert hub.topbar.slots["radio"].text() == "FREE"
    finally:
        _close(hub)


# ---------------------------------------------------------------- RA-S1 follow-ups
def test_ra_s1_f1_live_telemetry_keeps_running_off_ops():
    """F1: the strip's BAT and SDR slots are fed by OPS's live status worker: it must not pause
    when another page is on screen."""
    from palisade_qt.ops import LiveStatusWorker, DemoFeedWorker
    assert LiveStatusWorker.PAUSE_WHEN_HIDDEN is False
    w = LiveStatusWorker()
    w.pause(False)
    hub = _big_hub()
    try:
        hub.open_callsign("PRISM")
        _pump(100)
        if isinstance(hub.ops._worker, LiveStatusWorker):
            assert not hub.ops._worker.paused
    finally:
        _close(hub)
    assert DemoFeedWorker.PAUSE_WHEN_HIDDEN is True       # demo traffic still rests while hidden


def test_ra_s1_f2_f4_a_counter_is_not_a_new_warning_but_a_returning_one_is():
    from palisade_qt.shell import PageNotice
    w = QtWidgets.QWidget()
    n = PageNotice("dark", w)
    shown = []
    for s in range(12):                     # PROWL NWR: "no audio reaching the decoder (Ns)"
        shown += n.consider("PROWL", {"audio": {"text": "no audio (%ds)" % s, "state": "warn"}})
    assert len(shown) == 1, shown
    assert n.consider("PROWL", {}) == []                        # it clears …
    assert n.consider("PROWL", {"audio": {"text": "no audio (1s)", "state": "warn"}})  # … and returns
    assert n.consider("PROWL", {"audio": {"text": "no audio", "state": "alert"}}), "escalation shows"
    w.deleteLater()


def test_ra_s1_f3_the_notice_never_follows_you_to_another_page():
    hub = _big_hub()
    try:
        hub.open_callsign("ATLAS")
        _pump(100)
        hub.page_app("ATLAS").set_chip("probe2", "ATLAS PROBLEM", state="warn")
        _pump(50)
        assert hub.notice.isVisible() and hub.notice.text().startswith("ATLAS · ")
        hub.open_callsign("SYSTEM")
        _pump(50)
        assert not hub.notice.isVisible()
    finally:
        _close(hub)


def test_ra_s1_f8_no_automatic_notice_over_an_open_drawer_and_f9_palette_path():
    hub = _big_hub()
    try:
        hub.open_callsign("ATLAS")
        _pump(100)
        hub.open_panel("alerts")
        _pump(80)
        hub.notice.hide()
        hub.page_app("ATLAS").set_chip("probe3", "ANOTHER PROBLEM", state="warn")
        _pump(50)
        assert not hub.notice.isVisible()
        hub.open_panel("alerts")                      # close it again
        _pump(80)
        names = [c[0] for c in hub._commands()]
        cmd = next(c for c in hub._commands() if c[0].startswith("Page messages"))
        assert cmd and any("Page messages" in n for n in names)
        cmd[1]()
        _pump(50)
        assert hub.notice.isVisible() and "ANOTHER PROBLEM" in hub.notice.text()
    finally:
        _close(hub)


def test_ra_s1_f5_f7_focus_on_open_sub_tile_and_disabled_volume_rules():
    from palisade_qt import theme
    for mode in ("dark", "light", "sun"):
        q = theme.qss(mode)
        tok = theme.tokens(mode)
        assert ('QPushButton.subtab:checked:focus {{ border: {} solid {}; }}'.format(
            tok["focus_w"], tok["focus_on"])).replace("{{", "{").replace("}}", "}") in q
        assert "QSlider#vol::handle:horizontal:disabled" in q
    hub = _big_hub()
    try:
        v = hub.topbar.volume
        v.setEnabled(True)
        _pump(30)
        on = v.grab().toImage()
        v.setEnabled(False)
        _pump(30)
        off = v.grab().toImage()
        diff = sum(1 for x in range(0, on.width(), 2) for y in range(0, on.height(), 2)
                   if on.pixelColor(x, y) != off.pixelColor(x, y))
        assert diff > 20, "a disabled volume slider must look different"
    finally:
        _close(hub)


# ---------------------------------------------------------------- RA-S1b follow-ups
def test_ra_s1b_n1_a_different_warning_on_the_same_key_shows():
    from palisade_qt.shell import PageNotice
    w = QtWidgets.QWidget()
    n = PageNotice("dark", w)
    assert n.consider("RECON", {"sdr": {"text": "WIFI STANDBY", "state": "warn"}})
    assert n.consider("RECON", {"sdr": {"text": "WIFI STANDBY", "state": "warn"}}) == []
    assert n.consider("RECON", {"sdr": {"text": "BLE STANDBY", "state": "warn"}}) == ["BLE STANDBY"]
    # the same message dropping from alert to warn is not news
    assert n.consider("RECON", {"sdr": {"text": "BLE STANDBY", "state": "alert"}})
    assert n.consider("RECON", {"sdr": {"text": "BLE STANDBY", "state": "warn"}}) == []
    w.deleteLater()


def test_ra_s1b_n2_a_warning_held_back_by_a_panel_shows_once_it_closes():
    hub = _big_hub()
    try:
        hub.open_callsign("ATLAS")
        _pump(100)
        hub.open_panel("alerts")
        _pump(80)
        hub.notice.hide()
        hub.page_app("ATLAS").set_chip("probe4", "HELD BACK", state="warn")
        _pump(50)
        assert not hub.notice.isVisible()
        hub.open_panel("alerts")                      # close it
        _pump(1200)                                   # the retry runs (700 ms)
        assert hub.notice.isVisible() and "HELD BACK" in hub.notice.text()
    finally:
        _close(hub)


def test_ra_s1b_n3_a_still_active_warning_shows_again_on_return():
    hub = _big_hub()
    try:
        hub.open_callsign("ATLAS")
        _pump(100)
        hub.page_app("ATLAS").set_chip("probe5", "STILL BROKEN", state="warn")
        _pump(50)
        assert "STILL BROKEN" in hub.notice.text()
        hub.open_callsign("SYSTEM")
        _pump(50)
        assert not hub.notice.isVisible()
        hub.open_callsign("ATLAS")                    # a quick flip back: no repeat (RA-S1c N10)
        _pump(80)
        assert "STILL BROKEN" not in hub.notice.text() or not hub.notice.isVisible()
        hub.notice.REMIND_S = 0                       # away long enough: reminded once on return
        hub.open_callsign("SYSTEM")
        _pump(50)
        hub.open_callsign("ATLAS")
        _pump(80)
        assert hub.notice.isVisible() and "STILL BROKEN" in hub.notice.text()
    finally:
        _close(hub)


def test_ra_s1b_n4_open_nav_key_focus_is_a_full_ring():
    from palisade_qt import theme
    for mode in ("dark", "light", "sun"):
        tok = theme.tokens(mode)
        assert "QPushButton.navkey_on:focus { border: %s solid %s; }" % (
            tok["focus_w"], tok["focus_on"]) in theme.qss(mode)


# ---------------------------------------------------------------- RA-S1c follow-ups
def test_ra_s1c_n6_atlas_layer_counts_moving_do_not_re_pop_the_adsb_warning():
    from types import SimpleNamespace
    from palisade_qt.atlas import AtlasApp, KINDS
    from palisade_qt.shell import PageNotice
    stub = SimpleNamespace(_layers={k for k, _l, _t in KINDS}, demo=False,
                           _adsb_health={"state": "none"})
    kinds = [k for k, _l, _t in KINDS if k not in ("aircraft", "operator")]
    w = QtWidgets.QWidget()
    n = PageNotice("dark", w)
    shown = []
    for i in range(7):                      # a layer flickers between 0 and 1 contact
        pts = [{"kind": kinds[0]}] if i % 2 else []
        text, st = AtlasApp._layer_summary(stub, pts)
        assert st == "warn" and "ADS-B NO FEED" in text
        shown += n.consider("ATLAS", {"sdr": {"text": text, "state": st}})
    assert len(shown) == 1, shown
    w.deleteLater()


def test_ra_s1c_n8_notice_timers_stop_with_the_window():
    hub = _big_hub()
    hub.open_callsign("ATLAS")
    _pump(100)
    hub.notice._retry.start()
    n = hub.notice
    hub.close()
    assert not n._retry.isActive() and not n._timer.isActive() and n.refresh is None
    _pump(150)


def test_ra_s1c_a_second_warning_joins_the_notice_showing():
    from palisade_qt.shell import PageNotice
    w = QtWidgets.QWidget()
    w.resize(800, 600)
    w.show()
    n = PageNotice("dark", w)
    n.consider("ATLAS", {"a": {"text": "FIRST", "state": "warn"}})
    n.consider("ATLAS", {"a": {"text": "FIRST", "state": "warn"},
                         "b": {"text": "SECOND", "state": "warn"}})
    assert "FIRST" in n.text() and "SECOND" in n.text()
    w.close()
    w.deleteLater()


# ---------------------------------------------------------------- RA-S1d follow-ups
def _shown_notice():
    from palisade_qt.shell import PageNotice
    w = QtWidgets.QWidget()
    w.resize(800, 600)
    w.show()
    return w, PageNotice("dark", w)


def test_ra_s1d_n12_the_notice_only_says_what_the_page_reports_now():
    w, n = _shown_notice()
    # a replaced warning on the same key (RECON WIFI -> BLE) does not keep the old line
    n.consider("RECON", {"sdr": {"text": "WIFI STANDBY — offline", "state": "warn"}})
    n.consider("RECON", {"sdr": {"text": "BLE STANDBY — offline", "state": "warn"}})
    assert "BLE STANDBY" in n.text() and "WIFI" not in n.text()
    # a cleared warning goes when a second one joins
    n.consider("ATLAS", {"a": {"text": "FIRST PROBLEM", "state": "warn"}})
    n.consider("ATLAS", {"b": {"text": "SECOND PROBLEM", "state": "warn"}})
    assert "SECOND" in n.text() and "FIRST" not in n.text()
    # … and goes on its own; the notice hides once nothing it showed is still reported
    n.consider("ATLAS", {"a": {"text": "FIRST PROBLEM", "state": "warn"},
                         "b": {"text": "SECOND PROBLEM", "state": "warn"}})
    assert "FIRST" in n.text() and "SECOND" in n.text()
    n.consider("ATLAS", {"b": {"text": "SECOND PROBLEM", "state": "warn"}})
    assert "FIRST" not in n.text() and n.isVisible()
    n.consider("ATLAS", {})
    assert not n.isVisible()
    # ADS-B NO FEED -> STALE on the same key: one line, the current one
    n.consider("ATLAS", {"sdr": {"text": "ADS-B NO FEED", "state": "warn"}})
    n.consider("ATLAS", {"sdr": {"text": "ADS-B STALE 12s", "state": "alert"}})
    assert n.text().count("\n") == 0 and "STALE" in n.text()
    w.close()
    w.deleteLater()


def test_ra_s1d_n13_the_notice_never_grows_past_one_line_per_status_key():
    w, n = _shown_notice()
    for i in range(60):
        n.consider("RECON", {"sdr": {"text": ("WIFI" if i % 2 else "BLE") + " STANDBY",
                                     "state": "warn"}})
    assert n.text().count("\n") == 0
    w.close()
    w.deleteLater()


def test_ra_s1e_n16_an_update_never_raises_the_notice_over_an_open_drawer():
    w, n = _shown_notice()
    held = {"on": False}
    n.blocked = lambda: held["on"]
    n.consider("ATLAS", {"sdr": {"text": "ADS-B STALE 1s", "state": "alert"}})
    assert n.isVisible()
    held["on"] = True                       # a drawer opens over it
    n.consider("ATLAS", {"sdr": {"text": "ADS-B STALE 2s", "state": "alert"}})
    assert not n.isVisible()
    w.close()
    w.deleteLater()
