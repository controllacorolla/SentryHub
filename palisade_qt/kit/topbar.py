"""TopBar — the app-wide chrome strip: logo + wordmark + status chips + volume + DTG clock.

One bar for the whole window (lives in the shell; standalone windows get their own). Chips are
divider-separated text (not boxed), coloured by state: green=live/OK, amber=warn, red=alert,
muted otherwise. Exposes set_chip(key, text, state=, ok=) matching the old StatusHeader so pages
route their status here unchanged.
"""
from PySide6 import QtCore, QtGui, QtWidgets

from .logomark import LogoMark

_STATE = {"neutral": "hchip", "ok": "hchip hchip_live", "live": "hchip hchip_live",
          "warn": "hchip hchip_warn", "alert": "hchip hchip_alert", "accent": "hchip hchip_accent"}


class TopBar(QtWidgets.QFrame):
    def __init__(self, mode="dark", parent=None):
        super().__init__(parent)
        self.setObjectName("top_bar")
        self.setFixedHeight(44)
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(14, 0, 16, 0)
        lay.setSpacing(10)

        lay.addWidget(LogoMark(height=20, mode=mode))
        word = QtWidgets.QLabel("PALISADE")
        word.setObjectName("wordmark")
        lay.addWidget(word)
        lay.addSpacing(6)

        self.chips = {}
        for i, (key, text) in enumerate((("sdr", "SDR"), ("tx", "TX SAFE"),
                                         ("gps", "GPS"), ("pwr", "PWR"))):
            c = QtWidgets.QLabel(text)
            c.setProperty("class", "hchip hchip_live" if key == "tx" else "hchip")
            if i == 0:
                c.setStyleSheet("border-left: none;")
            self.chips[key] = c
            lay.addWidget(c)

        # OPSEC — one-button RF-dark. A shield toggle + state chip living in the app-wide top bar,
        # so the posture is operable AND visible on every page (not just OPS). Enforcement is in the
        # gates (txguard / engagement); this control only drives + reflects opsec's state.
        self._opsec_btn = QtWidgets.QToolButton()
        self._opsec_btn.setObjectName("opsec_toggle")
        self._opsec_btn.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
        self._opsec_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self._opsec_btn.setToolTip("OPSEC — one-button RF-dark. Arm to refuse every transmit path.")
        self._opsec_btn.clicked.connect(self._toggle_opsec)
        lay.addWidget(self._opsec_btn)
        try:
            import opsec
            opsec.subscribe(self._on_opsec_state)
        except Exception:
            pass
        self._refresh_opsec()

        lay.addStretch(1)

        vol = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        vol.setFixedWidth(84)
        vol.setRange(0, 100)
        vol.setValue(72)
        vol.setObjectName("vol")
        self.volume = vol
        lay.addWidget(vol)

        self.clock = QtWidgets.QLabel("—")
        self.clock.setObjectName("dtg")
        lay.addWidget(self.clock)
        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(1000)
        self._tick()

    def _tick(self):
        self.clock.setText(QtCore.QDateTime.currentDateTimeUtc().toString("HHmm'Z'"))

    # ---- OPSEC shield toggle (RF-dark posture) ----
    def _shield_icon(self, armed):
        """A small shield, painted so it renders identically in any font/theme: filled red with a
        warning mark when armed, muted outline when off."""
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
        if armed:
            p.fillPath(path, QtGui.QColor("#e5484d"))
            pen = QtGui.QPen(QtGui.QColor("#ffffff"))
            pen.setWidthF(1.6)
            p.setPen(pen)
            p.drawLine(9, 5, 9, 10)
            p.drawPoint(9, 12)
        else:
            pen = QtGui.QPen(QtGui.QColor("#8b94a3"))
            pen.setWidthF(1.6)
            p.setPen(pen)
            p.drawPath(path)
        p.end()
        return QtGui.QIcon(pm)

    def _operator(self):
        """Operator identity from opprofile for the arm/disarm record — best-effort, never invented."""
        try:
            import opprofile
            import suite
            prof = opprofile.load(suite.settings)
            return prof.get("callsign") or prof.get("name") or None
        except Exception:
            return None

    def _toggle_opsec(self):
        try:
            import opsec
            if opsec.is_armed():
                opsec.disarm(operator=self._operator())
            else:
                opsec.arm(operator=self._operator())
        except Exception:
            pass
        self._refresh_opsec()

    def _on_opsec_state(self, _state):
        try:
            self._refresh_opsec()
        except RuntimeError:
            # the top bar's C++ was deleted — actually drop the stale callback so it can't fire again
            try:
                import opsec
                opsec.unsubscribe(self._on_opsec_state)
            except Exception:
                pass

    def _refresh_opsec(self):
        try:
            import opsec
            armed = opsec.is_armed()
        except Exception:
            armed = False
        self._opsec_btn.setIcon(self._shield_icon(armed))
        self._opsec_btn.setText("OPSEC ARMED" if armed else "OPSEC OFF")
        if armed:
            self._opsec_btn.setStyleSheet(
                "#opsec_toggle{color:#fff;background:#b3261e;border:1px solid #e5484d;"
                "border-radius:4px;padding:1px 8px;font-weight:700;}")
        else:
            self._opsec_btn.setStyleSheet(
                "#opsec_toggle{color:#8b94a3;background:transparent;border:1px solid #39414f;"
                "border-radius:4px;padding:1px 8px;font-weight:600;}")

    def set_chip(self, key, text=None, state=None, ok=None):
        c = self.chips.get(key)
        if c is None:
            return
        if text is not None:
            c.setText(text)
        if state is None:
            state = "ok" if ok else "neutral"
        c.setProperty("class", _STATE.get(state, "hchip"))
        if key == "sdr":
            c.setStyleSheet("border-left: none;")
        c.style().unpolish(c)
        c.style().polish(c)
