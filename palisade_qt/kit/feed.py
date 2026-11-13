"""Feed table — a QTableView + model for decoder/contact feeds (the BABEL/ATLAS list)."""
from PySide6 import QtCore, QtGui, QtWidgets


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
        self.view.verticalHeader().setDefaultSectionSize(28)
        self.view.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.view.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        hdr = self.view.horizontalHeader()
        hdr.setStretchLastSection(True)
        hdr.setMinimumSectionSize(70)
        for i in range(len(columns) - 1):
            hdr.setSectionResizeMode(i, QtWidgets.QHeaderView.ResizeToContents)
        self.view.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.view.clicked.connect(self._clicked)
        lay.addWidget(self.view)

    def _clicked(self, idx):
        if 0 <= idx.row() < len(self.model.rows):
            self.selected.emit(self.model.rows[idx.row()])
