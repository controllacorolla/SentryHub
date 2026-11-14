"""PALISADE logo mark — the fence/palisade silhouette with a violet centre post.

Drawn with QPainter (not the SVG) so it recolours cleanly to the theme: the fence bars take the
chrome colour, the centre post is always the violet accent. Geometry matches
plan/brand/palisade-mark.svg (viewBox 116x96).
"""
from PySide6 import QtCore, QtGui, QtWidgets

from .. import theme

# (x, y, w, h) in the 116x96 SVG space; last tuple is the violet post
_BARS = [(6, 66, 7, 28), (18, 54, 7, 40), (30, 40, 7, 54), (42, 26, 7, 68),
         (66, 26, 7, 68), (78, 40, 7, 54), (90, 54, 7, 40), (102, 66, 7, 28)]
_POST = (54, 12, 7, 82)
_VBW, _VBH = 116, 96


class LogoMark(QtWidgets.QWidget):
    def __init__(self, height=22, mode="dark", parent=None):
        super().__init__(parent)
        self._mode = mode
        self._h = height
        self.setFixedSize(int(height * _VBW / _VBH), height)

    def paintEvent(self, _ev):
        tok = theme.tokens(self._mode)
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing, True)
        sx = self.width() / _VBW
        sy = self.height() / _VBH
        p.setPen(QtCore.Qt.NoPen)
        bar = QtGui.QColor(tok["muted"])
        for x, y, w, h in _BARS:
            p.fillRect(QtCore.QRectF(x * sx, y * sy, w * sx, h * sy), bar)
        x, y, w, h = _POST
        p.fillRect(QtCore.QRectF(x * sx, y * sy, w * sx, h * sy), QtGui.QColor(tok["accent"]))
        p.end()
