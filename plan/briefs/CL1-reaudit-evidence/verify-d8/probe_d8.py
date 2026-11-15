"""Verifier probe (scratch copy only): does the branch behaviour hold for the untested keys?"""
import pytest
from PySide6 import QtCore, QtWidgets
from PySide6.QtTest import QTest
from test_cl1_screen import _hub, _key, _pump, _isolate  # noqa


@pytest.mark.parametrize("which", ["radios", "engagement", "alerts", "palette", "keys"])
def test_probe_panic_with_overlay_open(which):
    import txguard
    hub = _hub(demo=True)
    try:
        hub._list_children = lambda: []
        hub.open_panel(which)
        _pump(100)
        assert hub.top_overlay() is not None
        txguard.arm(True)
        fw = QtWidgets.QApplication.focusWidget()
        print("PROBE overlay=%s focus=%s" % (which, type(fw).__name__))
        _key(hub, QtCore.Qt.Key_F12)
        assert not txguard.is_armed(), "PANIC dead with %s open" % which
    finally:
        txguard.arm(False)
        hub.close(); _pump(150)


def test_probe_r_e_m_keys():
    hub = _hub(demo=True)
    try:
        calls = []
        hub.topbar.toggle_mute = lambda: calls.append("mute")
        _key(hub, None, "r"); assert hub.radios_panel.isVisible()
        _key(hub, QtCore.Qt.Key_Escape); assert not hub.radios_panel.isVisible()
        _key(hub, None, "e"); assert hub.engage_panel.isVisible()
        _key(hub, QtCore.Qt.Key_Escape)
        _key(hub, None, "m"); assert calls == ["mute"]
    finally:
        hub.close(); _pump(150)


def test_probe_brackets_in_prowl():
    hub = _hub(demo=True)
    try:
        hub.open_callsign("PROWL", "SCAN"); _pump(100)
        app = hub.page_app("PROWL")
        hub.setFocus()
        n = app.bank_combo.count(); i0 = app.bank_combo.currentIndex()
        _key(hub, None, "]")
        print("PROBE bank n=%d %d->%d" % (n, i0, app.bank_combo.currentIndex()))
        assert n < 2 or app.bank_combo.currentIndex() == (i0 + 1) % n
        _key(hub, None, "[")
        assert app.bank_combo.currentIndex() == i0
    finally:
        hub.close(); _pump(150)


def test_probe_enter_acks_in_drawer():
    from palisade_qt import eventbus
    hub = _hub(demo=False)
    try:
        for i in range(3):
            eventbus.bus.publish(eventbus.alert("TEST", "alert %d" % i, severity="warn"))
        _pump(60)
        _key(hub, None, "a")
        assert hub.alerts_drawer.isVisible()
        before = hub.alerts.unacked()
        _key(hub, QtCore.Qt.Key_Return)
        print("PROBE unacked %d -> %d" % (before, hub.alerts.unacked()))
        assert hub.alerts.unacked() == before - 1
    finally:
        hub.close(); _pump(150)


def test_probe_ctrl_r_not_swallowed():
    hub = _hub(demo=True)
    try:
        hub.setFocus()
        QTest.keyClick(hub, QtCore.Qt.Key_R, QtCore.Qt.ControlModifier); _pump(40)
        assert not hub.radios_panel.isVisible()
    finally:
        hub.close(); _pump(150)


def test_probe_single_dispatch():
    """One press of a toggling key from a focused child must act once (palette opens, stays open)."""
    hub = _hub(demo=True)
    try:
        hub.open_callsign("PROWL", "SCAN"); _pump(100)
        n = []
        orig = hub.handle_key
        hub.handle_key = lambda ev: (n.append(ev.key()), orig(ev))[1]
        fw = QtWidgets.QApplication.focusWidget()
        QTest.keyClick(fw or hub, QtCore.Qt.Key_F5); _pump(40)   # unhandled key: propagates up
        print("PROBE handle_key calls for one unhandled press: %d (focus=%s)" % (len(n), type(fw).__name__))
        assert len(n) == 1
    finally:
        hub.close(); _pump(150)
