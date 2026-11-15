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
from .audio import AudioSink, AudioController

STRIP_H = 40


class ShapeGlyph(QtWidgets.QWidget):
    """A small painted shape, so state never rests on colour alone (and never on a font glyph).
    ring = off/none · dot = on/held · half = in progress · tri = caution · square = armed ·
    diamond = engagement · hatch = demo · unknown = dashed ring with a centre bar (cannot read)."""

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
        elif s == "unknown":
            pen.setStyle(QtCore.Qt.DashLine)
            p.setPen(pen)
            p.drawEllipse(r)
            p.setBrush(col)
            p.drawRect(QtCore.QRectF(6.5, 5, 3, 6))
        elif s == "hatch":
            p.drawRect(r)
            p.setClipRect(r)
            for x in range(-12, 16, 4):
                p.drawLine(QtCore.QPointF(x, 14), QtCore.QPointF(x + 12, 2))
        p.end()


class StatusSlot(QtWidgets.QFrame):
    """One fixed status slot: caption + shape + word. Clickable / Enter-activatable."""
    clicked = QtCore.Signal()

    def __init__(self, caption, parent=None):
        super().__init__(parent)
        self.setProperty("class", "slot")
        self.setFocusPolicy(QtCore.Qt.TabFocus)
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.caption = caption
        self._full = ""
        # one row: CAPTION glyph VALUE, every character at status size (16 px). A caption that
        # the value already implies (MODE: LIVE/DEMO, ALERTS: the triangle) is passed as "".
        row = QtWidgets.QHBoxLayout(self)
        row.setContentsMargins(4, 0, 3, 0)
        row.setSpacing(3)
        self.cap = QtWidgets.QLabel(caption)
        self.cap.setProperty("class", "slotcap")
        self.cap.setVisible(bool(caption))
        row.addWidget(self.cap)
        self.glyph = ShapeGlyph()
        row.addWidget(self.glyph)
        self.value = QtWidgets.QLabel("—")
        self.value.setProperty("class", "slotval")
        # never elided: the label is always as wide as its text (callers keep the text short —
        # OWNER_LABELS <= 8 chars, chrome.scope_summary). A cut-off owner or scope is the
        # RA-CL1 defect this replaces.
        self.value.setSizePolicy(QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Preferred)
        row.addWidget(self.value)

    def set(self, word, shape, color, detail=""):
        """word is the state; detail (owner / scope) follows it. The whole text is painted."""
        self._full = "%s · %s" % (word, detail) if detail else word
        self.value.setText(self._full)
        self.value.setStyleSheet("color:%s;" % color)
        self.glyph.set(shape, color)
        self.setToolTip("%s: %s" % (self.caption, self._full))
        self.value.updateGeometry()

    def text(self):
        return self._full

    def painted_text(self):
        """What is actually on screen: the label's text if it fits its width, else the part that
        fits. Tests assert on this, not on the stored string."""
        fm = self.value.fontMetrics()
        t = self.value.text()
        if fm.horizontalAdvance(t) <= self.value.width():
            return t
        return fm.elidedText(t, QtCore.Qt.ElideRight, self.value.width())

    def mousePressEvent(self, ev):
        self.clicked.emit()

    def keyPressEvent(self, ev):
        if ev.key() in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter, QtCore.Qt.Key_Space):
            self.clicked.emit()
        else:
            super().keyPressEvent(ev)


class NavKey(QtWidgets.QPushButton):
    """A numbered page key: '<n> CALLSIGN' over its function label ('map', 'listen' …), both at
    status size (16 px) — owner decision D7, 2026-11-15: the function is visible beside every key.

    Two 16 px lines are 2 × 20 px line boxes, more than the key's 36 px. But the callsign line is
    caps and digits (no descender) and the label line is lower case, so the INK of both is about
    12 + 17 rows. The two labels are therefore placed by their measured ink (tightBoundingRect),
    overlapping only in empty line-box space, with a 2 px gap between the glyphs. Nothing is shrunk
    and nothing is clipped (the test compares painted pixels with the text drawn unclipped)."""
    GAP = 2            # px between the callsign's baseline ink and the label's tallest ascender
    SIDE = 1           # px left/right inside the key

    def __init__(self, number, callsign, label, parent=None):
        super().__init__(parent)
        self.callsign = callsign
        self.setProperty("class", "navkey")
        self.setFocusPolicy(QtCore.Qt.TabFocus)
        self.setFixedHeight(STRIP_H - 4)
        self.call = QtWidgets.QLabel("%d %s" % (number, callsign), self)
        self.call.setProperty("class", "navcall")
        self.label = QtWidgets.QLabel(label, self)
        self.label.setProperty("class", "navlabel")
        for w in (self.call, self.label):
            w.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents)
            w.setAlignment(QtCore.Qt.AlignHCenter | QtCore.Qt.AlignTop)
        self.function = label
        self.setToolTip("%d — %s: %s" % (number, callsign, label))
        self.setAccessibleName("%s %s" % (callsign, label))

    def _ink(self, w):
        """(top, bottom) of the text's painted pixels relative to its baseline, at the polished font."""
        w.ensurePolished()
        r = w.fontMetrics().tightBoundingRect(w.text())
        return r.top(), r.bottom()

    def _text_w(self):
        return max(w.fontMetrics().horizontalAdvance(w.text()) for w in (self.call, self.label))

    def sizeHint(self):
        for w in (self.call, self.label):
            w.ensurePolished()
        return QtCore.QSize(self._text_w() + 2 * self.SIDE, STRIP_H - 4)

    def minimumSizeHint(self):
        return self.sizeHint()

    def _place(self):
        c_top, c_bot = self._ink(self.call)
        l_top, l_bot = self._ink(self.label)
        ink_h = (c_bot - c_top + 1) + self.GAP + (l_bot - l_top + 1)
        y0 = (self.height() - ink_h) // 2              # top row of the callsign's ink
        fm_c, fm_l = self.call.fontMetrics(), self.label.fontMetrics()
        c_base = y0 - c_top                            # AlignTop: baseline = label top + ascent
        l_base = c_base + c_bot + 1 + self.GAP - l_top
        w = self.width() - 2 * self.SIDE
        self.call.setGeometry(self.SIDE, c_base - fm_c.ascent(), w, fm_c.height())
        self.label.setGeometry(self.SIDE, l_base - fm_l.ascent(), w, fm_l.height())
        self.label.raise_()

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._place()

    def showEvent(self, ev):
        super().showEvent(ev)
        self._place()

    def set_on(self, on):
        suffix = "_on" if on else ""
        self.setProperty("class", "navkey" + suffix)
        self.call.setProperty("class", "navcall" + suffix)
        self.label.setProperty("class", "navlabel" + suffix)
        for w in (self, self.call, self.label):
            w.style().unpolish(w)
            w.style().polish(w)
        self._place()


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
        lay.setSpacing(1)

        self.nav_keys = {}
        for i, (callsign, label) in enumerate(nav, start=1):
            k = NavKey(i, callsign, label)
            k.clicked.connect(lambda _=False, c=callsign: self.nav_requested.emit(c))
            self.nav_keys[callsign] = k
            lay.addWidget(k)
        lay.addStretch(1)

        # the four fixed, shell-owned status slots
        self.slots = {}
        for key, cap in (("mode", ""), ("radio", "SDR"), ("tx", "TX"), ("engagement", "ENG")):
            s = StatusSlot(cap)
            s.clicked.connect(lambda k=key: self.slot_clicked.emit(k))
            self.slots[key] = s
            lay.addWidget(s)
        self.alerts = StatusSlot("")
        self.alerts.clicked.connect(lambda: self.slot_clicked.emit("alerts"))
        lay.addWidget(self.alerts)

        # reserved OPSEC shield slot — a placeholder until the OPSEC control lands (PR #16)
        self.opsec_slot = QtWidgets.QLabel()
        self.opsec_slot.setObjectName("opsec_slot")
        self.opsec_slot.setPixmap(_shield_pixmap(self._tok["disabled"]))
        self.opsec_slot.setToolTip("OPSEC — reserved (not installed in this build)")
        self.opsec_slot.setFixedWidth(20)
        lay.addWidget(self.opsec_slot)

        # audio: mute + volume, wired to the real sink; disabled (and saying why) when there is none.
        # Mixer calls run off the GUI thread and every set is read back: the controls show only
        # what the mixer confirmed, and a failing mixer shows a fault (RA-CL1 N5/N6/N7).
        self.audio = audio if audio is not None else AudioSink()
        self.mixer = AudioController(self.audio) if self.audio.available else None
        self._confirmed = {"volume": None, "muted": None}
        self.audio_fault = ""
        self.mute = QtWidgets.QPushButton("♪")
        self.mute.setCheckable(True)
        self.mute.setFocusPolicy(QtCore.Qt.TabFocus)
        self.mute.setFixedHeight(STRIP_H - 10)
        self.mute.setStyleSheet("padding: 1px 4px;")
        self.mute.clicked.connect(self._mute_clicked)
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
        self.volume.valueChanged.connect(self._volume_moved)

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
        if self.mixer is None:
            for w in (self.volume, self.mute):
                w.setEnabled(False)
                w.setToolTip("NO AUDIO SINK — wpctl / pactl / amixer not found on this host")
            self.volume.setValue(0)
            return
        self.mixer.state.connect(self._on_mixer)
        for w in (self.volume, self.mute):
            w.setEnabled(False)                       # nothing shown until the mixer answers
            w.setToolTip("reading %s …" % self.audio.backend)
        self.mixer.request("get")

    def _volume_moved(self, _v):
        if not self._syncing:
            self._vol_timer.start()

    _syncing = False

    def _apply_volume(self):
        if self.mixer is not None:
            self.mixer.request("volume", self.volume.value())

    def _mute_clicked(self, _checked=False):
        """The button never shows a state the mixer has not confirmed: it snaps back to the last
        read-back at once and shows MUTED only when the read-back after the set says so."""
        want = not bool(self._confirmed["muted"])
        self._show_audio()
        if self.mixer is not None:
            self.mute.setText("♪…")
            self.mixer.request("mute", want)

    def toggle_mute(self):
        if self.mute.isEnabled():
            self._mute_clicked()

    def _on_mixer(self, st):
        self.mixer.pending = max(0, self.mixer.pending - 1)
        if st["volume"] is not None or st["muted"] is not None:
            if st["volume"] is not None:
                self._confirmed["volume"] = st["volume"]
            if st["muted"] is not None:
                self._confirmed["muted"] = st["muted"]
        self.audio_fault = st["fault"]
        self._show_audio()

    def _show_audio(self):
        vol, muted = self._confirmed["volume"], self._confirmed["muted"]
        self._syncing = True
        self.volume.setValue(vol if vol is not None else 0)
        self._syncing = False
        self.volume.setEnabled(vol is not None)
        self.mute.setEnabled(True)
        self.mute.setChecked(muted is True)
        if self.audio_fault:
            self.mute.setText("♪!")
            self.mute.setStyleSheet("padding: 1px 4px; color:%s; border: %s solid %s;"
                                    % (self._tok["alert"], self._tok["focus_w"], self._tok["alert"]))
        else:
            self.mute.setText("♪?" if muted is None else "♪")
            self.mute.setStyleSheet("padding: 1px 4px;")
        state = ("MUTED" if muted else "on") if muted is not None else "UNKNOWN"
        tip = "Audio %s — %s" % (state, self.audio.backend)
        if vol is not None:
            tip += " · volume %d%%" % vol
        if self.audio_fault:
            tip = "MIXER FAULT: %s. Showing the last state the mixer confirmed. %s" % (
                self.audio_fault, tip)
        self.mute.setToolTip(tip)
        self.volume.setToolTip(tip if vol is not None else "volume UNKNOWN — " + tip)

    def audio_state(self):
        """What the strip claims about audio: (volume or None, muted or None, fault text)."""
        return self._confirmed["volume"], self._confirmed["muted"], self.audio_fault

    def stop(self):
        self._timer.stop()
        if self.mixer is not None:
            self.mixer.stop()

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
        elif tx == "UNKNOWN":
            self.slots["tx"].set("UNKNOWN", "unknown", t["warn"])
            self.slots["tx"].setToolTip("TX: UNKNOWN — txguard could not be read; treat as live")
        else:
            self.slots["tx"].set("OFF", "ring", t["muted"])
        eword, scope = engagement[0], engagement[1]
        name = engagement[2] if len(engagement) > 2 else ""
        if eword == "ACTIVE":
            # the scope IS the state word (as the owner is for SDR): "ENG ◆ 10.0.0.*" / "ENG ◆ 6
            # targets", amber diamond = active. "ACTIVE · <scope>" did not fit the strip, and the
            # scope is the part an operator needs to read (RA-CL1). Full detail: tooltip + panel.
            self.slots["engagement"].set(scope or "ACTIVE", "diamond", t["warn"])
            self.slots["engagement"].setToolTip("ENGAGEMENT: ACTIVE · %s · scope %s" % (name, scope))
        elif eword == "UNKNOWN":
            self.slots["engagement"].set("UNKNOWN", "unknown", t["warn"])
            self.slots["engagement"].setToolTip("ENGAGEMENT: UNKNOWN — the engagement state could "
                                                "not be read")
        else:
            self.slots["engagement"].set("NONE", "ring", t["muted"])

    def set_alerts(self, unacked):
        t = self._tok
        if unacked:
            self.alerts.set("%d" % unacked if unacked < 100 else "99+", "tri", t["warn"])
            self.alerts.setToolTip("ALERTS: %d unacknowledged" % unacked)
        else:
            self.alerts.set("0", "ring", t["muted"])
