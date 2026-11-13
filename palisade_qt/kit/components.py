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
    lbl = QtWidgets.QLabel(text.upper())
    lbl.setProperty("class", "micro")
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

    def set_chip(self, key, text=None, ok=None):
        c = self.chips.get(key)
        if c is None:
            return
        if text is not None:
            c.setText(text)
        c.setProperty("class", "chip chip_ok" if ok else "chip")
        c.style().unpolish(c)
        c.style().polish(c)


class ControlBar(QtWidgets.QFrame):
    """A row of labelled controls (tuner / gain / squelch …). Apps add fields; values are read
    back by name. Pure UI — the app wires them to its engine."""

    changed = QtCore.Signal(str, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setProperty("class", "card")
        self.setFixedHeight(54)
        self.lay = QtWidgets.QHBoxLayout(self)
        self.lay.setContentsMargins(12, 8, 12, 8)
        self.lay.setSpacing(14)
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
    """The selected-contact / detail panel: a hero numeral plus labelled key/value rows."""

    def __init__(self, title="DETAIL", parent=None):
        super().__init__(parent)
        self.setProperty("class", "card")
        self.lay = QtWidgets.QVBoxLayout(self)
        self.lay.setContentsMargins(14, 12, 14, 12)
        self.lay.setSpacing(6)
        self.lay.addWidget(micro(title))
        self.hero = QtWidgets.QLabel("—")
        self.hero.setProperty("class", "hero")
        self.lay.addWidget(self.hero)
        self.sub = QtWidgets.QLabel("")
        self.sub.setProperty("class", "micro")
        self.lay.addWidget(self.sub)
        self._rows = QtWidgets.QFormLayout()
        self._rows.setLabelAlignment(QtCore.Qt.AlignLeft)
        self._rows.setHorizontalSpacing(18)
        self._rows.setVerticalSpacing(4)
        self.lay.addLayout(self._rows)
        self.lay.addStretch(1)

    def set_hero(self, value, sub=""):
        self.hero.setText(str(value))
        self.sub.setText(sub.upper())

    def set_rows(self, pairs):
        while self._rows.rowCount():
            self._rows.removeRow(0)
        for k, v in pairs:
            key = micro(k)
            val = QtWidgets.QLabel(str(v))
            val.setProperty("class", "value")
            val.setStyleSheet("font-size:13px;")
            self._rows.addRow(key, val)


class EmptyState(QtWidgets.QFrame):
    """Shown when there's no signal / the hardware is absent — a first-class state, not a blank."""

    def __init__(self, text="NO SIGNAL", hint="", parent=None):
        super().__init__(parent)
        self.setProperty("class", "well")
        lay = QtWidgets.QVBoxLayout(self)
        lay.addStretch(1)
        big = QtWidgets.QLabel(text)
        big.setAlignment(QtCore.Qt.AlignCenter)
        big.setProperty("class", "micro")
        big.setStyleSheet("font-size:15px; letter-spacing:3px;")
        lay.addWidget(big)
        if hint:
            h = QtWidgets.QLabel(hint)
            h.setAlignment(QtCore.Qt.AlignCenter)
            h.setProperty("class", "micro")
            lay.addWidget(h)
        lay.addStretch(1)
