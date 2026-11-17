"""PALISADE Qt theme — DESIGN.md §4 depth tokens as a QSS stylesheet (light + dark).

Qt stylesheets have no CSS variables, so the tokens live in a dict per mode and the QSS is
formatted from them. Surfaces step bg -> p1 -> p2 (raised) and well (recessed); color carries
state only (violet accent, green = live/OK), chrome stays graphite monochrome.
"""
import os

from PySide6 import QtGui, QtWidgets

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Type scale (CL1 / D2), in physical pixels on the 1280x720 ~294 ppi panel. Nothing on screen is
# under 16 px — captions included (CL1-fix: 13 px captions were 1.1 mm on the 5" panel).
FONT_BODY = 18
FONT_STATUS = 16
FONT_CAPTION = 16
ROW_H = 40

DARK = {
    "bg": "#0C0F13", "p1": "#181C22", "p2": "#1F242B", "well": "#080A0D",
    "hairline": "#5A6472", "text": "#E6E9EE", "muted": "#9AA2AC",
    "accent": "#A492DA", "live": "#56D68E", "warn": "#E6B450", "alert": "#E06A6A",
    "cyan": "#4FC3D6",
    "highlight": "rgba(255,255,255,0.06)", "shadow": 0.55,
    "field": "#0E1115", "accent_dim": "rgba(164,146,218,0.15)",
    "row_alt": "rgba(255,255,255,0.035)", "row_hover": "rgba(255,255,255,0.06)",
    "focus": "#FFFFFF", "focus_w": "2px", "bw": "1px",
    "focus_on": "#FFFFFF", "focus_under": "2px",
    "check_bg": "rgba(164,146,218,0.22)", "check_fg": "#C9BCF2", "disabled": "#5F6772",
}
LIGHT = {
    "bg": "#E9EBEE", "p1": "#F5F6F8", "p2": "#FFFFFF", "well": "#DADDE2",
    "hairline": "#7A828C", "text": "#1B1E22", "muted": "#4A525C",
    "accent": "#5A4790", "live": "#1E7A48", "warn": "#7A5200", "alert": "#A8322C",
    "cyan": "#12697C",
    "highlight": "rgba(255,255,255,0.85)", "shadow": 0.18,
    "field": "#FFFFFF", "accent_dim": "rgba(90,71,144,0.12)",
    "row_alt": "rgba(0,0,0,0.04)", "row_hover": "rgba(0,0,0,0.07)",
    "focus": "#000000", "focus_w": "2px", "bw": "1px",
    "focus_on": "#000000", "focus_under": "2px",
    "check_bg": "rgba(90,71,144,0.18)", "check_fg": "#3B2C6B", "disabled": "#8A9099",
}
# SUN: direct-sunlight theme. Black and white only, nothing under 7:1, 2 px borders. Colour carries
# nothing here, so every state must also be a word and a shape (the status slots do both).
SUN = {
    "bg": "#FFFFFF", "p1": "#FFFFFF", "p2": "#FFFFFF", "well": "#FFFFFF",
    "hairline": "#000000", "text": "#000000", "muted": "#333333",
    "accent": "#000000", "live": "#000000", "warn": "#000000", "alert": "#000000",
    "cyan": "#000000",
    "highlight": "#000000", "shadow": 0.0,
    "field": "#FFFFFF", "accent_dim": "#D9D9D9",
    "row_alt": "#EEEEEE", "row_hover": "#DDDDDD",
    "focus": "#000000", "focus_w": "4px", "bw": "2px",
    "focus_on": "#FFFFFF", "focus_under": "3px",
    "check_bg": "#000000", "check_fg": "#FFFFFF", "disabled": "#595959",
}
MODES = {"dark": DARK, "light": LIGHT, "sun": SUN}
FONT_STACK = '"IBM Plex Mono", "DejaVu Sans Mono", monospace'

_QSS = """
* {{ font-family: {font}; color: {text}; font-size: {body}px; }}
QWidget {{ background: {bg}; color: {text}; }}
QWidget#root {{ background: {bg}; }}
QLabel {{ background: transparent; }}

/* raised surfaces */
QFrame.card   {{ background: {p1}; border: {bw} solid {hairline}; border-radius: 8px; }}
QFrame.card2  {{ background: {p2}; border: {bw} solid {hairline}; border-radius: 8px; }}
QFrame.well   {{ background: {well}; border: {bw} solid {hairline}; border-radius: 8px; }}

/* captions are static names, never state; anything that reports state is .note or larger */
QLabel.micro  {{ color: {muted}; font-size: {caption}px; font-weight: 400; letter-spacing: 1px; }}
QLabel.note   {{ color: {muted}; font-size: {status}px; }}
QLabel.hero   {{ color: {text}; font-size: 40px; font-weight: 600; letter-spacing: -1px; }}
QLabel.value  {{ color: {text}; font-size: 20px; font-weight: 600; }}
QLabel.live   {{ color: {live}; }}
QLabel.warn   {{ color: {warn}; }}
QLabel.alert  {{ color: {alert}; }}
QLabel.accent {{ color: {accent}; }}

QPushButton {{ background: {p2}; border: {bw} solid {hairline}; border-radius: 6px;
               padding: 5px 12px; color: {text}; font-size: {status}px; min-height: 26px; }}
QPushButton:hover {{ border-color: {accent}; }}
QPushButton:pressed {{ background: {p1}; }}
QPushButton:checked {{ background: {check_bg}; color: {check_fg}; border: {bw} solid {accent};
                       font-weight: 600; }}
QPushButton:focus {{ border: {focus_w} solid {focus}; }}
QPushButton:disabled {{ color: {disabled}; border: {bw} dashed {disabled}; background: transparent; }}
QPushButton.tile {{ background: {p1}; border-radius: 8px; padding: 10px; text-align: left; }}

QCheckBox {{ font-size: {status}px; spacing: 8px; }}
QCheckBox::indicator {{ width: 18px; height: 18px; border: {bw} solid {hairline};
                        border-radius: 3px; background: {field}; }}
QCheckBox::indicator:checked {{ background: {accent}; border-color: {accent}; }}
QCheckBox:focus {{ border: {focus_w} solid {focus}; border-radius: 4px; }}
QCheckBox:disabled {{ color: {disabled}; }}

/* input widgets */
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QAbstractSpinBox {{
    background: {field}; color: {text}; border: {bw} solid {hairline};
    border-radius: 6px; padding: 3px 8px; font-size: {status}px; min-height: 26px;
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QAbstractSpinBox:focus {{
    border: {focus_w} solid {focus};
}}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {{
    color: {disabled}; border: {bw} dashed {disabled};
}}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox::down-arrow {{ image: none; border-left: 5px solid transparent;
    border-right: 5px solid transparent; border-top: 6px solid {muted};
    margin-right: 6px; }}
QComboBox QAbstractItemView {{
    background: {p1}; color: {text}; border: {bw} solid {hairline};
    selection-background-color: {accent}; selection-color: {bg};
}}
QSpinBox::up-button, QDoubleSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::down-button {{
    background: {p2}; border: none; width: 18px;
}}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{
    border-left: 4px solid transparent; border-right: 4px solid transparent;
    border-bottom: 5px solid {muted}; width: 0; height: 0;
}}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{
    border-left: 4px solid transparent; border-right: 4px solid transparent;
    border-top: 5px solid {muted}; width: 0; height: 0;
}}

QPlainTextEdit {{ background: {well}; color: {text}; border: {bw} solid {hairline};
                  border-radius: 6px; font-size: {status}px; }}
QPlainTextEdit:focus {{ border: {focus_w} solid {focus}; }}

/* tables (the header's own font is set too, so its rendered size is measurable) */
QHeaderView {{ font-size: {status}px; }}
QHeaderView::section {{ background: {p1}; color: {muted}; border: none;
                        border-bottom: {bw} solid {hairline}; padding: 6px 8px;
                        font-size: {status}px; }}
QTableView {{ background: {well}; gridline-color: {hairline}; border: {bw} solid transparent;
              alternate-background-color: {row_alt}; font-size: {body}px;
              selection-background-color: {accent}; selection-color: {bg}; }}
QTableView:focus {{ border: {focus_w} solid {focus}; }}
QTableView::item {{ padding: 4px 6px; }}
QTableView::item:hover {{ background: {row_hover}; }}
QTableView::item:selected {{ background: {accent}; color: {bg}; }}

QScrollBar:vertical {{ background: {bg}; width: 10px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {hairline}; border-radius: 5px; min-height: 24px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}

QScrollBar:horizontal {{ background: {bg}; height: 10px; margin: 0; }}
QScrollBar::handle:horizontal {{ background: {hairline}; border-radius: 5px; min-width: 24px; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}

QToolTip {{ background: {p1}; color: {text}; border: {bw} solid {hairline};
            padding: 4px 8px; border-radius: 4px; font-size: {status}px; }}

QTabBar::tab {{ background: {p1}; color: {muted}; border: {bw} solid {hairline}; padding: 4px 12px;
                font-size: {status}px; }}
QTabBar::tab:selected {{ background: {check_bg}; color: {check_fg}; border-color: {accent}; }}
QTabWidget::pane {{ border: none; }}
QListWidget {{ background: {well}; border: {bw} solid {hairline}; border-radius: 6px;
               font-size: {body}px; }}
QListWidget::item:selected {{ background: {accent}; color: {bg}; }}

QProgressBar {{ background: {well}; border: {bw} solid {hairline}; border-radius: 4px; }}
QProgressBar::chunk {{ background: {accent}; border-radius: 3px; }}

/* ---- the one top strip: nav keys + shell-owned status slots ---- */
QFrame#top_bar {{ background: {p1}; border: none; border-bottom: {bw} solid {hairline}; }}
QFrame#nav_rail {{ background: {p1}; border: none; border-right: {bw} solid {hairline}; }}
QLabel#strip_title {{ color: {text}; font-size: {status}px; font-weight: 600; }}
QPushButton.navkey {{ background: transparent; border: {bw} solid transparent; border-radius: 5px;
                      padding: 0; min-height: 0; text-align: left; }}
QPushButton.navkey:hover {{ background: {row_hover}; }}
/* focus on a nav key: over- and underline only (RA-CL1c F1). Both text lines run edge to edge
   (SIDE = 1 px), so a side ring painted over the first/last glyph columns ('8 SYSTEM' read
   '3 SYSTEM' in SUN). The sides keep their unfocused width + colour; focus_under fits the ink-free
   rows under the label; corners are square (a rounded thick underline curls up into the edge
   glyphs); focus_on is the cue on the current page's filled key (SUN: white on black). No width. */
QPushButton.navkey:focus {{ border-style: solid; border-color: {focus} transparent;
                            border-width: {bw} {bw} {focus_under} {bw}; border-radius: 0; }}
QPushButton.navkey_on {{ background: {check_bg}; border: {bw} solid {accent}; border-radius: 0;
                         padding: 0; min-height: 0; text-align: left; }}
QPushButton.navkey_on:focus {{ border-style: solid solid double solid; border-color: {focus_on} {accent};
                               border-width: {bw} {bw} {focus_under} {bw}; border-radius: 0; }}
QLabel.navcall {{ color: {text}; font-size: {status}px; font-weight: 600; }}
QLabel.navcall_on {{ color: {check_fg}; font-size: {status}px; font-weight: 600; }}
QLabel.navlabel {{ color: {muted}; font-size: {status}px; }}
QLabel.navlabel_on {{ color: {check_fg}; font-size: {status}px; }}
QFrame.slot {{ background: transparent; border: none; }}  /* no dividers: spacing only (owner 2026-11-17) */
QFrame.slot:focus {{ border: {focus_w} solid {focus}; }}
QLabel.slotcap {{ color: {muted}; font-size: {status}px; letter-spacing: 1px; }}
QLabel.slotval {{ color: {text}; font-size: {status}px; font-weight: 600; }}
QLabel#dtg {{ color: {text}; font-size: {status}px; }}
QSlider#vol::groove:horizontal {{ height: 4px; background: {hairline}; border-radius: 2px; }}
QSlider#vol::handle:horizontal {{ width: 14px; height: 14px; margin: -6px 0;
                                  border-radius: 7px; background: {accent}; }}
QSlider#vol::sub-page:horizontal {{ background: {accent}; border-radius: 2px; }}
QSlider#vol:focus {{ border: {focus_w} solid {focus}; }}
QSlider#vol:disabled::handle:horizontal {{ background: {disabled}; }}

/* ---- vertical sub-tab rail at the page's left edge ---- */
QFrame#subtab_rail {{ background: transparent; border: none; }}
QPushButton.subtab {{ text-align: left; padding: 6px 10px; min-height: 28px; }}
QPushButton.subtab:focus {{ border: {focus_w} solid {focus}; }}

/* page-owned status row (pages may write this; they may never write the top strip) */
QFrame#page_status {{ background: transparent; border: none; border-top: {bw} solid {hairline}; }}
QLabel.pstat {{ color: {muted}; font-size: {status}px; }}
QLabel.pstat_live {{ color: {live}; font-size: {status}px; }}
QLabel.pstat_warn {{ color: {warn}; font-size: {status}px; }}
QLabel.pstat_alert {{ color: {alert}; font-size: {status}px; }}
QLabel.pstat_accent {{ color: {accent}; font-size: {status}px; }}

/* overlays: palette, key map, drawers, panels */
QFrame.overlay {{ background: {p1}; border: {focus_w} solid {accent}; border-radius: 8px; }}
QLabel.keycap {{ color: {text}; font-size: {status}px; font-weight: 600; border: {bw} solid {hairline};
                 border-radius: 4px; padding: 1px 7px; background: {p2}; }}
"""


def configure_scale(environ, setting=None):
    """Pin the UI scale before QApplication exists. The layout is designed in physical pixels for the
    uConsole's 1280x720 ~294 ppi panel, so the default is 1.0 with the desktop's automatic high-DPI
    scaling switched off (otherwise a 2x desktop setting would leave a 640x360 canvas). An operator
    who wants it larger sets PALISADE_UI_SCALE (or the saved 'ui_scale' setting). Returns the factor."""
    raw = environ.get("PALISADE_UI_SCALE") or setting
    try:
        factor = float(raw) if raw else 1.0
    except (TypeError, ValueError):
        factor = 1.0
    factor = min(3.0, max(0.5, factor))
    if "QT_SCALE_FACTOR" not in environ:
        environ["QT_ENABLE_HIGHDPI_SCALING"] = "0" if factor == 1.0 else "1"
        environ["QT_SCALE_FACTOR"] = "%g" % factor
    return factor


def contrast(fg, bg):
    """WCAG contrast ratio between two #RRGGBB colours."""
    def lum(c):
        c = c.lstrip("#")
        out = []
        for i in (0, 2, 4):
            v = int(c[i:i + 2], 16) / 255.0
            out.append(v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4)
        return 0.2126 * out[0] + 0.7152 * out[1] + 0.0722 * out[2]
    a, b = sorted((lum(fg), lum(bg)), reverse=True)
    return (a + 0.05) / (b + 0.05)


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
    font = QtGui.QFont("IBM Plex Mono")
    font.setPixelSize(FONT_BODY)
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
    return _QSS.format(font=FONT_STACK, body=FONT_BODY, status=FONT_STATUS, caption=FONT_CAPTION,
                       **{k: v for k, v in tok.items() if k not in ("shadow",)})


def tokens(mode="dark"):
    return MODES.get(mode, DARK)


def apply(widget, mode="dark"):
    """Style a widget tree and set a soft drop-shadow on every .card (QSS can't do box-shadow)."""
    widget.setObjectName("root")
    widget.setStyleSheet(qss(mode))
    strength = MODES.get(mode, DARK)["shadow"]
    if not strength:                    # SUN: flat, no shadows
        return widget
    for frame in widget.findChildren(QtWidgets.QFrame):
        if "card" in (frame.property("class") or ""):
            eff = QtWidgets.QGraphicsDropShadowEffect(frame)
            eff.setBlurRadius(24)
            eff.setXOffset(0)
            eff.setYOffset(6)
            eff.setColor(QtGui.QColor(0, 0, 0, int(255 * strength)))
            frame.setGraphicsEffect(eff)
    return widget
