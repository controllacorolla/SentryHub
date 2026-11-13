"""PALISADE Qt theme — DESIGN.md §4 depth tokens as a QSS stylesheet (light + dark).

Qt stylesheets have no CSS variables, so the tokens live in a dict per mode and the QSS is
formatted from them. Surfaces step bg -> p1 -> p2 (raised) and well (recessed); color carries
state only (violet accent, green = live/OK), chrome stays graphite monochrome.
"""
from PySide6 import QtGui, QtWidgets

# token name -> value, per mode. Keep names aligned with DESIGN §4 (--bg/--p1/--p2/--well …).
DARK = {
    "bg": "#0E1013", "p1": "#15181D", "p2": "#1C2026", "well": "#090B0E",
    "hairline": "#272B31", "text": "#E6E9EE", "muted": "#8A929C",
    "accent": "#A492DA", "live": "#56D68E", "warn": "#E6B450", "alert": "#E06A6A",
    "highlight": "rgba(255,255,255,0.05)", "shadow": 0.55,
}
LIGHT = {
    "bg": "#E9EBEE", "p1": "#F5F6F8", "p2": "#FFFFFF", "well": "#DADDE2",
    "hairline": "#CBD0D6", "text": "#1B1E22", "muted": "#5A626C",
    "accent": "#5A4790", "live": "#2E9E63", "warn": "#9A6B12", "alert": "#B5443E",
    "highlight": "rgba(255,255,255,0.85)", "shadow": 0.18,
}
MODES = {"dark": DARK, "light": LIGHT}
FONT_STACK = '"JetBrains Mono", "DejaVu Sans Mono", monospace'

_QSS = """
* {{ font-family: {font}; color: {text}; font-size: 13px; }}
QWidget#root {{ background: {bg}; }}
QLabel {{ background: transparent; }}

/* raised surfaces — a card is p1 with a hairline and a 1px top highlight */
QFrame.card   {{ background: {p1}; border: 1px solid {hairline}; border-radius: 10px;
                 border-top: 1px solid {highlight}; }}
QFrame.card2  {{ background: {p2}; border: 1px solid {hairline}; border-radius: 10px; }}
/* recessed well — scopes, tables, consoles sit in here */
QFrame.well   {{ background: {well}; border: 1px solid {hairline}; border-radius: 10px; }}

QLabel.micro  {{ color: {muted}; font-size: 10px; letter-spacing: 1px; }}
QLabel.hero   {{ color: {text}; font-size: 46px; font-weight: 600; }}
QLabel.value  {{ color: {text}; font-size: 20px; font-weight: 600; }}
QLabel.live   {{ color: {live}; }}
QLabel.warn   {{ color: {warn}; }}
QLabel.alert  {{ color: {alert}; }}
QLabel.accent {{ color: {accent}; }}

/* chip: status pill in the header */
QLabel.chip     {{ background: {p2}; border: 1px solid {hairline}; border-radius: 9px;
                   padding: 2px 9px; color: {muted}; font-size: 11px; }}
QLabel.chip_ok  {{ color: {live}; border-color: {live}; }}
QLabel.chip_tx  {{ color: {live}; border-color: {live}; }}

QPushButton {{ background: {p2}; border: 1px solid {hairline}; border-radius: 8px;
               padding: 6px 12px; color: {text}; }}
QPushButton:hover {{ border-color: {accent}; }}
QPushButton:pressed {{ background: {p1}; }}
QPushButton.tile {{ background: {p1}; border-radius: 10px; padding: 10px; text-align: left; }}
QPushButton.tile:hover {{ border-color: {accent}; }}

QHeaderView::section {{ background: {p1}; color: {muted}; border: none;
                        border-bottom: 1px solid {hairline}; padding: 4px 8px; font-size: 11px; }}
QTableView {{ background: {well}; gridline-color: {hairline}; border: none;
              selection-background-color: {accent}; selection-color: {bg}; }}
QScrollBar:vertical {{ background: {bg}; width: 8px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {hairline}; border-radius: 4px; min-height: 24px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
"""


def qss(mode="dark"):
    tok = MODES.get(mode, DARK)
    return _QSS.format(font=FONT_STACK, **{k: v for k, v in tok.items() if k != "shadow"})


def tokens(mode="dark"):
    return MODES.get(mode, DARK)


def apply(widget, mode="dark"):
    """Style a widget tree and set a soft drop-shadow on every .card (QSS can't do box-shadow)."""
    widget.setObjectName("root")
    widget.setStyleSheet(qss(mode))
    strength = MODES.get(mode, DARK)["shadow"]
    for frame in widget.findChildren(QtWidgets.QFrame):
        if "card" in (frame.property("class") or ""):
            eff = QtWidgets.QGraphicsDropShadowEffect(frame)
            eff.setBlurRadius(24)
            eff.setXOffset(0)
            eff.setYOffset(6)
            eff.setColor(QtGui.QColor(0, 0, 0, int(255 * strength)))
            frame.setGraphicsEffect(eff)
    return widget
