"""PALISADE Qt theme — DESIGN.md §4 depth tokens as a QSS stylesheet (light + dark).

Qt stylesheets have no CSS variables, so the tokens live in a dict per mode and the QSS is
formatted from them. Surfaces step bg -> p1 -> p2 (raised) and well (recessed); color carries
state only (violet accent, green = live/OK), chrome stays graphite monochrome.
"""
import os

from PySide6 import QtGui, QtWidgets

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DARK = {
    "bg": "#0C0F13", "p1": "#181C22", "p2": "#1F242B", "well": "#080A0D",
    "hairline": "#272B31", "text": "#E6E9EE", "muted": "#8A929C",
    "accent": "#A492DA", "live": "#56D68E", "warn": "#E6B450", "alert": "#E06A6A",
    "highlight": "rgba(255,255,255,0.06)", "shadow": 0.55,
    "field": "#0E1115", "accent_dim": "rgba(164,146,218,0.15)",
    "row_alt": "rgba(255,255,255,0.035)", "row_hover": "rgba(255,255,255,0.06)",
}
LIGHT = {
    "bg": "#E9EBEE", "p1": "#F5F6F8", "p2": "#FFFFFF", "well": "#DADDE2",
    "hairline": "#CBD0D6", "text": "#1B1E22", "muted": "#5A626C",
    "accent": "#5A4790", "live": "#2E9E63", "warn": "#9A6B12", "alert": "#B5443E",
    "highlight": "rgba(255,255,255,0.85)", "shadow": 0.18,
    "field": "#FFFFFF", "accent_dim": "rgba(90,71,144,0.12)",
    "row_alt": "rgba(0,0,0,0.04)", "row_hover": "rgba(0,0,0,0.07)",
}
MODES = {"dark": DARK, "light": LIGHT}
FONT_STACK = '"IBM Plex Mono", "DejaVu Sans Mono", monospace'

_QSS = """
* {{ font-family: {font}; color: {text}; font-size: 13px; }}
QWidget {{ background: {bg}; color: {text}; }}
QWidget#root {{ background: {bg}; }}
QLabel {{ background: transparent; }}

/* raised surfaces */
QFrame.card   {{ background: {p1}; border: 1px solid {hairline}; border-radius: 10px;
                 border-top: 1px solid {highlight}; }}
QFrame.card2  {{ background: {p2}; border: 1px solid {hairline}; border-radius: 10px; }}
QFrame.well   {{ background: {well}; border: 1px solid {hairline}; border-radius: 10px; }}

QLabel.micro  {{ color: {muted}; font-size: 10px; font-weight: 400; letter-spacing: 1px; }}
QLabel.hero   {{ color: {text}; font-size: 46px; font-weight: 600; letter-spacing: -1px; }}
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

/* input widgets */
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QAbstractSpinBox {{
    background: {field}; color: {text}; border: 1px solid {hairline};
    border-radius: 6px; padding: 4px 8px; font-size: 13px; min-height: 22px;
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QAbstractSpinBox:focus {{
    border-color: {accent};
}}
QComboBox::drop-down {{ border: none; width: 20px; }}
QComboBox::down-arrow {{ image: none; border-left: 4px solid transparent;
    border-right: 4px solid transparent; border-top: 5px solid {muted};
    margin-right: 6px; }}
QComboBox QAbstractItemView {{
    background: {p1}; color: {text}; border: 1px solid {hairline};
    selection-background-color: {accent}; selection-color: {bg};
}}
QSpinBox::up-button, QDoubleSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::down-button {{
    background: {p2}; border: none; width: 16px;
}}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{
    border-left: 4px solid transparent; border-right: 4px solid transparent;
    border-bottom: 4px solid {muted}; width: 0; height: 0;
}}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{
    border-left: 4px solid transparent; border-right: 4px solid transparent;
    border-top: 4px solid {muted}; width: 0; height: 0;
}}

QPlainTextEdit {{ background: transparent; color: {text}; border: none; }}

/* tables */
QHeaderView::section {{ background: {p1}; color: {muted}; border: none;
                        border-bottom: 1px solid {hairline}; padding: 6px 8px; font-size: 11px; }}
QTableView {{ background: {well}; gridline-color: {hairline}; border: none;
              alternate-background-color: {row_alt};
              selection-background-color: {accent}; selection-color: {bg}; }}
QTableView::item {{ padding: 4px 6px; min-height: 28px; }}
QTableView::item:hover {{ background: {row_hover}; }}
QTableView::item:selected {{ background: {accent}; color: {bg}; }}

QScrollBar:vertical {{ background: {bg}; width: 8px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {hairline}; border-radius: 4px; min-height: 24px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}

QScrollBar:horizontal {{ background: {bg}; height: 8px; margin: 0; }}
QScrollBar::handle:horizontal {{ background: {hairline}; border-radius: 4px; min-width: 24px; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}

QToolTip {{ background: {p1}; color: {text}; border: 1px solid {hairline};
            padding: 4px 8px; border-radius: 4px; font-size: 12px; }}

/* brand bar — thin accent line at the top of the main window */
QFrame#brand_bar {{ background: {accent}; min-height: 2px; max-height: 2px; border: none; }}

/* callsign rail */
QFrame#nav_rail {{ background: {p1}; border: none;
    border-right: 1px solid {hairline}; border-radius: 0; }}
QPushButton.nav_item {{ background: transparent; border: none; border-radius: 6px;
    padding: 4px 10px; color: {muted}; font-size: 11px; font-weight: 600;
    letter-spacing: 1px; text-align: left; min-height: 26px; }}
QPushButton.nav_item:hover {{ background: {row_hover}; color: {text}; }}
QPushButton.nav_active {{ background: {accent_dim}; border: none; border-radius: 6px;
    padding: 4px 10px; color: {accent}; font-size: 11px; font-weight: 600;
    letter-spacing: 1px; text-align: left; min-height: 26px;
    border-left: 2px solid {accent}; }}
"""


def load_fonts():
    """Load bundled IBM Plex fonts. Call once before creating any widgets."""
    fonts_dir = os.path.join(_HERE, "fonts")
    for name in ("IBMPlexMono-Regular.ttf", "IBMPlexMono-SemiBold.ttf",
                 "IBMPlexSans-Regular.ttf", "IBMPlexSans-SemiBold.ttf"):
        path = os.path.join(fonts_dir, name)
        if os.path.isfile(path):
            QtGui.QFontDatabase.addApplicationFont(path)


def set_app_font(app):
    """Set IBM Plex Mono as the application-wide font."""
    font = QtGui.QFont("IBM Plex Mono", 10)
    font.setStyleHint(QtGui.QFont.Monospace)
    app.setFont(font)


def set_palette(app, mode="dark"):
    """Set an application-wide QPalette so un-QSS'd containers inherit the right bg/fg."""
    tok = MODES.get(mode, DARK)
    pal = QtGui.QPalette()
    bg = QtGui.QColor(tok["bg"])
    text = QtGui.QColor(tok["text"])
    p1 = QtGui.QColor(tok["p1"])
    p2 = QtGui.QColor(tok["p2"])
    pal.setColor(QtGui.QPalette.Window, bg)
    pal.setColor(QtGui.QPalette.WindowText, text)
    pal.setColor(QtGui.QPalette.Base, bg)
    pal.setColor(QtGui.QPalette.AlternateBase, p1)
    pal.setColor(QtGui.QPalette.Text, text)
    pal.setColor(QtGui.QPalette.Button, p2)
    pal.setColor(QtGui.QPalette.ButtonText, text)
    pal.setColor(QtGui.QPalette.ToolTipBase, p1)
    pal.setColor(QtGui.QPalette.ToolTipText, text)
    pal.setColor(QtGui.QPalette.PlaceholderText, QtGui.QColor(tok["muted"]))
    pal.setColor(QtGui.QPalette.Highlight, QtGui.QColor(tok["accent"]))
    pal.setColor(QtGui.QPalette.HighlightedText, bg)
    app.setPalette(pal)


def qss(mode="dark"):
    tok = MODES.get(mode, DARK)
    return _QSS.format(font=FONT_STACK, **{k: v for k, v in tok.items()
                                            if k not in ("shadow",)})


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
