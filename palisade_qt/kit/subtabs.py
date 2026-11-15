"""SubTabRail — a page's sub-tabs as a vertical list at its left edge (D3).

Vertical, because the panel is 16:9: a horizontal sub-tab row costs ~50 px of the scarce height on
every page, while the same tabs down the side cost width the layout has to spare. The selected tab
has a visible checked state, every tab takes keyboard focus, and Left/Right step through them (D8).
"""
from PySide6 import QtCore, QtWidgets


class SubTabRail(QtWidgets.QFrame):
    selected = QtCore.Signal(str)

    def __init__(self, names, parent=None):
        super().__init__(parent)
        self.setObjectName("subtab_rail")
        self.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Expanding)
        self._lay = QtWidgets.QVBoxLayout(self)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._lay.setSpacing(6)
        self.buttons = {}
        self._current = None
        for n in names:
            b = QtWidgets.QPushButton(n)
            b.setProperty("class", "subtab")
            b.setCheckable(True)
            b.setAutoExclusive(False)
            b.setFocusPolicy(QtCore.Qt.TabFocus)
            b.clicked.connect(lambda _=False, nn=n: self.selected.emit(nn))
            self._lay.addWidget(b)
            self.buttons[n] = b
        self._lay.addStretch(1)

    def names(self):
        return list(self.buttons)

    def current(self):
        return self._current

    def set_current(self, name):
        self._current = name
        for n, b in self.buttons.items():
            b.setChecked(n == name)
