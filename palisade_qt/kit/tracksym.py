"""Track symbols for the map and the OPS scope (owner 2026-11-17: "planes on map should look like
[a C2 track display], not dots").

Each contact is drawn as a heading-oriented glyph (aircraft = delta, vessel = hull, drone = quad
cross, station = square, operator = small cross, DF / balloon / unknown = ring), a velocity leader
along its heading (length = distance covered in LEADER_MIN minutes), a short history trail, and a
data-block label (callsign + flight level). A contact with no reported heading gets the ring and no
leader: the symbol never shows a direction the feed did not give.

Glyph paths are cached per (kind, 10-degree heading bucket), so a full redraw on the CM5 is one
ScatterPlotItem.setData plus two line items.
"""
import math

from PySide6 import QtCore, QtGui

LEADER_MIN = 2.0          # leader length: nm covered in this many minutes at the reported speed
LEADER_MAX_NM = 20.0
AIR_SIZE, OTHER_SIZE = 20, 16  # glyph size in px
TRAIL_LEN = 8             # positions kept per contact
HEADING_BUCKET = 10       # degrees

_CACHE = {}


def _poly(points):
    path = QtGui.QPainterPath()
    path.moveTo(*points[0])
    for p in points[1:]:
        path.lineTo(*p)
    path.closeSubpath()
    return path


def _base(kind):
    """The north-up glyph in pyqtgraph symbol space, which is screen space: a unit box, y DOWN,
    nose at -y (pinned by test_u10: the nose and the leader point along the course)."""
    if kind == "aircraft":
        return _poly([(0, -0.5), (0.42, 0.42), (0, 0.18), (-0.42, 0.42)])
    if kind == "helo":
        p = QtGui.QPainterPath()
        p.addEllipse(-0.2, -0.3, 0.4, 0.55)                  # body, nose at -y
        p.addRect(-0.5, -0.06, 1.0, 0.12)                    # rotor
        p.addRect(-0.04, 0.2, 0.08, 0.3)                     # tail boom
        return p
    if kind == "vessel":
        return _poly([(0, -0.5), (0.22, -0.18), (0.22, 0.45), (-0.22, 0.45), (-0.22, -0.18)])
    if kind == "drone":
        p = QtGui.QPainterPath()
        for dx, dy in ((-0.32, -0.32), (0.32, -0.32), (0.32, 0.32), (-0.32, 0.32)):
            p.addEllipse(dx - 0.14, dy - 0.14, 0.28, 0.28)
        p.addPolygon(QtGui.QPolygonF([QtCore.QPointF(0, -0.5), QtCore.QPointF(0.12, -0.2),
                                     QtCore.QPointF(-0.12, -0.2)]))
        p.addRect(-0.1, -0.1, 0.2, 0.2)
        return p
    if kind == "station":
        p = QtGui.QPainterPath()
        p.addRect(-0.36, -0.36, 0.72, 0.72)
        return p
    if kind == "operator":
        p = QtGui.QPainterPath()
        p.addRect(-0.5, -0.09, 1.0, 0.18)
        p.addRect(-0.09, -0.5, 0.18, 1.0)
        return p
    p = QtGui.QPainterPath()                     # DF, balloon, unknown heading: a ring
    p.addEllipse(-0.42, -0.42, 0.84, 0.84)
    p.addEllipse(-0.22, -0.22, 0.44, 0.44)
    return p


ORIENTED = ("aircraft", "helo", "vessel", "drone")


def heading(c):
    """The contact's reported course in degrees true, or None."""
    for k in ("track", "hdg", "heading", "course"):
        v = c.get(k)
        if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v):
            return float(v) % 360
    return None


def symbol(kind, hdg):
    """Cached glyph for a kind at a heading (None -> the no-heading ring for oriented kinds)."""
    if kind in ORIENTED and hdg is None:
        key = ("ring", None)
    else:
        b = None if kind not in ORIENTED else int(round(hdg / HEADING_BUCKET)) * HEADING_BUCKET % 360
        key = (kind if kind in ORIENTED or kind in ("station", "operator") else "ring", b)
        if kind not in ORIENTED:
            key = (key[0], None)
    p = _CACHE.get(key)
    if p is None:
        p = _base(key[0])
        if key[1]:
            p = QtGui.QTransform().rotate(key[1]).map(p)     # clockwise on screen = true course
        _CACHE[key] = p
    return p


def leader(c):
    """(x0, y0, x1, y1) in nm: the velocity leader, or None without a heading and a speed."""
    hdg, spd = heading(c), c.get("spd")
    if hdg is None or not isinstance(spd, (int, float)) or spd <= 0:
        return None
    d = min(LEADER_MAX_NM, spd / 60.0 * LEADER_MIN)
    r = math.radians(hdg)
    return (c["x"], c["y"], c["x"] + d * math.sin(r), c["y"] + d * math.cos(r))


def data_block(c):
    """'UAL123 FL120' for an aircraft with an altitude; the bare label otherwise."""
    label = str(c.get("label") or c.get("id") or "")
    alt = c.get("alt")
    if c.get("kind") == "aircraft" and isinstance(alt, (int, float)) and alt > 0:
        return "%s FL%03d" % (label, int(round(alt / 100.0)))
    return label


def push_trail(trails, cid, x, y):
    """Append a position to a contact's history (skips a repeat of the last point)."""
    t = trails.setdefault(cid, [])
    if not t or (abs(t[-1][0] - x) > 1e-6 or abs(t[-1][1] - y) > 1e-6):
        t.append((x, y))
        del t[:-TRAIL_LEN]
    return t


def segments(lines):
    """[(x0, y0, x1, y1), ...] -> xs, ys for a PlotDataItem with connect='pairs'."""
    xs, ys = [], []
    for x0, y0, x1, y1 in lines:
        xs += [x0, x1]
        ys += [y0, y1]
    return xs, ys


def trail_segments(trails, ids):
    out = []
    for cid in ids:
        t = trails.get(cid) or []
        out += [(a[0], a[1], b[0], b[1]) for a, b in zip(t, t[1:])]
    return out


# ---- colour by type (owner 2026-11-17: "type needs to be separated by colour: planes,
# helicopters, drones, military"). Fixed colours, not theme tokens: the map is satellite imagery in
# every theme. Every glyph also gets a dark outline, so it reads on DARK SAT and LIGHT SAT alike;
# and the SHAPE carries the type too, so it never rests on colour alone.
CLASS_COLOR = {
    "plane": "#5AB8FF", "helo": "#B388FF", "mil": "#FF8A3D", "drone": "#FF4FA3",
    "operator": "#FF4FA3", "vessel": "#4DE0C2", "station": "#FFE14D", "balloon": "#FFFFFF",
    "df": "#C8C8C8",
}
EMERGENCY = "#FF3B3B"           # an aircraft squawking 7500/7600/7700 (severity alert)
UNCONFIRMED = "#FFB000"         # Remote-ID on fewer than RID_CONFIRM_ADVERTS adverts (P3)
LEGEND = (("plane", "PLANE"), ("helo", "HELO"), ("mil", "MIL"), ("drone", "DRONE"),
          ("vessel", "SHIP"), ("station", "APRS"), ("balloon", "SONDE"), ("df", "DF"))


def is_military(c):
    if c.get("mil") is True:
        return True
    flags = c.get("dbflags")
    return isinstance(flags, int) and not isinstance(flags, bool) and bool(flags & 1)


def classify(c):
    """plane | helo | mil | drone | operator | vessel | station | balloon | df."""
    kind = c.get("kind")
    if kind == "aircraft":
        if is_military(c):
            return "mil"
        if str(c.get("category") or "").upper() == "A7":        # ADS-B emitter category: rotorcraft
            return "helo"
        return "plane"
    return kind if kind in CLASS_COLOR else "df"


def color(c):
    if c.get("trust") == "unconfirmed":
        return UNCONFIRMED
    if c.get("severity") == "alert" and c.get("kind") == "aircraft" and not is_military(c):
        return EMERGENCY
    return CLASS_COLOR[classify(c)]


def legend_html(per_row=4):
    items = ['<span style="color:%s; font-weight:600;">&#9632;</span>'
             '<span style="color:#DDD;">&nbsp;%s&nbsp;&nbsp;</span>' % (CLASS_COLOR[k], name)
             for k, name in LEGEND]
    rows = ["".join(items[i:i + per_row]) for i in range(0, len(items), per_row)]
    return "<br>".join(rows)


def glyph(c):
    """The contact's glyph: shape by type, rotated to its reported course."""
    cls = classify(c)
    g = "helo" if cls == "helo" else c.get("kind")
    return symbol(g, heading(c))
