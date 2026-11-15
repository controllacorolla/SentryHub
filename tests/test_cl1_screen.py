"""CL1 — screen fit, 8-key structure, keyboard, legibility. Regression tests for audit findings
D1 D2 D3 D4(status slots) D7 D8 D9 D10 and the section-9 RADIOS panel + audio control.

Each test is derived from the audit's PoC or from the CL1 brief's "tests to add". Target screen is
1280x720 (plan/audit/AUDIT_INDEX.md correction). Headless via Qt's offscreen platform.
"""
import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")

SUITE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SUITE_DIR not in sys.path:
    sys.path.insert(0, SUITE_DIR)

from PySide6 import QtCore, QtGui, QtWidgets  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

SCREEN_W, SCREEN_H = 1280, 720
THEMES = ("dark", "light", "sun")
# Nothing is exempt from the 16 px floor any more. This set used to list exactly the classes the audit
# measured as too small (micro / navlabel / slotcap), which is why the test could never fail on
# them (CL1-fix item 12).
CAPTION_CLASSES = set()


def _app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def _pump(ms=200, step=10):
    import time
    app = _app()
    t = 0
    while t < ms:
        app.processEvents()
        time.sleep(step / 1000.0)
        t += step


@pytest.fixture(autouse=True)
def _isolate():
    import engagement
    import txguard
    from palisade_qt import chrome, eventbus, panels, radio_arbiter
    app = _app()
    saved = app.styleSheet()
    engagement.reset()
    txguard.reset_session()
    chrome.reset()
    panels.reset_alert_store()
    yield
    engagement.reset()
    txguard.reset_session()
    chrome.reset()
    panels.reset_alert_store()
    eventbus.bus.clear()
    radio_arbiter.arbiter._owner = None
    radio_arbiter.arbiter._lease = None
    app.setStyleSheet(saved)
    import gc
    gc.collect()
    app.processEvents()
    app.sendPostedEvents(None, 52)   # QEvent.DeferredDelete
    app.processEvents()


def _hub(mode="dark", demo=True):
    """A hub styled exactly as main() styles it, at the target screen size."""
    from palisade_qt import theme
    from palisade_qt.shell import PalisadeHub
    app = _app()
    theme.load_fonts()
    theme.set_app_font(app)
    app.setStyleSheet(theme.qss(mode))
    hub = PalisadeHub(demo=demo, mode=mode)
    hub.resize(SCREEN_W, SCREEN_H)
    hub.show()
    hub.activateWindow()
    _pump(150)
    return hub


def _every_view(hub):
    """Yield (key, sub-tab) after showing each page and each of its sub-tabs."""
    from palisade_qt.ops import CALLSIGNS
    for name, _label in CALLSIGNS:
        hub.open_callsign(name)
        _pump(60)
        page = hub.pages[name]
        tabs = page.subtabs()
        if not tabs:
            yield name, None
        for t in tabs:
            page.switch_subtab(t)
            _pump(40)
            yield name, t


def _worst_case_strip(hub):
    """The widest state the status slots can show: the longest owner label, the longest scope
    summary chrome.scope_summary can produce (one SCOPE_CHARS-long target, or '128 targets')."""
    from palisade_qt import chrome, radio_arbiter
    owner = max(radio_arbiter.OWNER_LABELS.values(), key=len)
    scope = max([chrome.scope_summary(["A" * chrome.SCOPE_CHARS]),
                 chrome.scope_summary(["x"] * 128)], key=len)
    hub.topbar.set_state("DEMO", ("HELD", owner), "PERMITTED",
                         ("ACTIVE", scope, "long engagement name"))
    hub.topbar.set_alerts(128)
    _pump(30)


# ============================================================ D1 / D3: it fits the screen
@pytest.mark.parametrize("mode", THEMES)
@pytest.mark.parametrize("demo", [True, False])
def test_every_page_and_subtab_fits_1280x720(mode, demo):
    """D1: every page (and every sub-tab) fits the 1280x720 panel with the top strip present, in
    every theme, in live and demo, with the status slots at their widest."""
    hub = _hub(mode, demo)
    try:
        _worst_case_strip(hub)
        for name, tab in _every_view(hub):
            hint = hub.minimumSizeHint()
            assert hint.width() <= SCREEN_W and hint.height() <= SCREEN_H, \
                "%s/%s needs %dx%d" % (name, tab, hint.width(), hint.height())
            hub.resize(SCREEN_W, SCREEN_H)
            _pump(20)
            assert (hub.width(), hub.height()) == (SCREEN_W, SCREEN_H), \
                "%s/%s forced the window to %dx%d" % (name, tab, hub.width(), hub.height())
    finally:
        hub.close()
        _pump(150)


def test_bench_long_reason_does_not_widen_the_window():
    """D1 PoC: BENCH's unwrapped REASON line pushed the window to 1845 px and it stayed that wide."""
    hub = _hub("dark", demo=False)
    try:
        bench = hub.page_app("BENCH")
        _pump(80)
        bench.ack.setChecked(False)
        bench._refresh_gate()             # the long "needs the conducted-only acknowledgment…" reason
        _pump(80)
        assert hub.minimumSizeHint().width() <= SCREEN_W
        hub.resize(SCREEN_W, SCREEN_H)
        _pump(30)
        assert hub.width() == SCREEN_W
        hub.open_callsign("OPS")          # and it does not stay wide afterwards
        _pump(30)
        assert hub.width() == SCREEN_W
    finally:
        hub.close()
        _pump(150)


def test_one_top_strip_no_rail_no_footer():
    """D1/D3: the left nav rail and the footer are gone; chrome is one strip of at most 40 px."""
    hub = _hub()
    try:
        assert hub.topbar.height() <= 40
        assert hub.findChild(QtWidgets.QFrame, "nav_rail") is None
        assert hub.findChild(QtWidgets.QFrame, "foot_bar") is None
        # the page starts directly under the strip and runs to the bottom of the window
        page = hub.stack
        assert page.height() >= SCREEN_H - 40 - 2 * 6      # minus the DEMO border
    finally:
        hub.close()
        _pump(150)


def test_detail_card_values_wrap_and_empty_card_collapses():
    """D1 + D10: a long value wraps instead of widening; an empty card shows no 40 px dash."""
    _app()
    from palisade_qt.kit import DetailCard
    c = DetailCard("X")
    c.show()
    assert c.is_empty() and not c.hero.isVisible(), "an empty detail card must collapse"
    c.set_rows([("REASON", "conducted-bench TX needs the conducted-only acknowledgment: " * 6)])
    _pump(20)
    assert c.minimumSizeHint().width() < 400, "a long value must wrap, not set the width"
    c.set_hero("City PD", "453.212 MHz")
    assert c.hero.isVisible()
    c.close()


def test_no_desktop_fixed_minimums():
    """D1 minor: the sky dome's 360x360 and the SSTV panel's 240 px minimums are gone."""
    _app()
    from palisade_qt import theme
    from palisade_qt.overwatch import SkyDome
    from palisade_qt.babel import SstvImagePanel
    assert SkyDome(theme.tokens("dark")).minimumHeight() <= 200
    assert SstvImagePanel().view.minimumHeight() <= 120


# ============================================================ D2: legibility
def _px(widget):
    widget.ensurePolished()
    return widget.fontInfo().pixelSize()


def _status_widgets(root):
    for w in root.findChildren(QtWidgets.QWidget):
        if not w.isVisible():
            continue
        if isinstance(w, QtWidgets.QLabel):
            if not w.text().strip() or w.pixmap() is not None and not w.pixmap().isNull():
                continue
            if (w.property("class") or "").split(" ")[0] in CAPTION_CLASSES:
                continue
            yield w
        elif isinstance(w, (QtWidgets.QAbstractButton, QtWidgets.QLineEdit, QtWidgets.QComboBox,
                            QtWidgets.QAbstractSpinBox, QtWidgets.QTableView,
                            QtWidgets.QHeaderView, QtWidgets.QPlainTextEdit,
                            QtWidgets.QListWidget, QtWidgets.QTabBar)):
            yield w


@pytest.mark.parametrize("mode", THEMES)
def test_no_status_bearing_text_under_16px(mode):
    """D2: nothing that carries state is under 16 px; only static captions may be smaller."""
    hub = _hub(mode, demo=True)
    try:
        _pump(600)                                    # let demo data fill the tables
        small = []
        for name, tab in _every_view(hub):
            for w in _status_widgets(hub):
                if _px(w) < 16:
                    small.append("%s/%s %s %r %dpx" % (name, tab, type(w).__name__,
                                                       getattr(w, "text", lambda: "")()[:30], _px(w)))
        for panel in ("radios", "engagement", "alerts", "keys", "palette"):
            hub.open_panel(panel)
            _pump(40)
            for w in _status_widgets(hub.top_overlay()):
                if _px(w) < 16:
                    small.append("panel %s %s %dpx" % (panel, type(w).__name__, _px(w)))
            hub.open_panel(panel)
        assert not small, "status-bearing text under 16 px:\n  " + "\n  ".join(sorted(set(small))[:25])
    finally:
        hub.close()
        _pump(150)


def test_type_scale_and_row_height():
    """D2: body 18 px, status 16 px, table rows 40 px."""
    _app()
    from palisade_qt import theme
    from palisade_qt.kit import FeedTable
    assert theme.FONT_BODY == 18 and theme.FONT_STATUS == 16 and theme.ROW_H == 40
    t = FeedTable([("a", "A"), ("b", "B")])
    assert t.view.verticalHeader().defaultSectionSize() == 40


def test_ui_scale_is_pinned_and_overridable():
    """D2: the layout is in physical pixels for the 1280x720 panel, so desktop auto-scaling is
    switched off by default; PALISADE_UI_SCALE overrides; an explicit QT_SCALE_FACTOR is respected."""
    from palisade_qt import theme
    env = {}
    assert theme.configure_scale(env) == 1.0
    assert env["QT_SCALE_FACTOR"] == "1" and env["QT_ENABLE_HIGHDPI_SCALING"] == "0"
    env = {"PALISADE_UI_SCALE": "1.25"}
    assert theme.configure_scale(env) == 1.25 and env["QT_SCALE_FACTOR"] == "1.25"
    env = {"QT_SCALE_FACTOR": "2"}
    theme.configure_scale(env)
    assert env["QT_SCALE_FACTOR"] == "2", "an operator's explicit Qt setting must not be overwritten"
    assert theme.configure_scale({"PALISADE_UI_SCALE": "garbage"}) == 1.0


# ============================================================ D4: shell-owned status slots
def test_four_fixed_status_slots_exist_with_word_and_shape():
    hub = _hub(demo=False)
    try:
        assert list(hub.topbar.slots) == ["mode", "radio", "tx", "engagement"]
        assert hub.topbar.slots["mode"].text() == "LIVE"
        assert hub.topbar.slots["radio"].text() == "FREE"
        assert hub.topbar.slots["tx"].text() == "OFF"
        assert hub.topbar.slots["engagement"].text() == "NONE"
        # every state is a word AND a shape; distinct states draw distinct shapes
        hub.topbar.set_state("DEMO", ("HELD", "APRS"), "ARMED", ("ACTIVE", "10.0.0.*", "x"))
        shapes = {k: s.glyph.shape() for k, s in hub.topbar.slots.items()}
        assert shapes == {"mode": "hatch", "radio": "dot", "tx": "square", "engagement": "diamond"}
        hub.topbar.set_state("LIVE", ("FREE", ""), "PERMITTED", ("NONE", "", ""))
        assert hub.topbar.slots["tx"].glyph.shape() == "tri"
    finally:
        hub.close()
        _pump(150)


def test_pages_cannot_overwrite_the_status_slots():
    """D4 / H7 PoC: RECON demo used to turn the shared chip from 'SDR DEMO' into '5 AP'. A page's
    status now lands in its own row; the strip's slots do not move."""
    hub = _hub(demo=True)
    try:
        assert not hasattr(hub.topbar, "set_chip"), "the strip must expose no page-writable chip"
        hub.open_callsign("RECON")
        _pump(700)                                  # the demo Wi-Fi worker reports 'N AP'
        recon = hub.pages["RECON"]
        before = {k: s.text() for k, s in hub.topbar.slots.items()}
        recon.set_chip("sdr", "5 AP", state="neutral")
        recon.set_chip("tx", "TX SAFE", state="live")        # even a page claiming 'tx'
        _pump(30)
        assert {k: s.text() for k, s in hub.topbar.slots.items()} == before
        assert hub.topbar.slots["mode"].text() == "DEMO"
        assert recon.page_status().get("sdr") == "5 AP", "page status belongs to the page row"
    finally:
        hub.close()
        _pump(150)


def test_slots_follow_engine_state():
    """The slots are read from the engines: txguard arm, an open engagement, the radio arbiter."""
    import engagement
    import txguard
    from palisade_qt import radio_arbiter as ra
    hub = _hub(demo=False)
    try:
        txguard.arm(True)
        hub.state.poll()
        assert hub.topbar.slots["tx"].text() == "ARMED"
        txguard.arm(False)
        hub.state.poll()
        assert hub.topbar.slots["tx"].text() == "OFF"
        engagement.start("Op", "ROE-1", ["10.0.0.*"], "N0CALL")
        hub.state.poll()
        assert hub.topbar.slots["engagement"].text() == "10.0.0.*"     # the scope is the word
        assert hub.topbar.slots["engagement"].glyph.shape() == "diamond"
        assert "ACTIVE" in hub.topbar.slots["engagement"].toolTip()
        ra.arbiter.changed.emit("ATLAS-APRS")
        _pump(20)
        assert hub.topbar.slots["radio"].text() == "APRS"
        assert "HELD" in hub.topbar.slots["radio"].toolTip()
        ra.arbiter.changed.emit("")
        _pump(20)
        assert hub.topbar.slots["radio"].text() == "FREE"
    finally:
        hub.close()
        _pump(150)


def test_tx_safe_is_retired_and_bench_permit_shows_in_the_tx_slot():
    """D4: 'TX SAFE' meant 'not transmitting' in the bar and 'transmit permitted' in BENCH. Now the
    slot says OFF / PERMITTED / ARMED and BENCH says PERMITTED / GATED."""
    hub = _hub(demo=False)
    try:
        for lbl in hub.findChildren(QtWidgets.QLabel):
            assert "TX SAFE" not in lbl.text()
        bench = hub.page_app("BENCH")
        _pump(60)
        assert hub.topbar.slots["tx"].text() == "OFF"
        bench.ack.setChecked(True)
        hub.state.poll()
        assert "PERMITTED" in bench.gate.text()
        assert hub.topbar.slots["tx"].text() == "PERMITTED"
        bench.ack.setChecked(False)
        hub.state.poll()
        assert hub.topbar.slots["tx"].text() == "OFF"
    finally:
        hub.close()
        _pump(150)


def test_demo_draws_a_border_and_live_does_not():
    hub = _hub(demo=True)
    try:
        assert hub.demo_border is not None and hub.demo_border.isVisible()
        assert hub.demo_border.width() == hub.centralWidget().width()
        assert hub.topbar.slots["mode"].text() == "DEMO"
    finally:
        hub.close()
        _pump(150)
    live = _hub(demo=False)
    try:
        assert live.demo_border is None and live.topbar.slots["mode"].text() == "LIVE"
    finally:
        live.close()
        _pump(150)


def test_disabled_buttons_look_disabled():
    """D4: locked attack buttons looked enabled because :disabled had no style."""
    from palisade_qt import theme
    for mode in THEMES:
        qss = theme.qss(mode)
        assert "QPushButton:disabled" in qss and "dashed" in qss.split("QPushButton:disabled")[1][:120]


# ============================================================ D7: the 8-key structure
def test_eight_keys_in_order_with_function_labels():
    from palisade_qt.ops import CALLSIGNS
    from palisade_qt.shell import QT_PAGES
    assert [n for n, _ in CALLSIGNS] == ["OPS", "ATLAS", "PRISM", "PROWL", "SWEEP", "RECON",
                                         "FORGE", "SYSTEM"]
    assert set(QT_PAGES) == {"ATLAS", "PRISM", "PROWL", "SWEEP", "RECON", "FORGE", "SYSTEM"}
    hub = _hub()
    try:
        assert list(hub.topbar.nav_keys) == [n for n, _ in CALLSIGNS]
        for i, (name, label) in enumerate(CALLSIGNS, start=1):
            key = hub.topbar.nav_keys[name]
            assert key.call.text() == "%d %s" % (i, name)
            # the function word is not drawn in the strip (nothing there under 16 px); it is
            # in the tooltip, the key map and the palette
            assert key.function == label and label in key.toolTip()
    finally:
        hub.close()
        _pump(150)


def test_folded_pages_live_where_the_brief_put_them():
    """BABEL -> PROWL, OVERWATCH's sky views -> ATLAS, BENCH -> SYSTEM, COUNTER -> SWEEP, ENGAGE ->
    the top strip. The radio dashboard is the RADIOS panel."""
    from palisade_qt.babel import BabelApp
    from palisade_qt.bench_app import BenchApp
    from palisade_qt.overwatch import OverwatchApp
    from palisade_qt.pages import AtlasPage, ProwlPage, SystemPage
    from palisade_qt.recon import SUBTABS as RECON_TABS
    from palisade_qt.sweep import DETECTORS
    assert AtlasPage(demo=True).subtabs() == ["MAP", "SKY DOME", "PASSES"]
    assert ProwlPage(demo=True).subtabs() == ["SCAN", "FM", "NWR", "DECODE"]
    assert SystemPage(demo=True).subtabs() == ["SETTINGS", "DOCTOR", "ASSISTANT", "MESH", "SITREP",
                                               "BENCH"]
    assert RECON_TABS == ("WIFI", "BLE", "NET", "RF"), "COUNTER and ENGAGE left RECON"
    assert DETECTORS == ("bugsweep", "jammer", "imsicatch", "gnss")
    hub = _hub()
    try:
        assert isinstance(hub.page_app("BABEL"), BabelApp)
        assert hub._current == "PROWL" and hub.pages["PROWL"].current_subtab() == "DECODE"
        assert isinstance(hub.page_app("OVERWATCH"), OverwatchApp)
        assert hub._current == "ATLAS" and hub.pages["ATLAS"].current_subtab() == "SKY DOME"
        assert isinstance(hub.page_app("BENCH"), BenchApp)
        assert hub._current == "SYSTEM" and hub.pages["SYSTEM"].current_subtab() == "BENCH"
        assert not hasattr(hub.page_app("OVERWATCH"), "hist_feed"), "radio view left OVERWATCH"
        assert hub.radios_panel.hist_feed is not None
        assert hub.engage_panel.eng_scope is not None
    finally:
        hub.close()
        _pump(150)


def test_composite_child_is_only_active_while_its_tab_is_in_front():
    """Moving a page under a composite must not change who is 'active' (PRISM/PROWL release the
    radio when backgrounded)."""
    from palisade_qt.babel import BabelApp
    from palisade_qt.prowl import ProwlApp
    hub = _hub()
    try:
        hub.open_callsign("PROWL", "SCAN")
        page = hub.pages["PROWL"]
        prowl, babel = page.child(ProwlApp), page.child(BabelApp)
        assert prowl._active and not babel._active
        page.switch_subtab("DECODE")
        assert babel._active and not prowl._active
        hub.open_callsign("OPS")
        assert not prowl._active and not babel._active
    finally:
        hub.close()
        _pump(150)


# ============================================================ D8: keyboard
def _key(hub, key, text=""):
    target = QtWidgets.QApplication.focusWidget() or hub
    QTest.keyClick(target, key) if not text else QTest.keyClicks(target, text)
    _pump(40)


def test_every_page_key_parses_to_a_real_key():
    """D8 PoC: QKeySequence('10') parsed to nothing, so the tenth page had no shortcut."""
    from palisade_qt.ops import CALLSIGNS
    assert len(CALLSIGNS) <= 9, "page keys are single digits"
    for i, (name, _label) in enumerate(CALLSIGNS, start=1):
        seq = QtGui.QKeySequence(str(i))
        assert seq.toString() != "" and seq.count() == 1, "%s has no usable key" % name
    assert QtGui.QKeySequence("10").toString() == "", "the old bug: a two-digit key is not a key"


def test_keyboard_only_walk_reaches_every_page_and_subtab():
    """D8: digits open every page, Left/Right reach every sub-tab, Esc returns home — no pointer."""
    from palisade_qt.ops import CALLSIGNS
    hub = _hub()
    try:
        for i, (name, _label) in enumerate(CALLSIGNS, start=1):
            _key(hub, None, str(i))
            assert hub._current == name, "key %d should open %s" % (i, name)
            page = hub.pages[name]
            tabs = page.subtabs()
            seen = {page.current_subtab()} if tabs else set()
            for _ in tabs:
                _key(hub, QtCore.Qt.Key_Right)
                seen.add(page.current_subtab())
            assert seen == set(tabs), "%s: Right arrow reached %s of %s" % (name, seen, tabs)
            if tabs:
                first = page.current_subtab()
                _key(hub, QtCore.Qt.Key_Left)
                assert page.current_subtab() != first, "Left steps back"
        _key(hub, QtCore.Qt.Key_Escape)
        assert hub._current == "OPS", "Esc is back/home"
    finally:
        hub.close()
        _pump(150)


def test_up_down_drive_the_list_and_the_detail_follows():
    """D8 / B4 PoC: arrow keys never updated the detail card (selection fired on clicks only)."""
    hub = _hub(demo=True)
    try:
        _key(hub, None, "4")                         # PROWL / SCAN: a channel list + a detail card
        _pump(700)
        prowl = hub.page_app("PROWL")
        rows = prowl.feed.model.rows
        assert len(rows) >= 3
        prowl.detail.set_hero("—", "")
        _key(hub, QtCore.Qt.Key_Down)
        assert prowl.feed.view.currentIndex().row() == 0
        _key(hub, QtCore.Qt.Key_Down)
        assert prowl.feed.view.currentIndex().row() == 1
        assert prowl.detail.hero.text() == prowl.feed.model.rows[1]["label"], "detail follows"
        prowl.feed.model.set_rows(list(prowl.feed.model.rows))      # a refresh keeps the cursor
        assert prowl.feed.view.currentIndex().row() == 1
    finally:
        hub.close()
        _pump(150)


def test_enter_runs_the_primary_action_and_typing_is_never_stolen():
    hub = _hub(demo=True)
    try:
        _key(hub, None, "4")
        _pump(300)
        prowl = hub.page_app("PROWL")
        hub.setFocus()
        assert prowl.hold_btn.text() == "SCAN"
        _key(hub, QtCore.Qt.Key_Return)             # primary action on SCAN = hold / resume
        assert prowl.hold_btn.text() == "HOLD"
        _key(hub, None, " ")                        # Space holds / resumes too
        assert prowl.hold_btn.text() == "SCAN"
        # digits typed into a text field stay in the field; they do not change page
        prowl.fdb_input.setFocus()
        _key(hub, None, "146")
        assert prowl.fdb_input.text() == "146" and hub._current == "PROWL"
        _key(hub, QtCore.Qt.Key_Escape)             # Esc leaves the field first…
        assert hub._current == "PROWL"
        _key(hub, QtCore.Qt.Key_Escape)             # …then goes home
        assert hub._current == "OPS"
    finally:
        hub.close()
        _pump(150)


def test_band_and_span_keys_in_prism():
    hub = _hub(demo=True)
    try:
        _key(hub, None, "3")
        _pump(200)
        prism = hub.pages["PRISM"]
        hub.setFocus()
        c0, s0 = prism.centre.value(), prism.span.value()
        _key(hub, None, "]")
        assert prism.centre.value() == pytest.approx(c0 + s0)
        _key(hub, None, "[")
        assert prism.centre.value() == pytest.approx(c0)
        _key(hub, None, "+")
        assert prism.span.value() == pytest.approx(s0 / 2)
        _key(hub, None, "-")
        assert prism.span.value() == pytest.approx(s0)
    finally:
        hub.close()
        _pump(150)


def test_focus_and_checked_states_are_visible():
    """D8: focus was invisible and the selected sub-tab looked like the others."""
    from palisade_qt import theme
    for mode in THEMES:
        qss = theme.qss(mode)
        assert "QPushButton:focus" in qss and "QTableView:focus" in qss
        assert "QPushButton:checked" in qss
    hub = _hub()
    try:
        hub.open_callsign("RECON")
        rail = hub.pages["RECON"]._rail
        rail_checked = [n for n, b in rail.buttons.items() if b.isChecked()]
        assert rail_checked == ["WIFI"], "exactly the current sub-tab is checked"
        hub.pages["RECON"].switch_subtab("NET")
        assert [n for n, b in rail.buttons.items() if b.isChecked()] == ["NET"]
        assert all(b.focusPolicy() != QtCore.Qt.NoFocus for b in rail.buttons.values())
    finally:
        hub.close()
        _pump(150)


def test_key_map_and_command_palette():
    """D8: '?' shows the key map; '/' opens a palette that takes callsigns, actions and a bare
    frequency. The two advertised-but-unimplemented footer shortcuts are gone."""
    from palisade_qt import panels
    hub = _hub(demo=True)
    try:
        documented = " ".join(k for k, _ in panels.KEYMAP)
        assert "⌘" not in documented, "no unimplemented shortcut is advertised"
        _key(hub, None, "?")
        assert hub.keymap.isVisible()
        _key(hub, QtCore.Qt.Key_Escape)
        assert not hub.keymap.isVisible() and hub._current == "OPS"
        _key(hub, None, "/")
        assert hub.palette.isVisible() and hub.palette.input.hasFocus()
        labels = [lbl for lbl, _fn in hub.palette.matches("prowl fm")]
        assert "PROWL › FM" in labels
        hub.palette.input.setText("prowl fm")
        _pump(20)
        _key(hub, QtCore.Qt.Key_Return)
        assert not hub.palette.isVisible()
        assert hub._current == "PROWL" and hub.pages["PROWL"].current_subtab() == "FM"
        # a bare frequency offers a tune action
        hub.open_panel("palette")
        hub.palette.input.setText("162.55")
        _pump(20)
        assert hub.palette.list.item(0).text().startswith("Tune PROWL FM to 162.550")
    finally:
        hub.close()
        _pump(150)


def test_panic_key_disarms_ends_engagement_and_kills_children():
    """D8: one PANIC key. It only stops things — disarm TX, end the engagement, kill children."""
    import engagement
    import txguard
    from palisade_qt import eventbus, shell
    hub = _hub(demo=False)
    try:
        stopped = []
        hub._list_children = lambda: [4242, 4243]
        hub._stop_tree = lambda roots: (stopped.extend(roots) or
                                        {"targets": roots, "stopped": roots, "survivors": []})
        txguard.arm(True)
        txguard.unlock_session(True)
        engagement.start("Op", "ROE-1", ["10.0.0.*"], "N0CALL")
        hub.state.poll()
        assert hub.topbar.slots["tx"].text() == "ARMED"
        got = []
        eventbus.bus.published.connect(lambda e: got.append(e))
        assert shell.PANIC_KEY == "F12" and shell.PANIC_CHORD == "Shift+Esc"
        _key(hub, QtCore.Qt.Key_F12)
        assert not txguard.is_armed() and not txguard.session_unlocked()
        assert not engagement.is_active()
        assert stopped == [4242, 4243]
        assert "2 of 2 child process(es) stopped (verified gone)" in hub.panic_banner.text()
        assert hub.topbar.slots["tx"].text() == "OFF"
        assert hub.topbar.slots["engagement"].text() == "NONE"
        assert any(e["type"] == "alert" and "PANIC" in e["payload"]["text"] for e in got)
        assert hub.panic_banner.isVisible() and "PANIC" in hub.panic_banner.text()
    finally:
        hub.close()
        _pump(150)


def test_panic_works_while_typing():
    import txguard
    hub = _hub(demo=True)
    try:
        hub._list_children = lambda: []
        hub.open_callsign("PROWL")
        _pump(100)
        hub.page_app("PROWL").fdb_input.setFocus()
        txguard.arm(True)
        _key(hub, QtCore.Qt.Key_F12)
        assert not txguard.is_armed()
    finally:
        hub.close()
        _pump(150)


# ============================================================ D9: colour, word and shape
def test_sun_theme_is_black_and_white_at_7_to_1_with_2px_borders():
    from palisade_qt import theme
    sun = theme.tokens("sun")
    for key in ("text", "muted", "accent", "live", "warn", "alert", "disabled", "hairline", "focus"):
        assert theme.contrast(sun[key], sun["bg"]) >= 7.0, "sun %s is under 7:1" % key
    for key in ("bg", "p1", "p2", "well", "field", "text", "accent", "live", "warn", "alert"):
        c = sun[key].lstrip("#")
        assert c[0:2] == c[2:4] == c[4:6], "sun %s is not grey-scale" % key
    assert sun["bw"] == "2px"
    assert "border: 2px solid #000000" in theme.qss("sun")


def test_light_and_dark_status_colours_meet_contrast():
    """D9: light-mode green was 3.1:1 and amber 4.3:1 at 10 px; borders were 1.1-1.4:1."""
    from palisade_qt import theme
    for mode in ("dark", "light"):
        t = theme.tokens(mode)
        for key in ("text", "muted", "live", "warn", "alert", "accent"):
            assert theme.contrast(t[key], t["p1"]) >= 4.5, "%s %s under 4.5:1" % (mode, key)
        assert theme.contrast(t["hairline"], t["bg"]) >= 3.0, "%s borders under 3:1" % mode


def test_green_means_receiving_only_not_authorized_or_armed():
    """D9: green had leaked onto 'AUTHORIZED', 'engagement active' and 'TX armed + unlocked'."""
    import engagement
    import txguard
    from palisade_qt import theme
    from palisade_qt.bench_app import BenchApp
    from palisade_qt.forge import ForgeApp, EngagementCard, ReplayTxCard
    from palisade_qt.recon import ReconApp
    _app()
    green = theme.tokens("dark")["live"].lower()
    engagement.start("Op", "ROE-1", ["10.0.0.*", "aa:*"], "N0CALL")
    txguard.arm(True)
    txguard.unlock_session(True)
    forge = ForgeApp(demo=False, mode="dark")
    forge.refresh_gates()
    for card in forge._cards:
        assert green not in card.state.styleSheet().lower(), type(card).__name__
        if isinstance(card, EngagementCard):
            assert "engagement active" in card.state.text()
        if isinstance(card, ReplayTxCard):
            assert "armed + unlocked" in card.state.text()
    recon = ReconApp(demo=False, mode="dark")
    recon._refresh_gate()
    recon.net_gated.target.setText("10.0.0.5")
    recon.net_gated._authorize("discover")
    assert "AUTHORIZED" in recon.net_gated.result.text()
    assert green not in recon.net_gated.result.styleSheet().lower()
    assert green not in recon.net_gated.state.styleSheet().lower()
    bench = BenchApp(demo=False, mode="dark")
    bench.ack.setChecked(True)
    assert "PERMITTED" in bench.gate.text() and green not in bench.gate.styleSheet().lower()
    for a in (forge, recon, bench):
        a.stop()


# ============================================================ D10: alerts, send-to
def test_alerts_persist_until_acknowledged_not_capped_at_three():
    """D10 PoC: alerts capped at three and vanished, with no history or acknowledge."""
    from palisade_qt import eventbus
    hub = _hub(demo=False)
    try:
        for i in range(7):
            eventbus.bus.publish(eventbus.alert("TEST", "alert %d" % i, severity="warn"))
        for i in range(60):                          # map traffic must not evict them (H17's cause)
            eventbus.bus.publish(eventbus.contact("ATLAS", "AC%d" % i, 47.6, -122.3))
        _pump(60)
        assert len(hub.alerts.items) == 7 and hub.alerts.unacked() == 7
        assert hub.topbar.alerts.text() == "7"
        _key(hub, None, "a")
        assert hub.alerts_drawer.isVisible()
        assert hub.alerts_drawer.table.model.rowCount() == 7
        hub.alerts_drawer.table.view.selectRow(0)
        hub.alerts_drawer.ack_selected()
        assert hub.alerts.unacked() == 6 and hub.topbar.alerts.text() == "6"
        hub.alerts.ack_all()
        assert hub.alerts.unacked() == 0 and hub.topbar.alerts.text() == "0"
        assert len(hub.alerts.items) == 7, "acknowledged alerts stay in the history"
    finally:
        hub.close()
        _pump(150)


def test_prism_peak_can_be_sent_to_the_tuner():
    """D10: a peak in PRISM could not be sent to the tuner."""
    hub = _hub(demo=True)
    try:
        hub.open_callsign("PRISM")
        _pump(500)
        prism = hub.pages["PRISM"]
        assert prism._peak_mhz is not None and prism.send_btn.isEnabled()
        peak = prism._peak_mhz
        prism.send_btn.click()
        _pump(80)
        assert hub._current == "PROWL" and hub.pages["PROWL"].current_subtab() == "FM"
        assert hub.page_app("PROWL").fm_freq.value() == pytest.approx(round(peak, 1), abs=0.06)
    finally:
        hub.close()
        _pump(150)


# ============================================================ section 9: RADIOS panel + audio
def _fake_sysfs(tmp_path, usb=(), rfkill=()):
    for i, (vid, pid) in enumerate(usb):
        d = tmp_path / "bus" / "usb" / "devices" / ("1-%d" % (i + 1))
        d.mkdir(parents=True)
        (d / "idVendor").write_text(vid + "\n")
        (d / "idProduct").write_text(pid + "\n")
    (tmp_path / "bus" / "usb" / "devices").mkdir(parents=True, exist_ok=True)
    for i, (name, typ, soft, hard) in enumerate(rfkill):
        d = tmp_path / "class" / "rfkill" / ("rfkill%d" % i)
        d.mkdir(parents=True)
        for fname, val in (("name", name), ("type", typ), ("soft", soft), ("hard", hard)):
            (d / fname).write_text(val + "\n")
    (tmp_path / "class" / "rfkill").mkdir(parents=True, exist_ok=True)
    return str(tmp_path)


def test_radio_inventory_reads_presence_and_power(tmp_path):
    from palisade_qt import radios
    root = _fake_sysfs(tmp_path, usb=[("0bda", "2838"), ("046d", "c52b")],
                       rfkill=[("phy0", "wlan", "0", "0"), ("hci0", "bluetooth", "1", "0")])
    rows = radios.inventory(owner_label="APRS", sys_root=root)
    sdr = [r for r in rows if "RTL-SDR" in r["radio"]]
    assert len(sdr) == 1 and sdr[0]["present"] == "PRESENT" and sdr[0]["owner"] == "APRS"
    wifi = [r for r in rows if r["radio"].startswith("Wi-Fi")][0]
    bt = [r for r in rows if r["radio"].startswith("Bluetooth")][0]
    assert wifi["power"] == "ON" and bt["power"] == "BLOCKED (rfkill)"
    # no dongle plugged in -> ABSENT, never a guess
    empty = radios.inventory(sys_root=_fake_sysfs(tmp_path / "e"))
    assert empty[0]["present"] == "ABSENT"
    # a host with no sysfs at all -> UNKNOWN, never ABSENT or PRESENT
    nosys = radios.inventory(sys_root=str(tmp_path / "missing"))
    assert all(r["present"].startswith("UNKNOWN") for r in nosys)


def test_radios_panel_opens_from_the_radio_slot_and_frees_the_holder(monkeypatch):
    from palisade_qt import radio_arbiter as ra
    monkeypatch.setattr(ra, "_make_lease", lambda n: None)
    hub = _hub(demo=False)
    try:
        hub.topbar.slots["radio"].clicked.emit()
        _pump(40)
        assert hub.radios_panel.isVisible()
        assert hub.radios_panel.table.model.rowCount() >= 1
        assert not hub.radios_panel.takeover_btn.isEnabled()
        assert not hub.radios_panel.device_pick.isEnabled(), "selection is not implemented: say so"
        ra.arbiter.request("ATLAS-APRS")
        _pump(40)
        assert "APRS" in hub.radios_panel.holder.hero.text()
        assert hub.radios_panel.hist_feed.model.rowCount() == 1
        assert hub.topbar.slots["radio"].text() == "APRS"
        assert "HELD" in hub.topbar.slots["radio"].toolTip()
        hub.radios_panel.takeover_btn.click()
        _pump(40)
        assert ra.arbiter.owner() is None and hub.topbar.slots["radio"].text() == "FREE"
        _key(hub, QtCore.Qt.Key_Escape)
        assert not hub.radios_panel.isVisible()
    finally:
        hub.close()
        _pump(150)


def test_engagement_panel_opens_from_its_slot_and_refreshes_recon_cards():
    """ENGAGE moved to the strip; RECON's gated cards must still follow the gate."""
    import engagement
    hub = _hub(demo=False)
    try:
        hub.open_callsign("RECON")
        recon = hub.pages["RECON"]
        assert not recon.net_gated.target.isEnabled()
        hub.topbar.slots["engagement"].clicked.emit()
        _pump(40)
        panel = hub.engage_panel
        assert panel.isVisible()
        panel.eng_name.setText("NightWatch")
        panel.eng_auth.setText("ROE-42")
        panel.eng_scope.setText("10.0.0.*")
        panel.eng_operator.setText("N0CALL")
        panel._activate()
        _pump(40)
        assert engagement.is_active()
        assert recon.net_gated.target.isEnabled(), "RECON cards unlock when the engagement opens"
        hub.state.poll()
        assert hub.topbar.slots["engagement"].text() == "10.0.0.*"
        panel._deactivate()
        _pump(40)
        assert not engagement.is_active() and not recon.net_gated.target.isEnabled()
    finally:
        hub.close()
        _pump(150)


class _FakeMixer:
    def __init__(self, backend="pactl", volume=40, muted=False):
        self.backend, self.calls, self.volume, self.muted = backend, [], volume, muted

    def which(self, name):
        return "/usr/bin/" + name if name == self.backend else None

    def run(self, argv, timeout=2.0):
        self.calls.append(list(argv))
        if argv[:2] == ["pactl", "set-sink-volume"]:      # a real mixer changes state on a set
            self.volume = int(argv[-1].rstrip("%"))
        if argv[:2] == ["pactl", "set-sink-mute"]:
            self.muted = argv[-1] == "1"
        if argv[:2] == ["pactl", "get-sink-volume"]:
            return 0, "Volume: front-left: 26214 /  %d%% / -23.9 dB" % self.volume
        if argv[:2] == ["pactl", "get-sink-mute"]:
            return 0, "Mute: %s" % ("yes" if self.muted else "no")
        return 0, ""


def _wait_mixer(tb, timeout=5.0):
    """Mixer calls run off the GUI thread: pump until every queued call has reported back."""
    import time
    end = time.time() + timeout
    while tb.mixer is not None and tb.mixer.pending and time.time() < end:
        _pump(20)
    assert tb.mixer is None or not tb.mixer.pending, "mixer call never reported back"


def test_volume_slider_and_mute_drive_the_real_sink():
    """Section 9: the volume slider was connected to nothing; there was no mute."""
    _app()
    from palisade_qt.kit import TopBar
    from palisade_qt.kit.audio import AudioSink
    mixer = _FakeMixer(volume=40)
    tb = TopBar(audio=AudioSink(which=mixer.which, run=mixer.run))
    try:
        _wait_mixer(tb)
        assert tb.volume.isEnabled() and tb.volume.value() == 40, \
            "the slider starts at the sink's level"
        tb.volume.setValue(75)              # moved by the operator -> debounced set + read-back
        _pump(200)
        _wait_mixer(tb)
        assert ["pactl", "set-sink-volume", "@DEFAULT_SINK@", "75%"] in mixer.calls
        tb.mute.click()
        _wait_mixer(tb)
        assert ["pactl", "set-sink-mute", "@DEFAULT_SINK@", "1"] in mixer.calls
        assert tb.mute.isChecked()
        tb.toggle_mute()
        _wait_mixer(tb)
        assert ["pactl", "set-sink-mute", "@DEFAULT_SINK@", "0"] in mixer.calls
        assert not tb.mute.isChecked()
    finally:
        tb.stop()


@pytest.mark.parametrize("backend,vol_argv,mute_argv", [
    ("wpctl", ["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "0.50"],
     ["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "1"]),
    ("amixer", ["amixer", "-M", "sset", "Master", "50%"], ["amixer", "sset", "Master", "mute"]),
])
def test_audio_backends_build_argv_lists(backend, vol_argv, mute_argv):
    from palisade_qt.kit.audio import AudioSink
    sink = AudioSink(which=lambda n: "/usr/bin/" + n if n == backend else None,
                     run=lambda argv, timeout=2.0: (0, ""))
    assert sink.set_volume_argv(50) == vol_argv and sink.set_mute_argv(True) == mute_argv
    assert sink.set_volume_argv(250)[-1] in ("1.00", "100%"), "volume is clamped"


def test_no_audio_sink_disables_the_controls_instead_of_pretending():
    _app()
    from palisade_qt.kit import TopBar
    from palisade_qt.kit.audio import AudioSink
    sink = AudioSink(which=lambda n: None)
    assert not sink.available and sink.set_volume(50) is False
    tb = TopBar(audio=sink)
    assert not tb.volume.isEnabled() and not tb.mute.isEnabled()
    assert "NO AUDIO SINK" in tb.volume.toolTip()


def test_opsec_slot_is_reserved_as_a_placeholder():
    _app()
    from palisade_qt.kit import TopBar
    tb = TopBar()
    assert tb.opsec_slot is not None and "reserved" in tb.opsec_slot.toolTip().lower()


def test_plot_text_is_status_size():
    """D2: spectrum axis numbers and map / scope labels are readings, so they are 16 px too."""
    _app()
    from palisade_qt.kit import ScopePanel, MapPanel
    scope = ScopePanel(bins=64, history=8, lo_mhz=430, hi_mhz=440)
    for ax in ("left", "bottom"):
        assert scope.spectrum.getAxis(ax).style["tickFont"].pixelSize() >= 16
    m = MapPanel(span_nm=80, mode="dark")
    m.set_contacts([(1.0, 2.0)], labels=["N123"], colors=["#ffffff"])
    assert m._contact_labels and m._contact_labels[0].textItem.font().pixelSize() >= 16


def test_navigation_leaves_focus_on_the_page_not_on_a_nav_key():
    """Enter must run the page's primary action, not re-press whichever nav key had focus."""
    hub = _hub(demo=True)
    try:
        _key(hub, None, "4")
        _pump(300)
        assert not isinstance(QtWidgets.QApplication.focusWidget(), QtWidgets.QAbstractButton)
        _key(hub, QtCore.Qt.Key_Return)
        assert hub._current == "PROWL" and hub.page_app("PROWL").hold_btn.text() == "HOLD"
    finally:
        hub.close()
        _pump(150)


def test_maps_are_dark_or_satellite_only():
    """Owner rule (2026-11-15): every map is DARK or SAT, in every theme; no light / plain tiles."""
    _app()
    from palisade_qt.kit import mappanel
    assert set(mappanel.STYLES) == {"dark", "satellite"}
    for mode in ("dark", "light", "sun"):
        m = mappanel.MapPanel(mode=mode)
        assert m.current_style() == "dark"
        assert [m._combo.itemText(i) for i in range(m._combo.count())] == ["DARK", "SAT"]


def test_strip_has_no_text_under_16px_at_all():
    """Planner decision: on the 5" panel nothing in the strip may be under 16 px — not captions,
    not nav function words. (Tighter than D2's status-bearing rule.)"""
    hub = _hub()
    try:
        small = []
        for w in hub.topbar.findChildren(QtWidgets.QLabel):
            if not w.isVisible() or not w.text().strip():
                continue
            w.ensurePolished()
            f = w.font()
            px = f.pixelSize() if f.pixelSize() > 0 else f.pointSizeF() * w.logicalDpiY() / 72.0
            if px < 16 - 0.01:
                small.append((w.property("class"), w.text(), px))
        assert not small, small
    finally:
        hub.close()
        _pump(100)


def test_panic_chord_shift_esc_works_too(monkeypatch):
    """Planner decision: Shift+Esc is the primary PANIC chord (no Fn layer on the uConsole)."""
    import txguard
    hub = _hub()
    try:
        monkeypatch.setattr(hub, "_list_children", lambda: [])
        txguard.arm(True)
        assert txguard.is_armed()
        QTest.keyClick(hub, QtCore.Qt.Key_Escape, QtCore.Qt.ShiftModifier)
        _pump(40)
        assert not txguard.is_armed()
    finally:
        hub.close()
        _pump(100)
