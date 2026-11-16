"""CL1-fix — regression tests for what the RA-CL1 re-audit reopened (plan/briefs/CL1-fix.md items 1-18).

Every test here was run against the branch before the fix (fd4d320) and failed there; the report
(plan/briefs/CL1-report.md, "CL1-fix") lists each test with its pre-fix failure. Headless via Qt's
offscreen platform; no radio, no network, no real mixer — process tests spawn only `sleep`.
"""
import os
import signal
import subprocess
import sys
import time

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
from PySide6.QtTest import QTest  # noqa: E402

from test_cl1_screen import (  # noqa: E402
    _app, _pump, _hub, _key, _isolate, _fake_sysfs, _FakeMixer, _wait_mixer, THEMES, SCREEN_W)

_isolate = _isolate          # the autouse isolation fixture applies to this module too


def _alive(pid):
    from palisade_qt import procs
    return procs.alive(pid)


def _wait(cond, timeout=5.0):
    end = time.time() + timeout
    while not cond() and time.time() < end:
        _pump(20)
    return cond()


def _members(pgid):
    out = subprocess.run(["pgrep", "-g", str(pgid)], capture_output=True, text=True).stdout
    return [int(x) for x in out.split()]


def _cleanup(proc):
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except OSError:
        pass
    try:
        proc.kill()
    except OSError:
        pass
    proc.wait(timeout=5)


# ================================================================ 1. PANIC stops the whole pipeline
@pytest.mark.parametrize("new_session", [True, False])
def test_panic_stops_every_pipeline_member_and_counts_only_verified(new_session):
    """RA-CL1: PANIC signalled only the `sh -c` wrapper, left `a | b` running, and counted signals
    sent as processes killed. Both members must be gone, and the count must be verified."""
    import txguard
    proc = subprocess.Popen(["sh", "-c", "sleep 300 | sleep 301"], start_new_session=new_session)
    try:
        assert _wait(lambda: len(_tree(proc.pid)) >= 2), "pipeline did not start"
        members = _tree(proc.pid)
        hub = _hub(demo=False)
        try:
            hub._list_children = lambda: [proc.pid]
            txguard.arm(True)
            hub.panic()
            assert not txguard.is_armed()
            for pid in members + [proc.pid]:
                assert not _alive(pid), "pid %d survived PANIC" % pid
            text = hub.panic_banner.text()
            n = len(set(members + [proc.pid]))
            assert "%d of %d child process(es) stopped (verified gone)" % (n, n) in text, text
            assert "SURVIVED" not in text
        finally:
            hub.close()
            _pump(100)
    finally:
        _cleanup(proc)


def _tree(pid):
    from palisade_qt import procs
    try:
        pg = os.getpgid(pid)
    except OSError:
        return []
    group = _members(pg) if pg == pid else []
    return sorted(set(procs.descendants(pid) + [p for p in group if p != pid]))


def test_panic_never_counts_a_signal_as_a_kill(monkeypatch):
    """A process that does not die is reported as a survivor, by pid — never as killed."""
    from palisade_qt import procs
    proc = subprocess.Popen(["sleep", "300"], start_new_session=True)
    try:
        monkeypatch.setattr(procs, "alive", lambda pid, run=None: True)     # nothing ever dies
        res = procs.stop_tree([proc.pid], term_wait=0.1, kill_wait=0.1)
        assert res["stopped"] == [] and res["survivors"] == [proc.pid]
        text = procs.describe(res)
        assert text.startswith("0 of 1") and "SURVIVED: pid %d" % proc.pid in text
    finally:
        _cleanup(proc)


def test_decoder_pipelines_start_in_their_own_session():
    """PANIC can only stop a whole pipeline by group if every stage leads one.

    Updated for CL5 (A4): decoders no longer call subprocess.Popen themselves; they go through
    kit.procs.Pipeline, where every stage leads its own session/group."""
    import inspect
    from palisade_qt import atlas, prism, prowl, babel
    from palisade_qt.kit.procs import Pipeline
    for fn in (atlas._open_aprs_pipe, atlas._open_ais_pipe):
        assert "Pipeline(" in inspect.getsource(fn), fn.__name__
    for mod in (atlas, prism, prowl, babel):
        assert "subprocess.Popen(" not in inspect.getsource(mod), mod.__name__
    pipe = Pipeline([["sleep", "30"], ["cat"]])
    try:
        for p in pipe.procs:
            assert os.getpgid(p.pid) == p.pid and os.getsid(p.pid) == p.pid
        assert pipe.terminate(grace=1.0, kill_after=1.0)
    finally:
        pipe.terminate(grace=0.1, kill_after=0.5)


def test_panic_never_signals_its_own_process_group():
    from palisade_qt import procs
    me = os.getpid()
    res = procs.stop_tree([], run=lambda argv: "")
    assert res == {"targets": [], "stopped": [], "survivors": []}
    assert me not in procs.stop_tree([me], term_wait=0, kill_wait=0,
                                      run=lambda argv: "")["targets"]


# ================================================================ 2. PANIC and BENCH's TX permit
# test_panic_leaves_tx_slot_on_the_real_bench_gate_and_says_ack_not_revoked was retired by the
# owner decision of 2026-11-15 (CL1-fix2): PANIC now revokes the BENCH ack (it is page state). Its
# replacement is tests/test_cl1_fix2.py::test_panic_unchecks_the_bench_ack_and_the_slot_reads_the_gate


# ================================================================ 3. mute / volume
class _BadMixer(_FakeMixer):
    """Accepts nothing: every set fails and the state does not change."""

    def run(self, argv, timeout=2.0):
        self.calls.append(list(argv))
        if argv[1].startswith("set-"):
            return 1, ""
        return _FakeMixer.run(self, argv, timeout)


class _DeadMixer(_FakeMixer):
    """The binary exists but cannot be read at all."""

    def run(self, argv, timeout=2.0):
        self.calls.append(list(argv))
        return 1, ""


class _SlowMixer(_FakeMixer):
    def run(self, argv, timeout=2.0):
        if argv[1].startswith("set-"):
            time.sleep(2.0)
        return _FakeMixer.run(self, argv, timeout)


def _bar(mixer):
    from palisade_qt.kit import TopBar
    from palisade_qt.kit.audio import AudioSink
    _app()
    return TopBar(audio=AudioSink(which=mixer.which, run=mixer.run))


def test_mute_shows_muted_only_after_the_read_back_says_so():
    mixer = _FakeMixer(volume=30)
    tb = _bar(mixer)
    try:
        _wait_mixer(tb)
        assert not tb.mute.isChecked()
        tb.mute.click()
        assert not tb.mute.isChecked(), "MUTED before the mixer confirmed it"
        _wait_mixer(tb)
        assert tb.mute.isChecked() and mixer.muted
        assert tb.audio_state() == (30, True, "")
        assert mixer.calls[-1][:2] == ["pactl", "get-sink-mute"], "every set is read back"
    finally:
        tb.stop()


def test_failed_mixer_command_shows_a_fault_and_the_true_state():
    mixer = _BadMixer(volume=30)
    tb = _bar(mixer)
    try:
        _wait_mixer(tb)
        tb.mute.click()
        _wait_mixer(tb)
        assert not tb.mute.isChecked(), "the mixer refused: the sink is still live"
        vol, muted, fault = tb.audio_state()
        assert muted is False and fault and "refused" in fault
        assert tb.mute.text() == "♪!" and "MIXER FAULT" in tb.mute.toolTip()
    finally:
        tb.stop()


def test_unreadable_mixer_shows_unknown_never_zero_and_unmuted():
    tb = _bar(_DeadMixer())
    try:
        _wait_mixer(tb)
        vol, muted, fault = tb.audio_state()
        assert vol is None and muted is None and fault
        assert not tb.volume.isEnabled(), "a 0% slider would be a reading nobody took"
        assert not tb.mute.isChecked() and tb.mute.text() == "♪!"
        assert "UNKNOWN" in tb.volume.toolTip()
    finally:
        tb.stop()


def test_a_hanging_mixer_does_not_freeze_the_ui():
    mixer = _SlowMixer()
    tb = _bar(mixer)
    try:
        _wait_mixer(tb)
        ticks = []
        timer = QtCore.QTimer()
        timer.timeout.connect(lambda: ticks.append(time.time()))
        timer.start(50)
        t0 = time.time()
        tb.mute.click()
        assert time.time() - t0 < 0.3, "the click itself blocked on the mixer"
        _pump(1000)
        timer.stop()
        assert len(ticks) >= 12, "the GUI thread stalled while the mixer hung (%d ticks)" % len(ticks)
        assert tb.mixer.pending == 1 and not tb.mute.isChecked()
        _wait_mixer(tb)
        assert tb.mute.isChecked()
    finally:
        tb.stop()


# ================================================================ 4. alerts drawer acks by id
def test_alert_arriving_while_drawer_open_does_not_get_acked_in_place_of_the_selected_one():
    from palisade_qt import eventbus
    hub = _hub(demo=False)
    try:
        for i in range(3):
            eventbus.bus.publish(eventbus.alert("TEST", "alert %d" % i, severity="warn"))
        _pump(40)
        hub.open_panel("alerts")
        _pump(40)
        d = hub.alerts_drawer
        d.table.view.selectRow(1)                  # the operator selects "alert 1"
        chosen = d.selected_id()
        assert hub.alerts.get(chosen)["text"] == "alert 1"
        eventbus.bus.publish(eventbus.alert("TEST", "NEW unseen", severity="alert"))
        _pump(40)
        assert d.selected_id() == chosen, "the cursor moved to another alert"
        _key(hub, QtCore.Qt.Key_Return)
        assert hub.alerts.get(chosen)["acked"]
        newest = hub.alerts.items[0]
        assert newest["text"] == "NEW unseen" and not newest["acked"]
    finally:
        hub.close()
        _pump(150)


# ================================================================ 5. slots paint the varying part
def test_slots_paint_the_whole_owner_and_scope_never_an_ellipsis():
    from palisade_qt import chrome, radio_arbiter
    hub = _hub(demo=True)
    try:
        painted = set()
        for owner in sorted(set(radio_arbiter.OWNER_LABELS.values())):
            hub.topbar.set_state("DEMO", ("HELD", owner), "OFF", ("NONE", "", ""))
            _pump(20)
            slot = hub.topbar.slots["radio"]
            assert slot.painted_text() == owner, (owner, slot.painted_text())
            painted.add(slot.painted_text())
        assert len(painted) == len(set(radio_arbiter.OWNER_LABELS.values())), \
            "two owners look identical in the strip"
        for scope in (["10.0.0.*"], ["Net-*", "AA:BB:CC:*"], ["192.168.100.0/24"]):
            word = chrome.scope_summary(scope)
            hub.topbar.set_state("DEMO", ("FREE", ""), "OFF", ("ACTIVE", word, "Op"))
            _pump(20)
            slot = hub.topbar.slots["engagement"]
            assert slot.painted_text() == word and "…" not in slot.painted_text()
        assert chrome.scope_summary(["10.0.0.*"]) == "10.0.0.*"
        assert chrome.scope_summary(["a", "b", "c"]) == "3 targets"
        assert hub.topbar.minimumSizeHint().width() <= SCREEN_W - 12
    finally:
        hub.close()
        _pump(150)


# ================================================================ 6. readers fail to UNKNOWN
def test_unreadable_engines_show_unknown_not_the_all_clear(monkeypatch):
    import engagement
    import txguard
    from palisade_qt import chrome, theme

    def boom(*_a, **_k):
        raise RuntimeError("engine unreadable")
    hub = _hub(demo=False)
    try:
        monkeypatch.setattr(txguard, "is_armed", boom)
        monkeypatch.setattr(engagement, "info", boom)
        assert chrome.read_tx() == "UNKNOWN"
        assert chrome.read_engagement()[0] == "UNKNOWN"
        hub.state.poll()
        _pump(20)
        warn = theme.tokens("dark")["warn"]
        for key in ("tx", "engagement"):
            s = hub.topbar.slots[key]
            assert s.text() == "UNKNOWN" and s.glyph.shape() == "unknown"
            assert warn.lower() in s.value.styleSheet().lower()
    finally:
        hub.close()
        _pump(150)


# ================================================================ 7. PANIC through popups
def test_panic_works_with_a_combo_dropdown_open():
    import txguard
    hub = _hub(demo=True)
    try:
        hub._list_children = lambda: []
        hub.open_callsign("BENCH")
        _pump(80)
        combo = hub.pages["BENCH"].band
        combo.showPopup()
        _pump(80)
        popup = QtWidgets.QApplication.activePopupWidget()
        assert popup is not None and popup.window() is not hub
        txguard.arm(True)
        QTest.keyClick(popup, QtCore.Qt.Key_Escape, QtCore.Qt.ShiftModifier)
        _pump(60)
        assert not txguard.is_armed(), "PANIC was swallowed by the dropdown"
        assert QtWidgets.QApplication.activePopupWidget() is None
    finally:
        hub.close()
        _pump(150)


def test_panic_works_with_a_context_menu_open_and_with_modifiers_held():
    import txguard
    hub = _hub(demo=True)
    try:
        hub._list_children = lambda: []
        menu = QtWidgets.QMenu(hub)
        menu.addAction("Copy")
        menu.popup(hub.mapToGlobal(QtCore.QPoint(200, 200)))
        _pump(80)
        assert QtWidgets.QApplication.activePopupWidget() is menu
        txguard.arm(True)
        QTest.keyClick(menu, QtCore.Qt.Key_F12)
        _pump(60)
        assert not txguard.is_armed(), "PANIC was swallowed by the context menu"
        txguard.arm(True)
        QTest.keyClick(hub, QtCore.Qt.Key_F12, QtCore.Qt.ControlModifier)
        _pump(40)
        assert not txguard.is_armed(), "Ctrl held must not disable PANIC"
    finally:
        hub.close()
        _pump(150)


# ================================================================ 8. ENGAGEMENT panel
def _clipped_labels(root):
    out = []
    for lbl in root.findChildren(QtWidgets.QLabel):
        if not lbl.isVisible() or not lbl.text():
            continue
        if lbl.wordWrap():
            need = lbl.heightForWidth(lbl.width())
            if need > lbl.height() + 1:
                out.append((lbl.text()[:30], lbl.height(), need))
        elif lbl.fontMetrics().horizontalAdvance(lbl.text()) > lbl.width() + 1:
            out.append((lbl.text()[:30], lbl.width()))
    return out


def test_engagement_panel_shows_whole_scope_three_evidence_rows_and_banner_parity():
    import engagement
    from palisade_qt import theme
    # CL2/G4: typed scope only (an OUI is the one wildcard); operator from the profile (KD0ABC)
    scope = ["192.168.100.0/24", "10.0.0.0/24", "AA:BB:CC:*", "Net-Core", "172.16.0.0/12",
             "Corp-Guest"]
    hub = _hub(demo=False)
    try:
        ok, why = engagement.start("Operation LONG NAME 2026", "ROE-17/B", scope)
        assert ok, why
        hub.open_panel("engagement")
        _pump(150)
        p = hub.engage_panel
        assert not _clipped_labels(p.eng_detail), _clipped_labels(p.eng_detail)
        text = " ".join(lbl.text() for lbl in p.eng_detail.findChildren(QtWidgets.QLabel))
        for want in scope + ["Operation LONG NAME 2026", "KD0ABC", "ROE-17/B"]:
            assert want in text, want
        rows = dict((k, v) for k, v in _card_rows(p.eng_detail))
        assert rows.get("TARGETS") == "6"
        view = p.eng_actions.view
        assert view.viewport().height() >= 3 * theme.ROW_H, view.viewport().height()
        assert p.geometry().bottom() <= hub.centralWidget().height()
    finally:
        hub.close()
        _pump(150)


def _card_rows(card):
    lay = card._rows
    for i in range(lay.rowCount()):
        k = lay.itemAt(i, QtWidgets.QFormLayout.LabelRole)
        v = lay.itemAt(i, QtWidgets.QFormLayout.FieldRole)
        if k and v:
            yield k.widget().text().upper(), v.widget().text()


# ================================================================ 9. alert cap
def test_alert_cap_never_drops_an_unacknowledged_alert():
    from palisade_qt import eventbus, panels
    _app()
    store = panels.AlertStore(cap=5)
    try:
        for i in range(8):
            eventbus.bus.publish(eventbus.alert("T", "a%d" % i, severity="warn"))
        assert len(store.items) == 8 and store.unacked() == 8, "unacknowledged alerts were dropped"
        oldest = [a["id"] for a in store.items[-3:]]
        for i in oldest:
            store.ack(i)
        assert len(store.items) == 5 and store.unacked() == 5
        assert all(not a["acked"] for a in store.items)
    finally:
        store.stop()


# ================================================================ 10. sky labels, focus, demo green, feed
def test_sky_dome_labels_are_font_sized_and_stay_inside_the_dome():
    _app()
    from palisade_qt import theme
    from palisade_qt.overwatch import SkyDome
    dome = SkyDome(theme.tokens("dark"))
    dome.resize(300, 220)
    f = dome.font()
    f.setPixelSize(theme.FONT_BODY)
    fm = QtGui.QFontMetrics(f)
    for x, y in ((150, 110), (295, 110), (150, 2), (150, 218), (2, 110)):
        r = dome.label_rect(x, y, "ISS (ZARYA)", fm)
        assert r.height() >= fm.height(), "label box shorter than the text"
        assert r.width() >= fm.horizontalAdvance("ISS (ZARYA)")
        assert r.left() >= 0 and r.right() <= dome.width() and r.top() >= 0 \
            and r.bottom() <= dome.height(), (x, y, r)


def _focus_changes_pixels(widget, other):
    widget.setFocus()
    _pump(40)
    a = widget.grab().toImage()
    other.setFocus()
    _pump(40)
    b = widget.grab().toImage()
    return a != b


def test_focus_ring_is_visible_on_the_active_nav_key_and_the_map_style_combo():
    from palisade_qt.kit import mappanel
    hub = _hub(demo=True)
    try:
        hub.open_callsign("ATLAS")
        _pump(150)
        key = hub.topbar.nav_keys["ATLAS"]
        assert key.property("class") == "navkey_on"
        assert _focus_changes_pixels(key, hub.topbar.nav_keys["OPS"]), \
            "the active page's nav key shows no focus"
        combo = hub.page_app("ATLAS").findChild(mappanel.MapPanel)._combo
        assert _focus_changes_pixels(combo, key), "the map style combo shows no focus"
    finally:
        hub.close()
        _pump(150)


def test_prowl_demo_data_is_never_painted_green():
    from palisade_qt import theme
    from palisade_qt.prowl import ProwlApp
    _app()
    p = ProwlApp(demo=True, mode="dark")
    try:
        live = theme.tokens("dark")["live"]
        rows = [{"freq": 162.55, "label": "WX1", "sig": "-40", "last": "", "_hot": True}]
        p._on_scan_row({"rows": rows, "active": None})
        colors = p.feed.model.rows[0]["_colors"]
        assert live not in colors.values(), colors
        p.on_status({"sdr": {"text": "SCAN DEMO", "state": "neutral"}})
        from palisade_qt import prowl
        import inspect
        src = inspect.getsource(prowl)
        for word in ("SCAN DEMO", "FM DEMO", "NWR DEMO"):
            line = [ln for ln in src.splitlines() if '"%s"' % word in ln][0]
            assert '"ok": True' not in line, "demo status is shown green: " + line.strip()
    finally:
        p.stop()


def test_feed_columns_get_real_widths_even_when_filled_while_hidden():
    _app()
    from palisade_qt.kit import FeedTable
    t = FeedTable([("t", "TIME"), ("id", "ID"), ("event", "EVENT"), ("text", "TEXT")])
    t.resize(900, 300)
    for i in range(5):                              # rows arrive while the table is hidden
        t.model.prepend({"t": "03:30:12", "id": "345301%03d" % i,
                         "event": "Severe Thunderstorm Warning", "text": "x"})
    t.show()
    _pump(60)
    hdr, fm = t.view.horizontalHeader(), t.view.fontMetrics()
    for i, (key, _h) in enumerate(t.model.columns[:-1]):
        need = max(fm.horizontalAdvance(str(r[key])) for r in t.model.rows)
        assert hdr.sectionSize(i) >= need + 12, (key, hdr.sectionSize(i), need)


# ================================================================ 11. D1 pins
def test_no_rail_the_page_starts_at_the_window_edge():
    from palisade_qt import panels
    for demo in (False, True):
        hub = _hub(demo=demo)
        try:
            b = panels.DemoBorder.WIDTH if demo else 0
            g = hub.stack.geometry()
            assert g.x() == b and g.width() == hub.centralWidget().width() - 2 * b, \
                "something sits beside the page (a rail?) at %r" % (g,)
        finally:
            hub.close()
            _pump(100)


def test_detail_values_wrap_instead_of_widening():
    _app()
    from palisade_qt.kit import DetailCard
    c = DetailCard("X")
    c.set_rows([("REASON", "word " * 80)])
    c.set_hero("y" * 120)
    val = [w for w in c.findChildren(QtWidgets.QLabel) if w.text().startswith("word")][0]
    assert val.wordWrap() and c.hero.wordWrap()
    assert c.minimumSizeHint().width() < 400, c.minimumSizeHint()


# ================================================================ 12. D2 measured on real widgets
def test_rendered_text_is_16px_or_more_everywhere_including_captions_headers_and_plots():
    """D2 on the rendered widgets: QFontInfo of every visible label, button, input and table header
    on every page — no class exempt — plus pyqtgraph axis and PPI label fonts."""
    import pyqtgraph as pg
    hub = _hub(demo=True)
    try:
        small = []
        from test_cl1_screen import _every_view
        for name, tab in _every_view(hub):
            for w in hub.findChildren(QtWidgets.QWidget):
                if not w.isVisible():
                    continue
                if isinstance(w, QtWidgets.QLabel) and (not w.text().strip() or
                                                        (w.pixmap() and not w.pixmap().isNull())):
                    continue
                if isinstance(w, (QtWidgets.QLabel, QtWidgets.QAbstractButton, QtWidgets.QLineEdit,
                                  QtWidgets.QComboBox, QtWidgets.QHeaderView)):
                    w.ensurePolished()
                    px = QtGui.QFontInfo(w.font()).pixelSize()
                    if px < 16:
                        small.append("%s/%s %s %r %s %dpx" % (
                            name, tab, type(w).__name__, getattr(w, "text", lambda: "")()[:24],
                            w.property("class"), px))
            for plot in hub.findChildren(pg.PlotWidget):
                if not plot.isVisible():
                    continue
                for ax in ("left", "bottom"):
                    axis = plot.getPlotItem().getAxis(ax)
                    if axis.isVisible() and axis.style.get("tickFont") is not None:
                        if axis.style["tickFont"].pixelSize() < 16:
                            small.append("%s/%s axis %s" % (name, tab, ax))
        assert not small, "\n".join(sorted(set(small))[:30])
    finally:
        hub.close()
        _pump(150)


# ================================================================ 13. D3
def test_ops_scope_has_at_most_24px_dead_space_each_side():
    from palisade_qt.kit.ppi import PpiScope
    for demo in (True, False):
        hub = _hub(demo=demo)
        try:
            hub.open_callsign("OPS")
            _pump(200)
            s = hub.pages["OPS"].findChild(PpiScope)
            (x0, x1), _ = s.plot.getViewBox().viewRange()
            w = s.plot.getViewBox().width()
            dead = (w - w * (2 * s._span) / (x1 - x0)) / 2
            assert dead <= 24, "%.0f px of empty well each side (demo=%s)" % (dead, demo)
        finally:
            hub.close()
            _pump(150)


def test_sub_tabs_are_a_vertical_rail_left_of_the_page():
    from palisade_qt.kit.subtabs import SubTabRail
    hub = _hub(demo=True)
    try:
        for name in ("ATLAS", "PROWL", "RECON", "FORGE", "SYSTEM"):
            hub.open_callsign(name)
            _pump(80)
            page = hub.pages[name]
            rail = page._rail
            assert isinstance(rail, SubTabRail), name
            btns = list(rail.buttons.values())
            xs = {b.geometry().x() for b in btns}
            ys = [b.geometry().y() for b in btns]
            assert len(xs) == 1 and ys == sorted(ys) and len(set(ys)) == len(ys), \
                "%s sub-tabs are not stacked vertically" % name
            body_x = min(c.geometry().x() for c in page.children()
                         if isinstance(c, QtWidgets.QWidget) and c is not rail and c.isVisible()
                         and c.objectName() != "page_status")
            assert rail.geometry().x() <= body_x, "%s rail is not at the left edge" % name
    finally:
        hub.close()
        _pump(150)


# ================================================================ 14. D9
@pytest.mark.parametrize("mode", THEMES)
def test_armed_and_active_slots_are_never_green(mode):
    import colorsys
    from palisade_qt import theme
    from palisade_qt.kit import TopBar
    _app()
    t = theme.tokens(mode)
    tb = TopBar(mode=mode)
    try:
        tb.set_state("LIVE", ("FREE", ""), "ARMED", ("ACTIVE", "10.0.0.*", "Op"))
        for key, want in (("tx", t["alert"]), ("engagement", t["warn"])):
            css = tb.slots[key].value.styleSheet().lower()
            assert want.lower() in css, (key, css)
            if mode != "sun":
                assert t["live"].lower() not in css
            c = QtGui.QColor(want)
            h, _l, s = colorsys.rgb_to_hls(c.redF(), c.greenF(), c.blueF())
            assert not (s > 0.2 and 80 / 360 <= h <= 170 / 360), "%s slot is green in %s" % (key,
                                                                                            mode)
    finally:
        tb.stop()


@pytest.mark.parametrize("mode,minimum", [("light", 4.5), ("sun", 7.0), ("dark", 4.5)])
def test_babel_protocol_colours_are_readable(mode, minimum):
    from palisade_qt import theme
    from palisade_qt.babel import BabelApp
    _app()
    app = BabelApp(demo=True, mode=mode)
    try:
        tok = theme.tokens(mode)
        for proto, col in app.proto_colors().items():
            for bg in ("well", "bg", "p1", "p2"):
                assert theme.contrast(col, tok[bg]) >= minimum, (mode, proto, col, bg)
    finally:
        app.stop()


# ================================================================ 15. D10
def test_empty_detail_cards_collapse_in_live_pages():
    from palisade_qt.kit import DetailCard
    hub = _hub(demo=False)
    try:
        from test_cl1_screen import _every_view
        tall, clipped = [], []
        for name, tab in _every_view(hub):
            for c in hub.findChildren(DetailCard):
                if c.isVisible() and c.is_empty():
                    if c.drawn_height() > 110:
                        tall.append("%s/%s %dx%d" % (name, tab, c.width(), c.drawn_height()))
                    need = c.box.sizeHint().height()
                    if c.drawn_height() < need:
                        clipped.append("%s/%s %d < %d" % (name, tab, c.drawn_height(), need))
        assert not tall, "empty cards still hold blank space: %s" % tall
        assert not clipped, "collapsed cards clip their own title: %s" % clipped
    finally:
        hub.close()
        _pump(150)


def test_ops_alert_card_shows_newest_unacknowledged_alerts():
    from palisade_qt import eventbus
    hub = _hub(demo=False)
    try:
        for i in range(6):
            eventbus.bus.publish(eventbus.alert("T%d" % i, "event %d" % i, severity="warn"))
        _pump(60)
        ops = hub.pages["OPS"]
        texts = [w.text() for w in ops.card_alert.findChildren(QtWidgets.QLabel) if w.isVisible()]
        joined = " | ".join(texts)
        assert "6 unacknowledged" in joined
        for i in (5, 4, 3, 2):
            assert "event %d" % i in joined, joined
        hub.alerts.ack(hub.alerts.items[0]["id"])
        _pump(40)
        texts = [w.text() for w in ops.card_alert.findChildren(QtWidgets.QLabel) if w.isVisible()]
        assert "5 unacknowledged" in " | ".join(texts)
        # a re-render must not leave the previous rows painted underneath (RA-CL1 render: the
        # first alert row overlapped an older one until the deferred delete ran)
        rows = [w for w in ops.card_alert.findChildren(QtWidgets.QLabel)
                if w.isVisible() and "event" in w.text()]
        assert len(rows) <= 4, [w.text() for w in rows]
    finally:
        hub.close()
        _pump(150)


# ================================================================ 16. RADIOS refreshes while open
def test_radios_panel_rereads_the_kernel_while_visible(tmp_path):
    from palisade_qt import panels
    _app()
    root = _fake_sysfs(tmp_path)
    host = QtWidgets.QWidget()
    host.resize(1280, 720)
    p = panels.RadiosPanel("dark", host, sys_root=root)
    try:
        p._poll.setInterval(50)
        host.show()
        p.open()
        _pump(60)
        assert p.table.model.rows[0]["present"] == "ABSENT"
        d = tmp_path / "bus" / "usb" / "devices" / "1-9"
        d.mkdir(parents=True)
        (d / "idVendor").write_text("0bda\n")
        (d / "idProduct").write_text("2838\n")
        assert _wait(lambda: any(r["present"] == "PRESENT" for r in p.table.model.rows), 2.0), \
            "a dongle plugged in while the panel is open never shows"
        p.close_overlay()
        assert not p._poll.isActive(), "the poll must stop when the panel is hidden"
    finally:
        p.stop()
        host.close()


# ================================================================ 17. keys
def test_r_e_m_keys_and_panic_with_a_panel_open():
    import txguard
    hub = _hub(demo=True)
    try:
        hub._list_children = lambda: []
        toggled = []
        hub.topbar.toggle_mute = lambda: toggled.append(1)
        _key(hub, None, "r")
        assert hub.top_overlay() is hub.radios_panel
        _key(hub, QtCore.Qt.Key_Escape)
        _key(hub, None, "e")
        assert hub.top_overlay() is hub.engage_panel
        txguard.arm(True)
        _key(hub, QtCore.Qt.Key_F12)
        assert not txguard.is_armed(), "PANIC is dead while a panel is open"
        hub.engage_panel.close_overlay()
        hub.setFocus()
        _pump(20)
        _key(hub, None, "m")
        assert toggled == [1]
    finally:
        hub.close()
        _pump(150)


def test_bracket_keys_step_prowl_scan_bank_and_fm_frequency():
    hub = _hub(demo=True)
    try:
        hub.open_callsign("PROWL", "SCAN")
        _pump(100)
        prowl = hub.page_app("PROWL")
        hub.setFocus()
        n = prowl.bank_combo.count()
        start = prowl.bank_combo.currentIndex()
        _key(hub, None, "]")
        assert n < 2 or prowl.bank_combo.currentIndex() == (start + 1) % n
        _key(hub, None, "[")
        assert prowl.bank_combo.currentIndex() == start
        hub.open_callsign("PROWL", "FM")
        _pump(60)
        hub.setFocus()
        f0 = prowl.fm_freq.value()
        _key(hub, None, "]")
        assert abs(prowl.fm_freq.value() - (f0 + 0.2)) < 0.051
        _key(hub, None, "[")
        assert abs(prowl.fm_freq.value() - f0) < 0.051
    finally:
        hub.close()
        _pump(150)


# ================================================================ 18. SWEEP detectors start on open
def test_detectors_start_when_sweep_opens_and_not_before(monkeypatch):
    monkeypatch.setenv("PALISADE_SHOW_HIDDEN", "1")  # CL8 v0.1: SWEEP is hidden; its own test shows it
    from palisade_qt import sweep
    hub = _hub(demo=True)
    try:
        hub.open_callsign("RECON")
        _pump(80)
        assert "SWEEP" not in hub.pages, "SWEEP is built lazily: opening RECON must not start it"
        hub.open_callsign("SWEEP")
        _pump(120)
        page = hub.pages["SWEEP"]
        assert len(page._workers) == len(sweep.DETECTORS)
        assert all(w.isRunning() for w in page._workers)
    finally:
        hub.close()
        _pump(150)
    assert all(not w.isRunning() for w in page._workers), "detector threads outlived the hub"
