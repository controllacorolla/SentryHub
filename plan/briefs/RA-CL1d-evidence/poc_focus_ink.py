"""RA-CL1d F1 attack: independent of the fix's text-rect maths. Ink = unfocused pixels that differ
from the key's dominant background colour. Report focus-changed pixels that are ink or touch ink
(8-neighbour), plus the gap between ink and the nearest changed row, per theme x live/demo x on/off x key."""
import os, sys, time, collections
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, sys.argv[1])
from PySide6 import QtCore, QtWidgets
app = QtWidgets.QApplication([])
from palisade_qt import theme
from palisade_qt.shell import PalisadeHub
from palisade_qt.ops import CALLSIGNS
def pump(ms):
    t = time.time()
    while time.time() - t < ms / 1000: app.processEvents(); time.sleep(0.005)
worst = 0
for mode in ("dark", "light", "sun"):
    for demo in (False, True):
        theme.load_fonts(); theme.set_app_font(app); app.setStyleSheet(theme.qss(mode))
        h = PalisadeHub(demo=demo, mode=mode); h.resize(1280, 720); h.show(); h.activateWindow(); pump(300)
        keys = h.topbar.nav_keys; names = [n for n, _ in CALLSIGNS]
        for on in (False, True):
            for name in names:
                k = keys[name]; other = keys[names[(names.index(name) + 1) % len(names)]]
                h.topbar.set_active_page(name if on else other.callsign)
                other.setFocus(); pump(30)
                r = QtCore.QRect(k.mapTo(h, QtCore.QPoint(0, 0)), k.size())
                a = h.grab(r).toImage(); k.setFocus(); pump(30); b = h.grab(r).toImage()
                if (mode, on, name) in (("sun", False, "SYSTEM"), ("sun", True, "SYSTEM"), ("dark", False, "SYSTEM")) and demo:
                    a.save("/tmp/ra-cl1d/key_%s_%s_%s_unf.png" % (mode, on, name)); b.save("/tmp/ra-cl1d/key_%s_%s_%s_foc.png" % (mode, on, name))
                W, H = a.width(), a.height()
                bg = collections.Counter(a.pixel(x, y) for y in range(H) for x in range(W)).most_common(1)[0][0]
                ink = {(x, y) for y in range(H) for x in range(W) if a.pixel(x, y) != bg}
                # border pixels of the unfocused key (outer bw ring) are not glyph ink
                bw = int(theme.tokens(mode)["bw"].rstrip("px"))
                if on and mode != "sun":   # on-key accent border is not glyph ink (sun: accent == fill)
                    ink = {(x, y) for (x, y) in ink if bw <= x < W - bw and bw <= y < H - bw}
                strict = len(ink & {(x, y) for y in range(H) for x in range(W) if a.pixel(x, y) != b.pixel(x, y)})
                ch = {(x, y) for y in range(H) for x in range(W) if a.pixel(x, y) != b.pixel(x, y)}
                hit = [p for p in ch if any((p[0]+dx, p[1]+dy) in ink for dx in (-1,0,1) for dy in (-1,0,1))]
                iy = sorted({y for _, y in ink}); cy = sorted({y for _, y in ch})
                gap_top = (iy[0] - max([y for y in cy if y < iy[0]], default=-99) - 1) if iy else None
                gap_bot = (min([y for y in cy if y > iy[-1]], default=999) - iy[-1] - 1) if iy else None
                worst = max(worst, strict)
                print("%-5s %-4s %-3s %-7s w=%d changed=%4d ink=%4d overpainted=%d ink_touched=%d gap_top=%s gap_bot=%s cue_rows=%s"
                      % (mode, "demo" if demo else "live", "on" if on else "off", name, W, len(ch), len(ink),
                         strict, len(hit), gap_top, gap_bot, cy[:3] + ["…"] + cy[-4:] if len(cy) > 7 else cy))
        h.close(); pump(150)
print("WORST overpainted =", worst)
