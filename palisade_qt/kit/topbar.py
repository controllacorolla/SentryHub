"""TopBar — the ONE chrome strip (≤ 40 px): numbered nav keys + shell-owned status slots.

Left: one key per page, callsign with its function label beside it (D7). Right: four fixed status
slots — MODE, RADIO, TX, ENGAGEMENT — each a word + a colour + a shape, drawn by the shell from engine
state (see chrome.py). A page can never write them: there is no set_chip here any more (D4/H7). Then
an alerts counter, the reserved OPSEC shield slot, mute + volume wired to the real audio sink, and
the Zulu clock.

Standalone page windows get the same strip without the nav keys.
"""
from PySide6 import QtCore, QtGui, QtWidgets

from .. import theme
from .audio import AudioSink

STRIP_H = 40


class ShapeGlyph(QtWidgets.QWidget):
    """A small painted shape, so state never rests on colour alone (and never on a font glyph).
    ring = off/none · dot = on/held · half = in progress · tri = caution · square = armed ·
    diamond = engagement · hatch = demo."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(12, 12)
        self._shape, self._color = "ring", "#888888"

    def set(self, shape, color):
        self._shape, self._color = shape, color
        self.update()

    def shape(self):
        return self._shape

    def paintEvent(self, ev):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        col = QtGui.QColor(self._color)
        pen = QtGui.QPen(col)
        pen.setWidthF(1.8)
        p.setPen(pen)
        p.scale(0.75, 0.75)                       # shapes are drawn on a 16 px grid
        r = QtCore.QRectF(2.5, 2.5, 11, 11)
        s = self._shape
        if s == "ring":
            p.drawEllipse(r)
        elif s == "dot":
            p.setBrush(col)
            p.drawEllipse(r)
        elif s == "half":
            p.drawEllipse(r)
            p.setBrush(col)
            p.drawPie(r, 90 * 16, 180 * 16)
        elif s == "tri":
            p.setBrush(col)
            p.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(8, 2), QtCore.QPointF(14.5, 14),
                                           QtCore.QPointF(1.5, 14)]))
        elif s == "square":
            p.setBrush(col)
            p.drawRect(r)
        elif s == "diamond":
            p.setBrush(col)
            p.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(8, 1.5), QtCore.QPointF(14.5, 8),
                                           QtCore.QPointF(8, 14.5), QtCore.QPointF(1.5, 8)]))
        elif s == "hatch":
            p.drawRect(r)
            p.setClipRect(r)
            for x in range(-12, 16, 4):
                p.drawLine(QtCore.QPointF(x, 14), QtCore.QPointF(x + 12, 2))
        p.end()


class StatusSlot(QtWidgets.QFrame):
    """One fixed status slot: caption + shape + word. Clickable / Enter-activatable."""
    clicked = QtCore.Signal()

    def __init__(self, caption, max_chars=10, parent=None):
        super().__init__(parent)
        self.setProperty("class", "slot")
        self.setFocusPolicy(QtCore.Qt.TabFocus)
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.caption = caption
        self._max = max_chars
        self._full = ""
        # one row: CAPTION glyph VALUE, every character at status size (16 px). A caption that
        # the value already implies (MODE: LIVE/DEMO, ALERTS: the triangle) is passed as "".
        row = QtWidgets.QHBoxLayout(self)
        row.setContentsMargins(5, 0, 4, 0)
        row.setSpacing(4)
        self.cap = QtWidgets.QLabel(caption)
        self.cap.setProperty("class", "slotcap")
        self.cap.setVisible(bool(caption))
        row.addWidget(self.cap)
        self.glyph = ShapeGlyph()
        row.addWidget(self.glyph)
        self.value = QtWidgets.QLabel("—")
        self.value.setProperty("class", "slotval")
        row.addWidget(self.value, 1)

    def set(self, word, shape, color, detail=""):
        """word is the state; detail (owner / scope) is appended and elided, full text in the tip."""
        self._full = "%s · %s" % (word, detail) if detail else word
        text = self._full
        if len(text) > self._max:
            text = text[:self._max - 1] + "…"
        self.value.setText(text)
        self.value.setStyleSheet("color:%s;" % color)
        self.glyph.set(shape, color)
        self.setToolTip("%s: %s" % (self.caption, self._full))

    def text(self):
        return self._full

    def mousePressEvent(self, ev):
        self.clicked.emit()

    def keyPressEvent(self, ev):
        if ev.key() in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter, QtCore.Qt.Key_Space):
            self.clicked.emit()
        else:
            super().keyPressEvent(ev)


class NavKey(QtWidgets.QPushButton):
    """A numbered page key: '<n> CALLSIGN' at status size. The function word lives in the
    tooltip, the key map (?) and the palette (/): on a 5" ~294 ppi panel an 11 px caption is
    under 1 mm tall, so the owner ruled out any strip text below 16 px (planner decision, CL1)."""

    def __init__(self, number, callsign, label, parent=None):
        super().__init__(parent)
        self.callsign = callsign
        self.setProperty("class", "navkey")
        self.setFocusPolicy(QtCore.Qt.TabFocus)
        self.setFixedHeight(STRIP_H - 4)
        v = QtWidgets.QVBoxLayout(self)
        v.setContentsMargins(2, 1, 2, 1)
        v.setSpacing(0)
        self.call = QtWidgets.QLabel("%d %s" % (number, callsign))
        self.call.setProperty("class", "navcall")
        self.call.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents)
        v.addStretch(1)
        v.addWidget(self.call)
        v.addStretch(1)
        self.function = label
        self.setToolTip("%d — %s: %s" % (number, callsign, label))
        self.setAccessibleName("%s %s" % (callsign, label))

    def sizeHint(self):
        return self.layout().sizeHint()

    def minimumSizeHint(self):
        return self.layout().sizeHint()

    def set_on(self, on):
        suffix = "_on" if on else ""
        self.setProperty("class", "navkey" + suffix)
        self.call.setProperty("class", "navcall" + suffix)
        for w in (self, self.call):
            w.style().unpolish(w)
            w.style().polish(w)


def _shield_pixmap(color):
    pm = QtGui.QPixmap(18, 18)
    pm.fill(QtCore.Qt.transparent)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    path = QtGui.QPainterPath()
    path.moveTo(9, 1.5)
    path.lineTo(15.5, 4.5)
    path.lineTo(15.5, 9)
    path.cubicTo(15.5, 13.5, 12, 16, 9, 16.8)
    path.cubicTo(6, 16, 2.5, 13.5, 2.5, 9)
    path.lineTo(2.5, 4.5)
    path.closeSubpath()
    pen = QtGui.QPen(QtGui.QColor(color))
    pen.setWidthF(1.6)
    pen.setStyle(QtCore.Qt.DashLine)
    p.setPen(pen)
    p.drawPath(path)
    p.end()
    return pm


class TopBar(QtWidgets.QFrame):
    nav_requested = QtCore.Signal(str)
    slot_clicked = QtCore.Signal(str)        # "mode" | "radio" | "tx" | "engagement" | "alerts"

    def __init__(self, mode="dark", nav=(), audio=None, parent=None):
        super().__init__(parent)
        self.setObjectName("top_bar")
        self.setFixedHeight(STRIP_H)
        self._tok = theme.tokens(mode)
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(2, 0, 3, 0)
        lay.setSpacing(2)

        self.nav_keys = {}
        for i, (callsign, label) in enumerate(nav, start=1):
            k = NavKey(i, callsign, label)
            k.clicked.connect(lambda _=False, c=callsign: self.nav_requested.emit(c))
            self.nav_keys[callsign] = k
            lay.addWidget(k)
        lay.addStretch(1)

        # the four fixed, shell-owned status slots
        self.slots = {}
        for key, cap, width in (("mode", "", 4), ("radio", "SDR", 8),
                                ("tx", "TX", 9), ("engagement", "ENG", 6)):
            s = StatusSlot(cap, max_chars=width)
            s.clicked.connect(lambda k=key: self.slot_clicked.emit(k))
            self.slots[key] = s
            lay.addWidget(s)
        self.alerts = StatusSlot("", max_chars=3)
        self.alerts.clicked.connect(lambda: self.slot_clicked.emit("alerts"))
        lay.addWidget(self.alerts)

        # reserved OPSEC shield slot — a placeholder until the OPSEC control lands (PR #16)
        self.opsec_slot = QtWidgets.QLabel()
        self.opsec_slot.setObjectName("opsec_slot")
        self.opsec_slot.setPixmap(_shield_pixmap(self._tok["disabled"]))
        self.opsec_slot.setToolTip("OPSEC — reserved (not installed in this build)")
        self.opsec_slot.setFixedWidth(20)
        lay.addWidget(self.opsec_slot)

        # audio: mute + volume, wired to the real sink; disabled (and saying why) when there is none
        self.audio = audio if audio is not None else AudioSink()
        self.mute = QtWidgets.QPushButton("♪")
        self.mute.setCheckable(True)
        self.mute.setFocusPolicy(QtCore.Qt.TabFocus)
        self.mute.setFixedHeight(STRIP_H - 10)
        self.mute.setStyleSheet("padding: 1px 4px;")
        self.mute.toggled.connect(self._on_mute)
        lay.addWidget(self.mute)
        self.volume = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.volume.setObjectName("vol")
        self.volume.setFixedWidth(40)
        self.volume.setRange(0, 100)
        self.volume.setFocusPolicy(QtCore.Qt.TabFocus)
        lay.addWidget(self.volume)
        self._vol_timer = QtCore.QTimer(self)        # debounce: one mixer call per drag pause
        self._vol_timer.setSingleShot(True)
        self._vol_timer.setInterval(120)
        self._vol_timer.timeout.connect(self._apply_volume)
        self._init_audio()
        self.volume.valueChanged.connect(lambda _v: self._vol_timer.start())

        self.clock = QtWidgets.QLabel("—")
        self.clock.setObjectName("dtg")
        lay.addWidget(self.clock)
        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(1000)
        self._tick()

        self.set_state("LIVE", ("FREE", ""), "OFF", ("NONE", "", ""))
        self.set_alerts(0)

    # ---- audio ----
    def _init_audio(self):
        if not self.audio.available:
            for w in (self.volume, self.mute):
                w.setEnabled(False)
                w.setToolTip("NO AUDIO SINK — wpctl / pactl / amixer not found on this host")
            self.volume.setValue(0)
            return
        vol, muted = self.audio.get()
        self.volume.setValue(vol if vol is not None else 0)
        self.volume.setToolTip("Volume — %s" % self.audio.backend)
        self.mute.setToolTip("Mute — %s" % self.audio.backend)
        if muted:
            self.mute.blockSignals(True)
            self.mute.setChecked(True)
            self.mute.blockSignals(False)

    def _apply_volume(self):
        if self.audio.available:
            self.audio.set_volume(self.volume.value())

    def _on_mute(self, muted):
        if self.audio.available:
            self.audio.set_mute(muted)

    def toggle_mute(self):
        if self.mute.isEnabled():
            self.mute.toggle()

    # ---- clock ----
    def _tick(self):
        self.clock.setText(QtCore.QDateTime.currentDateTimeUtc().toString("HHmm'Z'"))

    # ---- shell-owned state (only the shell calls these) ----
    def set_active_page(self, callsign):
        for name, key in self.nav_keys.items():
            key.set_on(name == callsign)

    def set_state(self, mode, radio, tx, engagement):
        t = self._tok
        if mode == "DEMO":
            self.slots["mode"].set("DEMO", "hatch", t["warn"])
        else:
            self.slots["mode"].set("LIVE", "dot", t["text"])
        word, owner = radio
        if word == "HELD":
            # the owner IS the state word (8 chars max: OWNER_LABELS); HELD is in the tooltip
            self.slots["radio"].set(owner or "HELD", "dot", t["accent"])
            self.slots["radio"].setToolTip("SDR: HELD by %s" % owner)
        elif word == "ACQUIRING":
            self.slots["radio"].set("ACQUIR…", "half", t["warn"])
            self.slots["radio"].setToolTip("SDR: ACQUIRING for %s" % owner)
        else:
            self.slots["radio"].set("FREE", "ring", t["muted"])
        if tx == "ARMED":
            self.slots["tx"].set("ARMED", "square", t["alert"])
        elif tx == "PERMITTED":
            self.slots["tx"].set("PERMITTED", "tri", t["warn"])
        else:
            self.slots["tx"].set("OFF", "ring", t["muted"])
        eword, scope = engagement[0], engagement[1]
        if eword == "ACTIVE":
            self.slots["engagement"].set("ACTIVE", "diamond", t["warn"])
            self.slots["engagement"].setToolTip("ENGAGEMENT: ACTIVE · %s" % scope)
        else:
            self.slots["engagement"].set("NONE", "ring", t["muted"])

    def set_alerts(self, unacked):
        t = self._tok
        if unacked:
            self.alerts.set("%d" % unacked if unacked < 100 else "99+", "tri", t["warn"])
            self.alerts.setToolTip("ALERTS: %d unacknowledged" % unacked)
        else:
            self.alerts.set("0", "ring", t["muted"])
