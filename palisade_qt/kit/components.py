"""Static/QSS-styled kit components: status header, control bar, detail card, empty state,
plus small card helpers. The data-heavy ones (feed table, scope, map) live in sibling modules.
"""
from PySide6 import QtCore, QtWidgets


def _cls(w, name):
    w.setProperty("class", name)
    return w


def card(raised=1):
    f = QtWidgets.QFrame()
    f.setProperty("class", "card" if raised == 1 else "card2")
    return f


def micro(text):
    """A static caption (a name, never a state). Captions are the only text allowed under 16 px."""
    lbl = QtWidgets.QLabel(text.upper())
    lbl.setProperty("class", "micro")
    return lbl


def note(text=""):
    """A status-bearing line: 16 px, wraps. Use this (not micro) for anything that reports state."""
    lbl = QtWidgets.QLabel(text)
    lbl.setProperty("class", "note")
    lbl.setWordWrap(True)
    return lbl


class StatusHeader(QtWidgets.QFrame):
    """Top chrome: SDR / TX SAFE / GPS / PWR chips + a live DTG clock. Color carries state only."""

    def __init__(self, title="PALISADE", parent=None):
        super().__init__(parent)
        self.setProperty("class", "card2")
        self.setFixedHeight(46)
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(14, 6, 14, 6)
        lay.setSpacing(8)

        name = QtWidgets.QLabel(title)
        name.setProperty("class", "accent")
        name.setStyleSheet("font-weight:600; letter-spacing:2px;")
        lay.addWidget(name)
        lay.addSpacing(8)

        self.chips = {}
        for key, text in (("sdr", "SDR"), ("tx", "TX SAFE"), ("gps", "GPS"), ("pwr", "PWR")):
            c = QtWidgets.QLabel(text)
            c.setProperty("class", "chip chip_ok" if key == "tx" else "chip")
            self.chips[key] = c
            lay.addWidget(c)
        lay.addStretch(1)

        self.clock = QtWidgets.QLabel("—")
        self.clock.setProperty("class", "value")
        self.clock.setStyleSheet("font-size:14px;")
        lay.addWidget(self.clock)

        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(1000)
        self._tick()

    def _tick(self):
        self.clock.setText(QtCore.QDateTime.currentDateTimeUtc().toString("ddMMM HH:mm:ss'Z'").upper())

    # state -> QSS class. Green (ok/live) is reserved for genuine live/OK; violet (accent) is
    # identity/active; neutral is the default graphite; warn/alert for power & faults.
    _STATE = {"neutral": "chip", "ok": "chip chip_ok", "live": "chip chip_ok",
              "warn": "chip chip_warn", "alert": "chip chip_alert", "accent": "chip chip_accent"}

    def set_chip(self, key, text=None, state=None, ok=None):
        c = self.chips.get(key)
        if c is None:
            return
        if text is not None:
            c.setText(text)
        if state is None:
            state = "ok" if ok else "neutral"     # back-compat for ok=bool callers
        c.setProperty("class", self._STATE.get(state, "chip"))
        c.style().unpolish(c)
        c.style().polish(c)


class StatusLine(QtWidgets.QLabel):
    """A status-bearing line (RADIO BUSY / STANDBY …) that takes no space while it has nothing to
    say. 16 px, wraps."""

    def __init__(self, text="", parent=None):
        super().__init__(parent)
        self.setProperty("class", "note")
        self.setWordWrap(True)
        self.setText(text)

    def setText(self, text):
        super().setText(text)
        self.setVisible(bool(text))


class ControlBar(QtWidgets.QFrame):
    """A row of labelled controls (tuner / gain / squelch …). Apps add fields; values are read
    back by name. Pure UI — the app wires them to its engine."""

    changed = QtCore.Signal(str, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setProperty("class", "card")
        self.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Fixed)
        self.lay = QtWidgets.QHBoxLayout(self)
        self.lay.setContentsMargins(10, 6, 10, 6)
        self.lay.setSpacing(12)
        self.fields = {}

    def add_field(self, name, widget, label=None):
        box = QtWidgets.QVBoxLayout()
        box.setSpacing(1)
        box.addWidget(micro(label or name))
        box.addWidget(widget)
        self.lay.addLayout(box)
        self.fields[name] = widget
        return widget

    def add_button(self, text, slot):
        b = QtWidgets.QPushButton(text)
        b.clicked.connect(slot)
        self.lay.addWidget(b)
        return b

    def add_stretch(self):
        self.lay.addStretch(1)


class DetailCard(QtWidgets.QFrame):
    """The selected-contact / detail panel: a hero numeral plus labelled key/value rows. Every value
    wraps (a long value must never widen the window). With nothing to show, the drawn card shrinks
    to its title + hint at the top of its slot: no 200-600 px empty framed box (RA-CL1 / D10), and
    the page's other widgets do not move, because the card keeps the slot it was given."""

    def __init__(self, title="DETAIL", parent=None):
        super().__init__(parent)
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.box = QtWidgets.QFrame()              # the drawn card
        self.box.setProperty("class", "card")
        outer.addWidget(self.box)
        outer.addStretch(0)
        self._outer = outer
        self.lay = QtWidgets.QVBoxLayout(self.box)
        self.lay.setContentsMargins(12, 10, 12, 10)
        self.lay.setSpacing(4)
        self.lay.addWidget(micro(title))
        self.hero = QtWidgets.QLabel("—")
        self.hero.setProperty("class", "hero")
        self.hero.setWordWrap(True)
        self.hero.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Preferred)
        self.lay.addWidget(self.hero)
        self.sub = QtWidgets.QLabel("")
        self.sub.setProperty("class", "note")
        self.sub.setWordWrap(True)
        self.lay.addWidget(self.sub)
        self._rows = QtWidgets.QFormLayout()
        self._rows.setLabelAlignment(QtCore.Qt.AlignLeft)
        self._rows.setHorizontalSpacing(14)
        self._rows.setVerticalSpacing(3)
        self._rows.setRowWrapPolicy(QtWidgets.QFormLayout.WrapLongRows)
        self.lay.addLayout(self._rows)
        self.lay.addStretch(1)
        self._nrows = 0
        self._sync_collapsed()

    def is_empty(self):
        return self.hero.text().strip() in ("", "—") and self._nrows == 0

    def _sync_collapsed(self):
        # a dash is not information: never spend a 40 px hero line on it
        self.hero.setVisible(self.hero.text().strip() not in ("", "—"))
        self.sub.setVisible(bool(self.sub.text()))
        empty = self.is_empty()
        # empty: the box takes only its content height and the rest of the slot is page
        # background; otherwise the box fills the slot
        self.box.setSizePolicy(QtWidgets.QSizePolicy.Preferred,
                               QtWidgets.QSizePolicy.Maximum if empty
                               else QtWidgets.QSizePolicy.Preferred)
        self._outer.setStretch(0, 0 if empty else 1)
        self._outer.setStretch(1, 1 if empty else 0)

    def drawn_height(self):
        """Height of the drawn card (tests: an empty card must be short)."""
        return self.box.height()

    def set_hero(self, value, sub=""):
        self.hero.setText(str(value))
        self.sub.setText(sub.upper())
        self._sync_collapsed()

    def set_rows(self, pairs):
        while self._rows.rowCount():
            self._rows.removeRow(0)
        self._nrows = 0
        for k, v in pairs:
            key = micro(k)
            val = QtWidgets.QLabel(str(v))
            val.setProperty("class", "note")
            val.setWordWrap(True)
            val.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Preferred)
            val.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
            self._rows.addRow(key, val)
            self._nrows += 1
        self._sync_collapsed()


class EmptyState(QtWidgets.QFrame):
    """The one empty-state component (D4). A panel with no data says WHY, in one of three looks:

      OFFLINE  — hatched panel, amber: the reason and what to do ("NO DEVICE — plug in …").
      WATCHING — green: the feed runs and nothing is above baseline; sample count + last-sample age.
      STALE    — the last data is old: its age in red.

    `text`/`hint` keep the pre-CL4 call signature (a plain OFFLINE panel)."""
    LOOKS = ("offline", "watching", "stale")

    def __init__(self, text="NO SIGNAL", hint="", parent=None, state="offline"):
        super().__init__(parent)
        self.setProperty("class", "well")
        self.setObjectName("emptystate")
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.addStretch(1)
        self.big = QtWidgets.QLabel()
        self.big.setAlignment(QtCore.Qt.AlignCenter)
        self.big.setProperty("class", "value")
        self.big.setWordWrap(True)
        lay.addWidget(self.big)
        self.hint = QtWidgets.QLabel()
        self.hint.setAlignment(QtCore.Qt.AlignCenter)
        self.hint.setProperty("class", "note")
        self.hint.setWordWrap(True)
        lay.addWidget(self.hint)
        lay.addStretch(1)
        self.state = None
        self.set_state(state, text, hint)

    def set_state(self, state, title, detail=""):
        if state not in self.LOOKS:
            raise ValueError("EmptyState look must be one of %s" % (self.LOOKS,))
        self.state = state
        word = {"offline": "OFFLINE", "watching": "WATCHING", "stale": "STALE"}[state]
        t = title or word
        if not t.upper().startswith(word) and state != "offline":
            t = "%s — %s" % (word, t)
        self.big.setText(t)
        self.hint.setText(detail or "")
        self.hint.setVisible(bool(detail))
        tok = _tokens_for(self)
        col = {"offline": tok["warn"], "watching": tok["live"], "stale": tok["alert"]}[state]
        self.big.setStyleSheet("color:%s;" % col)
        self.hint.setStyleSheet("color:%s;" % (tok["alert"] if state == "stale" else tok["text"]))
        self.update()

    def text(self):
        return self.big.text() + ("\n" + self.hint.text() if self.hint.text() else "")

    def paintEvent(self, ev):
        super().paintEvent(ev)
        if self.state != "offline":
            return
        from PySide6 import QtGui
        tok = _tokens_for(self)
        c = QtGui.QColor(tok["warn"])
        c.setAlpha(60)
        p = QtGui.QPainter(self)
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(QtGui.QBrush(c, QtCore.Qt.BDiagPattern))
        p.drawRect(self.rect().adjusted(1, 1, -1, -1))
        pen = QtGui.QPen(QtGui.QColor(tok["warn"]))
        pen.setWidth(2)
        p.setPen(pen)
        p.setBrush(QtCore.Qt.NoBrush)
        p.drawRect(self.rect().adjusted(1, 1, -2, -2))
        p.end()


def _tokens_for(widget):
    """The theme tokens the app is drawn in (matched on the application palette's window colour)."""
    from .. import theme
    app = QtWidgets.QApplication.instance()
    if app is not None:
        bg = app.palette().color(app.palette().ColorRole.Window).name().lower()
        for mode, tok in theme.MODES.items():
            if tok["bg"].lower() == bg:
                return tok
    return theme.tokens("dark")

