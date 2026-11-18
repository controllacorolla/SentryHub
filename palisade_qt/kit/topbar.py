"""TopBar — the ONE chrome strip (≤ 40 px) + the left rail of page keys + shell-owned status slots.

Left: one key per page, callsign with its function label beside it (D7). Right: four fixed status
slots — MODE, RADIO, TX, ENGAGEMENT — each a word + a colour + a shape, drawn by the shell from engine
state (see chrome.py). A page can never write them: there is no set_chip here any more (D4/H7). Then
an alerts counter, the NET mode slot (L3), mute + volume wired to the real audio sink, and the Zulu
clock. The MODE slot doubles as the fault indicator (C4): a caution triangle while the session log
holds faults the operator has not seen.

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
    """A page key: 'CALLSIGN' over its function label ('map', 'listen' …), its digit key in the
    tooltip only (no numbers on the key since 2026-11-18), both at
    status size (16 px) — owner decision D7, 2026-11-15: the function is visible beside every key.

    Two 16 px lines are 2 × 20 px line boxes, more than the key's 36 px. But the callsign line is
    caps and digits (no descender) and the label line is lower case, so the INK of both is about
    12 + 17 rows. The two lines are therefore placed by ink, overlapping only in empty line-box
    space, with a 2 px gap between the glyphs. Nothing is shrunk and nothing is clipped (the test
    compares painted pixels with the text drawn unclipped).

    N-ui1 (device, 2026-11-17): the ink is measured on REFERENCE strings (every caps letter and
    digit; every lower-case letter), not on each key's own text, so all keys share one callsign
    baseline and one label baseline ('map' and 'spectrum' sit on the same line), and each key has
    SIDE px of air left and right, so adjacent callsigns never run together ('4 PROWL5 RECON')."""
    GAP = 2            # px between the callsign's baseline ink and the label's tallest ascender
    SIDE = 5           # px left/right inside the key: the visible gap between two keys' text
    REF_CALL = "0123456789 ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    REF_LABEL = "abcdefghijklmnopqrstuvwxyz"

    def __init__(self, number, callsign, label, parent=None, height=STRIP_H - 4):
        super().__init__(parent)
        self.callsign = callsign
        self.setProperty("class", "navkey")
        self.setFocusPolicy(QtCore.Qt.TabFocus)
        self.setFixedHeight(height)
        # no number in the title (owner, device run 2026-11-18); the digit key still works and
        # the tooltip says which one
        self.call = QtWidgets.QLabel(callsign, self)
        self.call.setProperty("class", "navcall")
        self.label = QtWidgets.QLabel(label, self)
        self.label.setProperty("class", "navlabel")
        for w in (self.call, self.label):
            w.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents)
            w.setAlignment(QtCore.Qt.AlignHCenter | QtCore.Qt.AlignTop)
        self.function = label
        self._bases = (None, None)
        self.number = number
        self.setToolTip("%s — %s (key %d)" % (callsign, label, number))
        self.setAccessibleName("%s %s" % (callsign, label))

    def _ink(self, w, ref):
        """(top, bottom) of the painted pixels of the reference string relative to the baseline, at
        the label's polished font. The same for every key, so every key's baselines line up."""
        w.ensurePolished()
        r = w.fontMetrics().tightBoundingRect(ref)
        return r.top(), r.bottom()

    def baselines(self):
        """(callsign baseline, label baseline) in key coordinates — the row tests compare."""
        return self._bases

    def _text_w(self):
        return max(w.fontMetrics().horizontalAdvance(w.text()) for w in (self.call, self.label))

    def sizeHint(self):
        for w in (self.call, self.label):
            w.ensurePolished()
        return QtCore.QSize(self._text_w() + 2 * self.SIDE, self.height())

    def minimumSizeHint(self):
        return self.sizeHint()

    def _place(self):
        c_top, c_bot = self._ink(self.call, self.REF_CALL)
        l_top, l_bot = self._ink(self.label, self.REF_LABEL)
        ink_h = (c_bot - c_top + 1) + self.GAP + (l_bot - l_top + 1)
        y0 = (self.height() - ink_h) // 2              # top row of the callsign's ink
        fm_c, fm_l = self.call.fontMetrics(), self.label.fontMetrics()
        c_base = y0 - c_top                            # AlignTop: baseline = label top + ascent
        l_base = c_base + c_bot + 1 + self.GAP - l_top
        w = self.width() - 2 * self.SIDE
        self.call.setGeometry(self.SIDE, c_base - fm_c.ascent(), w, fm_c.height())
        self.label.setGeometry(self.SIDE, l_base - fm_l.ascent(), w, fm_l.height())
        self.label.raise_()
        self._bases = (c_base, l_base)

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


class NavRail(QtWidgets.QFrame):
    """The page keys, stacked down the left edge (owner decision 2026-11-17, device run: "I would
    rather have OPS, RECON etc. vertically stacked on the left side"). Replaces the keys across the
    top strip, which ran together at 1280 px. Same NavKey widgets, same digit shortcuts (1-9, rail order); each key is
    a tall, touch-sized target. F on a map page hides it with the page's side panels."""
    KEY_H = 48
    WIDTH = 128          # fits 'ASSISTANT' and a nested 'SKY DOME' at 16 px
    BOTTOM = 18          # px kept free under the last key, so nothing runs off the screen

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("nav_rail")
        self.setFixedWidth(self.WIDTH)
        self.lay = QtWidgets.QVBoxLayout(self)
        self.lay.setContentsMargins(6, 8, 6, self.BOTTOM)
        self.lay.setSpacing(6)
        self.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Ignored)

    def add_key(self, key):
        # owner 2026-11-18 ("why are you condensing the left side so much"): the keys are spread
        # evenly down the full height, a stretch between each, instead of packed at the top
        if getattr(self, "_keys", None):
            self.lay.addStretch(1)
        self.lay.addWidget(key)
        self._keys = getattr(self, "_keys", []) + [key]
        self.subs = getattr(self, "subs", {})

    def finish(self):
        pass

    def attach_sub(self, callsign, widget):
        """Nest a page's sub-tab list under its key (owner 2026-11-17: one navigation column
        instead of a page rail beside a sub-tab rail beside the content)."""
        if self.subs.get(callsign) is widget:
            return
        key = next(k for k in self._keys if k.callsign == callsign)
        widget.setParent(self)
        widget.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Maximum)
        widget.setProperty("nested", True)
        if widget.layout() is not None:
            widget.layout().setContentsMargins(8, 0, 0, 6)        # indented under its page key
            widget.layout().setSpacing(4)
        widget.setStyleSheet("QPushButton.subtab { padding: 4px 6px; min-height: 26px; }")
        self.lay.insertWidget(self.lay.indexOf(key) + 1, widget)
        self.subs[callsign] = widget


class TitleLabel(QtWidgets.QLabel):
    """The strip's "PALISADE · <page>" title. It asks for its full width but, when the status
    slots are at their widest (long radio owner, PERMITTED, a long scope, 99+ alerts), it gives way
    and elides ("PALISADE · ASSIS…") instead of pushing the window past 1280 px (Stage 1, the
    BAT slot and UTC caption joined the strip). text() is always the full title."""

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self._full = text

    def text(self):
        return self._full

    def set_full_text(self, text):
        self._full = text
        self.setToolTip("%s — click: what this page reports now" % text)
        self.updateGeometry()
        self._elide()

    def _pad(self):
        m = self.contentsMargins()
        return m.left() + m.right() + 6

    def sizeHint(self):
        h = super().sizeHint()
        return QtCore.QSize(self.fontMetrics().horizontalAdvance(self._full) + self._pad(),
                            h.height())

    def minimumSizeHint(self):
        h = super().minimumSizeHint()
        return QtCore.QSize(self.fontMetrics().horizontalAdvance("PALISADE ·…") + self._pad(),
                            h.height())

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._elide()

    def _elide(self):
        w = self.contentsRect().width() - 4
        QtWidgets.QLabel.setText(self, self.fontMetrics().elidedText(
            self._full, QtCore.Qt.ElideRight, max(10, w)))


class TopBar(QtWidgets.QFrame):
    nav_requested = QtCore.Signal(str)
    slot_clicked = QtCore.Signal(str)        # "mode" | "radio" | "tx" | "engagement" | "alerts" | "net"

    def __init__(self, mode="dark", nav=(), audio=None, parent=None):
        super().__init__(parent)
        self.setObjectName("top_bar")
        self.setFixedHeight(STRIP_H)
        self._tok = theme.tokens(mode)
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(2, 0, 6, 0)
        # slots are separated by space, not divider lines (2026-11-17); 9 px since the BAT slot and
        # the UTC caption joined the strip (2026-11-18) and the worst case must still fit 1280
        lay.setSpacing(9)

        # the page keys live in a vertical rail the shell puts down the left edge (NavRail); the
        # strip keeps only the wordmark and the shell-owned status. nav_keys keeps its name.
        self.nav_rail = NavRail() if nav else None
        self.nav_keys = {}
        for i, (callsign, label) in enumerate(nav, start=1):
            k = NavKey(i, callsign, label, height=NavRail.KEY_H)
            k.clicked.connect(lambda _=False, c=callsign: self.nav_requested.emit(c))
            self.nav_keys[callsign] = k
            self.nav_rail.add_key(k)
        if self.nav_rail is not None:
            self.nav_rail.finish()
        self.page_title = TitleLabel("PALISADE")
        self.page_title.setObjectName("strip_title")
        self.page_title.setContentsMargins(8, 0, 0, 0)
        # click the page name: a short notice lists what the page reports (the bottom status bar
        # is gone, owner 2026-11-18)
        self.page_title.setCursor(QtCore.Qt.PointingHandCursor)
        self.page_title.setToolTip("click: what this page reports now")
        self.page_title.mousePressEvent = lambda ev: self.slot_clicked.emit("page")
        lay.addWidget(self.page_title)
        lay.addStretch(1)

        # the four fixed, shell-owned status slots
        self.slots = {}
        for key, cap in (("mode", ""), ("radio", "SDR"), ("tx", "TX"), ("engagement", "ENG")):
            s = StatusSlot(cap)
            s.clicked.connect(lambda k=key: self.slot_clicked.emit(k))
            self.slots[key] = s
            lay.addWidget(s)
        self.alerts = StatusSlot("ALERTS")       # a bare "○ 0" read as nothing (2026-11-18)
        self.alerts.clicked.connect(lambda: self.slot_clicked.emit("alerts"))
        lay.addWidget(self.alerts)

        # NET (L3): the global network mode, OFFLINE / LAN / ONLINE, set from the session-log
        # panel. Takes the 20 px the reserved OPSEC placeholder held, plus SWEEP's key (hidden in
        # v0.1), so the worst-case strip still fits 1280 px.
        self.net = StatusSlot("NET")
        self.net.clicked.connect(lambda: self.slot_clicked.emit("net"))
        lay.addWidget(self.net)

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
        # 40 px gave almost no travel (owner, device run 2026-11-18): a real slider, 2 % steps
        self.volume.setFixedWidth(130)
        self.volume.setRange(0, 100)
        self.volume.setSingleStep(2)
        self.volume.setPageStep(10)
        self.volume.setFocusPolicy(QtCore.Qt.TabFocus)
        lay.addWidget(self.volume)
        self._vol_timer = QtCore.QTimer(self)        # debounce: one mixer call per drag pause
        self._vol_timer.setSingleShot(True)
        self._vol_timer.setInterval(120)
        self._vol_timer.timeout.connect(self._apply_volume)
        self._init_audio()
        self.volume.valueChanged.connect(self._volume_moved)

        # battery: one labelled place for it, in the strip (it was a bare "PWR 95%" in the OPS
        # footer and a POWER card; owner 2026-11-18 "power percentage in some random spot")
        self.battery = StatusSlot("BAT")
        self.battery.clicked.connect(lambda: self.slot_clicked.emit("battery"))
        lay.addWidget(self.battery)
        self.set_battery(None)

        # the clock is Zulu (UTC) time and says so ("I don't know what the 0221Z reads")
        self.clock_cap = QtWidgets.QLabel("UTC")
        self.clock_cap.setProperty("class", "slotcap")
        lay.addWidget(self.clock_cap)
        lay.addSpacing(-8)
        self.clock = QtWidgets.QLabel("—")
        self.clock.setObjectName("dtg")
        self.clock.setToolTip("UTC (Zulu) time, hours and minutes: 0221Z = 02:21 UTC")
        self.clock_cap.setToolTip(self.clock.toolTip())
        lay.addWidget(self.clock)
        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(1000)
        self._tick()

        self._faults = 0
        self.set_state("LIVE", ("FREE", ""), "OFF", ("NONE", "", ""))
        self.set_alerts(0)
        self.set_net("OFFLINE")

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
        key = self.nav_keys.get(callsign)
        self.page_title.set_full_text("PALISADE · %s" % callsign if key is not None
                                      else "PALISADE")

    def set_state(self, mode, radio, tx, engagement):
        self._last_state = (mode, radio, tx, engagement)
        t = self._tok
        self._mode_word = mode
        if self._faults:
            # C4: the fault indicator. The word stays LIVE/DEMO; the glyph turns to a caution
            # triangle in the alert colour until the operator opens the session log.
            self.slots["mode"].set(mode if mode == "DEMO" else "LIVE", "tri", t["alert"])
            self.slots["mode"].setToolTip("%s — %d unseen fault%s: open the session log" % (
                mode, self._faults, "" if self._faults == 1 else "s"))
        elif mode == "DEMO":
            self.slots["mode"].set("DEMO", "hatch", t["warn"])
        else:
            self.slots["mode"].set("LIVE", "dot", t["text"])
        word, owner = radio
        pres = getattr(self, "_sdr_presence", None)
        if word == "FREE" and pres in ("ABSENT", "BLOCKED"):
            # the SDR presence, which only the OPS footer used to show ("SDR PRESENT"), lives in
            # this one labelled slot now (owner 2026-11-18)
            self.slots["radio"].set(pres, "tri" if pres == "BLOCKED" else "ring",
                                    t["alert"] if pres == "BLOCKED" else t["warn"])
            self.slots["radio"].setToolTip("SDR: %s" % (self._sdr_presence_text or pres))
            word = None
        if word is None:
            pass
        elif word == "HELD":
            # the owner IS the state word (8 chars max: OWNER_LABELS); HELD is in the tooltip
            # owner request (device notes 2026-11-17): an SDR in use reads green ("on"), like
            # every other live/OK state in the theme; FREE stays a muted ring.
            self.slots["radio"].set(owner or "HELD", "dot", t["live"])
            self.slots["radio"].setToolTip("SDR: HELD by %s" % owner)
        elif word == "ACQUIRING":
            self.slots["radio"].set("ACQUIR…", "half", t["warn"])
            self.slots["radio"].setToolTip("SDR: ACQUIRING for %s" % owner)
        else:
            self.slots["radio"].set("FREE", "ring", t["muted"])
        if tx == "UNLOCKED":
            self.slots["tx"].set("UNLOCKED", "square", t["alert"])
        elif tx == "ARMED":
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
            # targets", diamond = active. "ACTIVE · <scope>" did not fit the strip, and the
            # scope is the part an operator needs to read (RA-CL1). Full detail: tooltip + panel.
            # Green, not amber: owner decision 2026-11-17 (device notes) — an open engagement is
            # the authorised "on" state; amber/red stay for EXPIRED/UNKNOWN and for TX.
            self.slots["engagement"].set(scope or "ACTIVE", "diamond", t["live"])
            self.slots["engagement"].setToolTip("ENGAGEMENT: ACTIVE · %s · scope %s" % (name, scope))
        elif eword == "EXPIRED":
            self.slots["engagement"].set("EXPIRED", "tri", t["alert"])
            self.slots["engagement"].setToolTip("ENGAGEMENT: EXPIRED · %s — END it and open a new one"
                                                % name)
        elif eword == "UNKNOWN":
            self.slots["engagement"].set("UNKNOWN", "unknown", t["warn"])
            self.slots["engagement"].setToolTip("ENGAGEMENT: UNKNOWN — the engagement state could "
                                                "not be read")
        else:
            self.slots["engagement"].set("NONE", "ring", t["muted"])

    def set_faults(self, n):
        """C4: unseen faults/errors in the session log (0 clears the indicator)."""
        self._faults = int(n or 0)
        st = getattr(self, "_last_state", None)
        if st is not None:
            self.set_state(*st)

    def set_net(self, mode):
        """L3: the network mode. OFFLINE is the safe state; LAN amber; ONLINE in the alert colour
        because the device is then talking to the internet."""
        t = self._tok
        if mode == "ONLINE":
            self.net.set("ON", "dot", t["alert"])
            self.net.setToolTip("NET: ONLINE — outbound requests to the internet are allowed")
        elif mode == "LAN":
            self.net.set("LAN", "half", t["warn"])
            self.net.setToolTip("NET: LAN — only this device and private addresses")
        else:
            self.net.set("OFF", "ring", t["muted"])
            self.net.setToolTip("NET: OFFLINE — nothing leaves the device")

    def set_sdr_presence(self, text):
        """OPS's SDR chip text ('SDR PRESENT' / 'SDR ABSENT' / 'SDR BLOCKED — dvb bound' / 'SDR ?' /
        'SDR HELD · x' / 'SDR DEMO'). Only ABSENT and BLOCKED change the slot; held/free come from
        the arbiter as before."""
        t = (text or "").upper()
        pres = "ABSENT" if "ABSENT" in t else "BLOCKED" if "BLOCKED" in t else None
        if (pres, text) == (getattr(self, "_sdr_presence", None),
                            getattr(self, "_sdr_presence_text", None)):
            return
        self._sdr_presence, self._sdr_presence_text = pres, text
        st = getattr(self, "_last_state", None)
        if st is not None:
            self.set_state(*st)

    def set_battery(self, pct):
        """The device battery, from the OPS telemetry. None = no battery sensor read."""
        t = self._tok
        if pct is None:
            self.battery.set("—", "unknown", t["muted"])
            self.battery.setToolTip("BATTERY: not read — no battery sensor found "
                                    "(/sys/class/power_supply)")
            return
        pct = max(0, min(100, int(pct)))
        if pct <= 10:
            self.battery.set("%d%%" % pct, "tri", t["alert"])
        elif pct <= 20:
            self.battery.set("%d%%" % pct, "half", t["warn"])
        else:
            self.battery.set("%d%%" % pct, "dot", t["text"])
        self.battery.setToolTip("BATTERY: %d%%" % pct)

    def set_alerts(self, unacked):
        t = self._tok
        if unacked:
            self.alerts.set("%d" % unacked if unacked < 100 else "99+", "tri", t["warn"])
            self.alerts.setToolTip("ALERTS: %d unacknowledged" % unacked)
        else:
            self.alerts.set("0", "ring", t["muted"])
