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
        if role in (QtCore.Qt.DisplayRole, QtCore.Qt.ToolTipRole):
            return str(row.get(key, ""))      # tooltip = the full value, even when the cell elides
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


def row_key(row, columns):
    """A row's identity across refreshes: its `_id` if the caller gave one, else its whole visible
    content (an unchanged row is the same item; a changed row without an id cannot be followed)."""
    if "_id" in row:
        return ("id", row["_id"])
    return ("content",) + tuple(str(row.get(k, "")) for k, _h in columns)


class FeedTable(QtWidgets.QFrame):
    selected = QtCore.Signal(dict)

    def __init__(self, columns, parent=None, fit_viewport=False):
        """fit_viewport: the columns always fit the visible width (no sideways scroll); a value too
        wide for its column elides with '…' and its full text is the cell's tooltip (CL1-fix2 N1).
        Without it a wide table scrolls sideways, never elides."""
        super().__init__(parent)
        self._fit_viewport = fit_viewport
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
        self.view.setTextElideMode(QtCore.Qt.ElideRight)
        if fit_viewport:
            self.view.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
            self.view.setHorizontalScrollMode(QtWidgets.QAbstractItemView.ScrollPerPixel)
            self.view.viewport().installEventFilter(self)
        self.view.setTabKeyNavigation(False)
        self.view.clicked.connect(self._clicked)
        # keyboard: the detail card must follow the cursor row, not only mouse clicks (D8)
        self.view.selectionModel().currentRowChanged.connect(self._row_changed)
        # a refresh resets the model; keep the cursor on the same ITEM (by row_key), not the same row
        # number: a re-sort or a new row would otherwise move the highlight to a different item while
        # the detail card still shows the old one (RA-CL1b N2)
        self._keep_key = None
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
        def need(key, title):
            n = hfm.horizontalAdvance(title) + COL_PAD
            for r in rows:
                n = max(n, fm.horizontalAdvance(str(r.get(key, ""))) + COL_PAD)
            return n
        if self._fit_viewport:
            self._fit_into_viewport([need(k, t) for k, t in self.model.columns])
            return
        for i, (key, title) in enumerate(self.model.columns[:-1]):
            n = need(key, title)
            if hdr.sectionSize(i) < n:
                hdr.resizeSection(i, n)

    def _fit_into_viewport(self, needs):
        """Every section is set explicitly so the sum is exactly the visible width: if all fit, the
        last column takes the slack; if not, the widest give way (down to the minimum) and their
        values elide with '…'. Nothing relies on stretch-last-section, which keeps a stale size."""
        hdr = self.view.horizontalHeader()
        hdr.setStretchLastSection(False)
        avail = self.view.viewport().width()
        lo = hdr.minimumSectionSize()
        widths = [max(lo, n) for n in needs]       # Qt enforces the minimum anyway
        while sum(widths) > avail and max(widths) > lo:
            i = widths.index(max(widths))
            widths[i] = max(lo, widths[i] - (sum(widths) - avail))
        if sum(widths) < avail:
            widths[-1] += avail - sum(widths)
        for i, w in enumerate(widths):
            hdr.resizeSection(i, w)

    def eventFilter(self, obj, ev):
        # the viewport narrows when the vertical scroll bar appears: refit, or the sum overflows
        if obj is self.view.viewport() and ev.type() == QtCore.QEvent.Resize:
            self._fit.start()
        return super().eventFilter(obj, ev)

    def showEvent(self, ev):
        super().showEvent(ev)
        self.fit_columns()

    def _remember_row(self):
        row = self.view.currentIndex().row()
        rows = self.model.rows
        self._keep_key = row_key(rows[row], self.model.columns) if 0 <= row < len(rows) else None

    def _restore_row(self):
        key, self._keep_key = self._keep_key, None
        if key is None:
            return
        cols = self.model.columns
        for i, r in enumerate(self.model.rows):
            if row_key(r, cols) == key:
                sm = self.view.selectionModel()
                sm.blockSignals(True)
                self.view.selectRow(i)
                sm.blockSignals(False)
                self.selected.emit(r)              # the detail follows the item's fresh data
                return
        # the item is gone: highlight nothing rather than whatever now sits in its row
        self.view.selectionModel().clearSelection()
        self.view.setCurrentIndex(QtCore.QModelIndex())

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
