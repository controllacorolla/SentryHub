"""CL1-fix2 — regression tests for what RA-CL1b reopened (plan/briefs/CL1-fix2.md).

N1 ATLAS table fits / never clips a value · N2 list selection follows the item, not the row number ·
N10 PANIC's SIGKILL fallback and group kill are load-bearing · N3 PANIC revokes the BENCH ack ·
D7 function label visible beside every key · item 6 panels fail to UNKNOWN · ack-all only acks
what the operator has seen. Headless (Qt offscreen); process tests spawn only `sh` and `sleep`.
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

from PySide6 import QtCore, QtGui  # noqa: E402

from test_cl1_screen import _app, _pump, _hub, _isolate, THEMES  # noqa: E402

_isolate = _isolate          # autouse isolation fixture applies here too


def _wait(cond, timeout=5.0):
    end = time.time() + timeout
    while not cond() and time.time() < end:
        _pump(20)
    return cond()


# ================================================================ N1 ATLAS table fits
@pytest.mark.parametrize("mode", THEMES)
def test_atlas_table_fits_without_hscroll_and_never_clips_a_value(mode):
    """RA-CL1b N1: 470 px of columns in a 438 px viewport cut right-aligned altitudes off with no
    marker (15023 read as 150). Every visible cell must fit its column or be elided with '…', and
    the table must not scroll sideways."""
    hub = _hub(demo=True, mode=mode)
    try:
        hub.resize(1280, 720)
        hub.show()
        hub.open_callsign("ATLAS")
        atlas = hub.pages["ATLAS:inner"]
        assert _wait(lambda: len(atlas.feed.model.rows) >= 5, 6.0), "demo contacts did not arrive"
        # the hard case: a long callsign/ID and a 6-digit altitude must still not push the table
        # past the viewport (it elides with '…' instead)
        atlas._contacts["LONG"] = {"id": "LONG", "label": "OP RID-1581F5FAB2C3D4E5F60718", "kind": "aircraft",
                                   "x": 1.0, "y": 1.0, "alt": 123456, "spd": 400, "severity": "info",
                                   "_ts": time.time() + 3600, "rng": 1.4, "brg": 45.0}
        atlas._render()
        _pump(200)
        assert any(r["_id"] == "LONG" for r in atlas.feed.model.rows)
        view, model = atlas.feed.view, atlas.feed.model
        hdr = view.horizontalHeader()
        total = sum(hdr.sectionSize(i) for i in range(hdr.count()))
        assert total <= view.viewport().width(), (total, view.viewport().width())
        assert not view.horizontalScrollBar().isVisible()
        assert view.textElideMode() == QtCore.Qt.ElideRight
        fm = view.fontMetrics()
        pad = 12                                     # QSS item padding 6 + 6
        for r, row in enumerate(model.rows):
            for c in range(model.columnCount()):
                text = model.data(model.index(r, c))
                room = hdr.sectionSize(c) - pad
                if fm.horizontalAdvance(text) > room:
                    shown = fm.elidedText(text, QtCore.Qt.ElideRight, room)
                    assert shown.endswith("…"), (text, shown)
                    # the full value is still reachable
                    assert model.data(model.index(r, c), QtCore.Qt.ToolTipRole) == text
    finally:
        hub.close()
        _pump(150)


# ================================================================ N2 selection by item
def test_feed_selection_follows_the_item_across_a_resort_and_the_detail_matches():
    from palisade_qt.kit.feed import FeedTable
    _app()
    ft = FeedTable([("label", "ID"), ("rng", "NM")])
    ft.resize(400, 300)
    ft.show()
    shown = []
    ft.selected.connect(lambda r: shown.append((r["_id"], r["rng"])))
    ft.model.set_rows([{"_id": "A", "label": "A", "rng": "1"}, {"_id": "B", "label": "B", "rng": "2"},
                       {"_id": "C", "label": "C", "rng": "3"}])
    _pump(20)
    ft.move_cursor(1)
    ft.move_cursor(0)                     # cursor on B
    _pump(10)
    assert shown[-1][0] == "B"
    # re-sorted, a new row first, B's data changed
    ft.model.set_rows([{"_id": "X", "label": "X", "rng": "0"}, {"_id": "C", "label": "C", "rng": "1"},
                       {"_id": "B", "label": "B", "rng": "9"}, {"_id": "A", "label": "A", "rng": "4"}])
    _pump(20)
    row = ft.view.currentIndex().row()
    assert row >= 0, "selection lost"            # rows[-1] would silently read the last row
    assert ft.model.rows[row]["_id"] == "B", "highlight moved to a different item"
    assert shown[-1] == ("B", "9"), "detail did not follow the selected item's fresh data"
    # the selected item disappears: no highlight on some other item
    ft.model.set_rows([{"_id": "X", "label": "X", "rng": "0"}, {"_id": "A", "label": "A", "rng": "4"}])
    _pump(20)
    assert ft.view.currentIndex().row() < 0 and not ft.view.selectionModel().hasSelection()


def test_atlas_keeps_the_same_aircraft_selected_when_it_resorts():
    hub = _hub(demo=True)
    try:
        hub.resize(1280, 720)
        hub.show()
        hub.open_callsign("ATLAS")
        atlas = hub.pages["ATLAS:inner"]
        assert _wait(lambda: len(atlas.feed.model.rows) >= 4, 6.0)
        atlas.feed.move_cursor(2)
        _pump(20)
        cur = atlas.feed.view.currentIndex().row()
        assert cur >= 0
        cid = atlas.feed.model.rows[cur]["_src"]["id"]
        assert atlas._selected == cid
        # force a re-sort: push the selected contact to the far edge
        atlas._contacts[cid]["rng"] = 1e6
        atlas._render()
        _pump(30)
        row = atlas.feed.view.currentIndex().row()
        assert row >= 0 and atlas.feed.model.rows[row]["_src"]["id"] == cid
        assert atlas._selected == cid
    finally:
        hub.close()
        _pump(150)


# ================================================================ N10 PANIC escalation + group kill
_TRAPPED = "trap '' TERM; sleep 311 | sleep 312"       # every member ignores SIGTERM


def _group(pgid):
    out = subprocess.run(["pgrep", "-g", str(pgid)], capture_output=True, text=True).stdout
    return [int(x) for x in out.split()]


def _kill_group(proc):
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except OSError:
        pass
    proc.wait(timeout=5)


def test_panic_kills_a_pipeline_that_ignores_sigterm():
    """Fails if the SIGKILL fallback is removed: SIGTERM alone leaves every member running."""
    from palisade_qt import procs
    proc = subprocess.Popen(["sh", "-c", _TRAPPED], start_new_session=True)
    try:
        assert _wait(lambda: len(_group(proc.pid)) >= 3)
        members = _group(proc.pid)
        res = procs.stop_tree([proc.pid], term_wait=0.3, kill_wait=1.0)
        alive = [p for p in members if procs.alive(p)]
        assert not alive, "survived PANIC: %s" % alive
        assert sorted(res["stopped"]) == sorted(set(res["targets"])) and not res["survivors"]
    finally:
        _kill_group(proc)


def test_panic_group_kill_reaches_members_the_snapshot_missed():
    """Fails if the process-group kill is removed: when the child listing misses the pipeline
    members (spawned after the snapshot, or reparented), only killpg reaches them."""
    from palisade_qt import procs
    proc = subprocess.Popen(["sh", "-c", _TRAPPED], start_new_session=True)
    try:
        assert _wait(lambda: len(_group(proc.pid)) >= 3)
        members = _group(proc.pid)

        def blind(argv):                     # pgrep sees nothing; ps still answers for alive()
            return "" if argv[0] == "pgrep" else procs._run(argv)
        procs.stop_tree([proc.pid], term_wait=0.3, kill_wait=1.0, run=blind)
        alive = [p for p in members if procs.alive(p)]
        assert not alive, "group members survived: %s" % alive
    finally:
        _kill_group(proc)


# ================================================================ N3 PANIC revokes the BENCH ack
def test_panic_unchecks_the_bench_ack_and_the_slot_reads_the_gate():
    import bench as bench_engine
    hub = _hub(demo=False)
    try:
        hub._list_children = lambda: []
        hub.open_callsign("BENCH")
        _pump(80)
        bench = hub.pages["BENCH"]
        # CL2/G1: BENCH needs the kill switch armed + the session unlocked, not just the ack
        import txguard
        txguard.arm(True)
        txguard.unlock_session(True)
        bench.ack.setChecked(True)
        _pump(30)
        hub.state.poll()
        assert hub.topbar.slots["tx"].text() == "UNLOCKED"
        hub.panic()
        _pump(40)
        assert not bench.ack.isChecked()
        ok, _why = bench_engine.preflight(bench._settings(), bench._band_freq())
        assert not ok, "bench gate still passes after PANIC"
        assert not bench.tx_btn.isEnabled()
        assert hub.topbar.slots["tx"].text() == "OFF"
        text = hub.panic_banner.text()
        assert "not revoked" not in text
        assert "BENCH ack revoked" in text and "TX OFF" in text, text
    finally:
        hub.close()
        _pump(150)


def test_panic_banner_reports_a_permit_that_survives(monkeypatch):
    """If some gate still passes after PANIC, the banner says so from the re-read — never silent."""
    from palisade_qt import chrome
    hub = _hub(demo=False)
    try:
        hub._list_children = lambda: []
        chrome.report_tx_permit("TESTRIG", True)     # a source PANIC has no revoke hook for
        hub.panic()
        assert "TX still PERMITTED (TESTRIG)" in hub.panic_banner.text()
        assert hub.topbar.slots["tx"].text() == "PERMITTED"
    finally:
        chrome.report_tx_permit("TESTRIG", False)
        hub.close()
        _pump(150)


# ================================================================ D7 function label visible
def _ink(img, bg):
    n = 0
    for y in range(img.height()):
        for x in range(img.width()):
            c = QtGui.QColor(img.pixel(x, y))
            if abs(c.red() - bg.red()) + abs(c.green() - bg.green()) + abs(c.blue() - bg.blue()) > 120:
                n += 1
    return n


@pytest.mark.parametrize("mode", THEMES)
def test_every_nav_key_shows_its_function_label_beside_the_callsign(mode):
    """Owner decision D7 (2026-11-15): callsign over function label, both >= 16 px, strip <= 40 px,
    the whole strip inside 1280 px. Checked on painted pixels: a clipped glyph fails."""
    from palisade_qt.ops import CALLSIGNS
    from palisade_qt.kit.topbar import STRIP_H
    hub = _hub(mode=mode)
    try:
        hub.resize(1280, 720)
        hub.show()
        _pump(100)
        assert hub.topbar.height() <= 40 and STRIP_H <= 40
        assert hub.topbar.minimumSizeHint().width() <= 1280
        for i, (name, label) in enumerate(CALLSIGNS, start=1):
            key = hub.topbar.nav_keys[name]
            lbl = key.label
            assert lbl.isVisibleTo(hub) and lbl.text() == label
            for w in (key.call, lbl):
                assert QtGui.QFontInfo(w.font()).pixelSize() >= 16, (name, w.text())
                assert w.fontMetrics().horizontalAdvance(w.text()) <= w.width(), (name, w.text())
            assert lbl.geometry().top() >= key.call.geometry().bottom() - 8, "label not below"
            # every glyph pixel is painted: compare with the same text drawn unclipped
            for w in (key.call, lbl):
                # what is ON SCREEN: the strip's pixels at the label's rect (parent clipping and
                # the real background included; a label's own grab() would be transparent)
                top_left = w.mapTo(hub.topbar, QtCore.QPoint(0, 0))
                got = hub.topbar.grab(QtCore.QRect(top_left, w.size())).toImage()
                bg = QtGui.QColor(got.pixel(0, 0))
                # compare only this text's own ink rows: the two line boxes overlap (by design),
                # but only where the other line has no ink
                tb = w.fontMetrics().tightBoundingRect(w.text())
                asc = w.fontMetrics().ascent()
                y0 = max(0, asc + tb.top() - 1)
                y1 = min(w.height() - 1, asc + tb.bottom() + 1)
                got = got.copy(0, y0, got.width(), y1 - y0 + 1)
                # the painted colour: the pixel in this line's own rows furthest from the background
                far = max((QtGui.QColor(got.pixel(x, y)) for x in range(got.width())
                           for y in range(got.height())),
                          key=lambda c: abs(c.red() - bg.red()) + abs(c.green() - bg.green())
                          + abs(c.blue() - bg.blue()))
                # the same text in the same rect and alignment, nothing clipping it
                ref = QtGui.QImage(w.size(), QtGui.QImage.Format_RGB32)
                ref.fill(bg)
                p = QtGui.QPainter(ref)
                p.setFont(w.font())
                p.setPen(far)
                p.drawText(QtCore.QRect(QtCore.QPoint(0, 0), w.size()), int(w.alignment()), w.text())
                p.end()
                ref = ref.copy(0, y0, ref.width(), y1 - y0 + 1)
                ink_ref = _ink(ref, bg)
                assert ink_ref > 0
                assert _ink(got, bg) >= 0.99 * ink_ref, (name, w.text(), "glyphs clipped")
            # and no border can cover a glyph, focused or not: ink stays clear of the key's
            # top/bottom border at its widest (the focus ring's top/bottom = the normal border)
            from palisade_qt import theme
            edge = int(theme.tokens(mode)["bw"].rstrip("px"))
            for w in (key.call, lbl):
                r = w.fontMetrics().tightBoundingRect(w.text())
                base = w.y() + w.fontMetrics().ascent()
                assert base + r.top() >= edge and base + r.bottom() < key.height() - edge, (name, w.text())
    finally:
        hub.close()
        _pump(150)


# ================================================================ item 6: panels fail to UNKNOWN
def test_radios_panel_shows_unknown_when_the_arbiter_read_raises(monkeypatch, tmp_path):
    from palisade_qt import panels, radio_arbiter
    _app()
    panel = panels.RadiosPanel("dark", None, sys_root=str(tmp_path))
    try:
        def boom(*a, **k):
            raise RuntimeError("arbiter lock wedged")
        monkeypatch.setattr(radio_arbiter.arbiter, "owner", boom)
        panel.refresh()
        hero = panel.holder.hero.text()
        assert "UNKNOWN" in hero and "FREE" not in hero
        assert not panel.takeover_btn.isEnabled()
        monkeypatch.setattr(panels.radios, "inventory", boom)
        panel.refresh()
        assert any(r.get("present") == "UNKNOWN" for r in panel.table.model.rows)
    finally:
        panel.stop()


def test_engagement_panel_shows_unknown_when_the_engine_read_raises(monkeypatch):
    import engagement
    from palisade_qt import panels
    _app()
    panel = panels.EngagePanel("dark", None)

    def boom(*a, **k):
        raise RuntimeError("engagement store unreadable")
    monkeypatch.setattr(engagement, "info", boom)
    monkeypatch.setattr(engagement, "actions", boom)
    panel.open()                                     # used to raise
    hero = panel.eng_detail.hero.text()
    assert "UNKNOWN" in hero
    assert any("UNKNOWN" in str(r.get("action", "")) for r in panel.eng_actions.model.rows)
    panel.close_overlay()


# ================================================================ ack all only what was seen
def test_ack_all_never_acks_an_alert_that_arrived_after_the_drawer_was_viewed():
    from palisade_qt import eventbus, panels
    hub = _hub()
    try:
        for i in range(3):
            eventbus.bus.publish(eventbus.alert("T", "old %d" % i, severity="warn"))
        _pump(20)
        hub.open_panel("alerts")
        _pump(20)
        eventbus.bus.publish(eventbus.alert("T", "arrived while open", severity="alert"))
        _pump(20)
        hub.alerts_drawer.ack_all_btn.click()
        _pump(20)
        new = [a for a in hub.alerts.items if not a["acked"]]
        assert [a["text"] for a in new] == ["arrived while open"]
        # the palette's "Acknowledge all" follows the same rule
        eventbus.bus.publish(eventbus.alert("T", "after", severity="alert"))
        _pump(20)
        cmd = dict(hub._commands())["Acknowledge all alerts"]
        cmd()
        assert {a["text"] for a in hub.alerts.items if not a["acked"]} == {"arrived while open", "after"}
        # viewing again makes them ackable
        hub.open_panel("alerts")
        hub.open_panel("alerts")
        _pump(20)
        hub.alerts_drawer.ack_all_btn.click()
        assert hub.alerts.unacked() == 0
    finally:
        panels.reset_alert_store()
        hub.close()
        _pump(150)


# ================================================================ RA-CL1b N4 (Low)
def test_a_scope_target_spelled_like_a_state_word_is_never_the_slot_word():
    from palisade_qt import chrome
    for word in ("NONE", "none", "OFF", "Unknown", "FREE"):
        assert chrome.scope_summary([word]) == "1 target", word
    assert chrome.scope_summary(["10.0.0.*"]) == "10.0.0.*"
