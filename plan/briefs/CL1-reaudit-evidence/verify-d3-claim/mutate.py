import sys, pathlib
W = pathlib.Path(sys.argv[1])
def sub(p, a, b):
    t = p.read_text(); assert a in t, (p, a); p.write_text(t.replace(a, b))
# horiz
d = W/"horiz"/"palisade_qt"
sub(d/"kit/subtabs.py", "QSizePolicy.Fixed, QtWidgets.QSizePolicy.Expanding", "QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed")
sub(d/"kit/subtabs.py", "QVBoxLayout(self)", "QHBoxLayout(self)")
sub(d/"app.py", "            mid.addWidget(self._rail)\n", "            root.addWidget(self._rail)\n")
# focus
d = W/"focus"/"palisade_qt"
sub(d/"theme.py", "QPushButton:focus {{ border: {focus_w} solid {focus}; }}", "QPushButton:focus {{ border: {bw} solid {hairline}; }}")
sub(d/"theme.py", "QTableView:focus {{ border: {focus_w} solid {focus}; }}", "QTableView:focus {{ border: {bw} solid transparent; }}")
# checked
d = W/"checked"/"palisade_qt"
sub(d/"theme.py", "QPushButton:checked {{ background: {check_bg}; color: {check_fg}; border: {bw} solid {accent};\n                       font-weight: 600; }}", "QPushButton:checked {{ background: {p2}; color: {text}; border: {bw} solid {hairline}; }}")
# nofocus control
d = W/"nofocus"/"palisade_qt"
sub(d/"kit/subtabs.py", "QtCore.Qt.TabFocus", "QtCore.Qt.NoFocus")
