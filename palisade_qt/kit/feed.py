"""Feed table — a QTableView + model for decoder/contact feeds (the BABEL/ATLAS list)."""
from PySide6 import QtCore, QtGui, QtWidgets

from ..theme import ROW_H

COL_PAD = 22          # cell padding (QSS item padding 6 + 6) + room for the sort/edge


class FeedModel(QtCore.QAbstractTableModel):
    def __init__(self, columns, parent=None):
        super().__init__(parent)
        self.columns = columns          # list of (key, header)
        self.rows = []                  # list of dict

    def rowCount(self, _=QtCore.QModelIndex()):
        return len(self.rows)

    def columnCount(self, _=QtCore.QModelIndex()):
        return len(self.columns)

    def headerData(self, section, orient, role=QtCore.Qt.DisplayRole):
        if role == QtCore.Qt.DisplayRole and orient == QtCore.Qt.Horizontal:
            return self.columns[section][1]
        return None

    def data(self, idx, role=QtCore.Qt.DisplayRole):
        if not idx.isValid():
            return None
        row = self.rows[idx.row()]
        key = self.columns[idx.column()][0]
        if role == QtCore.Qt.DisplayRole:
            return str(row.get(key, ""))
        if role == QtCore.Qt.ForegroundRole:
            colors = row.get("_colors")
            if colors and key in colors:
                return QtGui.QColor(colors[key])
            return None
        if role == QtCore.Qt.TextAlignmentRole and idx.column() > 0:
            return int(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        return None

    def set_rows(self, rows):
        self.beginResetModel()
        self.rows = list(rows)
        self.endResetModel()

    def prepend(self, row, cap=500):
        self.beginInsertRows(QtCore.QModelIndex(), 0, 0)
        self.rows.insert(0, row)
        self.endInsertRows()
        if len(self.rows) > cap:
            self.beginRemoveRows(QtCore.QModelIndex(), cap, len(self.rows) - 1)
            del self.rows[cap:]
            self.endRemoveRows()


class FeedTable(QtWidgets.QFrame):
    selected = QtCore.Signal(dict)

    def __init__(self, columns, parent=None):
        super().__init__(parent)
        self.setProperty("class", "well")
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(1, 1, 1, 1)
        self.model = FeedModel(columns)
        self.view = QtWidgets.QTableView()
        self.view.setModel(self.model)
        self.view.setShowGrid(False)
        self.view.setAlternatingRowColors(True)
        self.view.verticalHeader().setVisible(False)
        self.view.verticalHeader().setDefaultSectionSize(ROW_H)
        self.view.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.view.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        hdr = self.view.horizontalHeader()
        hdr.setStretchLastSection(True)
        hdr.setMinimumSectionSize(70)
        # real column widths, measured from the header and the data at the table's own font:
        # ResizeToContents did not run for rows prepended while the table was hidden, so TIME / ID
        # / EVENT were elided to a few characters at 18 px (RA-CL1). Every column but the last
        # (which stretches) is as wide as its widest value; a wide table scrolls, it never elides.
        for i in range(len(columns) - 1):
            hdr.setSectionResizeMode(i, QtWidgets.QHeaderView.Interactive)
        self._fit = QtCore.QTimer(self)
        self._fit.setSingleShot(True)
        self._fit.setInterval(0)
        self._fit.timeout.connect(self.fit_columns)
        self.model.modelReset.connect(self._fit.start)
        self.model.rowsInserted.connect(lambda *_: self._fit.start())
        self.view.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.view.setWordWrap(False)
        self.view.setTabKeyNavigation(False)
        self.view.clicked.connect(self._clicked)
        # keyboard: the detail card must follow the cursor row, not only mouse clicks (D8)
        self.view.selectionModel().currentRowChanged.connect(self._row_changed)
        # a refresh resets the model; keep the cursor row so arrow-key navigation survives it
        self._keep_row = -1
        self.model.modelAboutToBeReset.connect(self._remember_row)
        self.model.modelReset.connect(self._restore_row)
        lay.addWidget(self.view)

    def fit_columns(self, sample=200):
        """Size every column but the last to its widest header / value (first `sample` rows)."""
        hdr = self.view.horizontalHeader()
        self.view.ensurePolished()
        hdr.ensurePolished()
        fm, hfm = self.view.fontMetrics(), hdr.fontMetrics()
        rows = self.model.rows[:sample]
        for i, (key, title) in enumerate(self.model.columns[:-1]):
            need = hfm.horizontalAdvance(title) + COL_PAD
            for r in rows:
                need = max(need, fm.horizontalAdvance(str(r.get(key, ""))) + COL_PAD)
            if hdr.sectionSize(i) < need:
                hdr.resizeSection(i, need)

    def showEvent(self, ev):
        super().showEvent(ev)
        self.fit_columns()

    def _remember_row(self):
        self._keep_row = self.view.currentIndex().row()

    def _restore_row(self):
        if 0 <= self._keep_row < len(self.model.rows):
            sm = self.view.selectionModel()
            sm.blockSignals(True)                  # restoring is not a new selection
            self.view.selectRow(self._keep_row)
            sm.blockSignals(False)

    def _row_changed(self, cur, _prev):
        if cur.isValid() and 0 <= cur.row() < len(self.model.rows):
            self.selected.emit(self.model.rows[cur.row()])

    def move_cursor(self, delta):
        """Move the row cursor by delta (keyboard up/down from anywhere on the page)."""
        n = len(self.model.rows)
        if not n:
            return False
        cur = self.view.currentIndex().row()
        row = 0 if cur < 0 else max(0, min(n - 1, cur + delta))
        self.view.setFocus()
        self.view.selectRow(row)
        return True

    def _clicked(self, idx):
        if 0 <= idx.row() < len(self.model.rows):
            self.selected.emit(self.model.rows[idx.row()])
