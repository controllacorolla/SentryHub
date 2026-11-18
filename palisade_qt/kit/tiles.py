"""Map tile fetcher + cache for ATLAS/OVERWATCH map backgrounds.

Fetches web map tiles (dark, light, satellite) in a background thread, caches them
locally under ~/.cache/palisade/tiles/ so the map works offline after first view.
Emits a stitched numpy array that the MapPanel renders as an ImageItem behind the
range rings and contacts.
"""
import math
import threading
from pathlib import Path
import os
from urllib.request import Request

import numpy as np
from PySide6 import QtCore, QtGui
from .seams import offscreen as _seam_offscreen

TILE_URLS = {
    "dark": "https://a.basemaps.cartocdn.com/dark_nolabels/{z}/{x}/{y}.png",
    "light": "https://a.basemaps.cartocdn.com/light_nolabels/{z}/{x}/{y}.png",
    "satellite": ("https://server.arcgisonline.com/ArcGIS/rest/services/"
                  "World_Imagery/MapServer/tile/{z}/{y}/{x}"),
}
# SAT: tried in order, per tile. Esri World Imagery first (it served "API KEY REQUIRED"
# placeholders to the device once, 2026-11-17, then recovered). Where a source has no tile or a
# blank one, the next is used: USGS National Map imagery (keyless, public domain, US only), then
# EOX Sentinel-2 cloudless (keyless, world, CC BY-NC-SA 4.0).
SAT_SOURCES = (
    ("esri", TILE_URLS["satellite"]),
    ("usgs", "https://basemap.nationalmap.gov/arcgis/rest/services/USGSImageryOnly/MapServer/"
             "tile/{z}/{y}/{x}"),
    ("eox", "https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless-2020_3857/default/"
            "GoogleMapsCompatible/{z}/{y}/{x}.jpg"),
)
TILE_SOURCES = {"dark": (("carto", TILE_URLS["dark"]),),
                "light": (("carto", TILE_URLS["light"]),),
                "satellite": SAT_SOURCES}
ATTRIBUTION = {"dark": "© OpenStreetMap contributors © CARTO",
               "satellite": "Imagery: Esri World Imagery · USGS The National Map · "
                            "Sentinel-2 cloudless by EOX (CC BY-NC-SA 4.0)"}
TILE_SIZE = 256
MAX_TILES = 48          # per view: a zoomed-out view drops a zoom level instead of fetching more
MIN_ZOOM, MAX_ZOOM = 3, 16
MARGIN = 0.25           # the resampled image covers the view plus this fraction on every side
OUT_SCALE = 1.0         # output pixels per screen pixel
MAX_OUT_PX = 2048
GREY_SPREAD, GREY_FRACTION = 4, 0.97     # _placeholder: pixels with R/G/B within 4 counts
CACHE_ROOT = Path.home() / ".cache" / "palisade" / "tiles"


def _tile_xy(lat, lon, zoom):
    n = 2 ** zoom
    x = int((lon + 180) / 360 * n)
    lat_r = math.radians(lat)
    y = int((1 - math.log(math.tan(lat_r) + 1 / math.cos(lat_r)) / math.pi) / 2 * n)
    return max(0, min(n - 1, x)), max(0, min(n - 1, y))


def _tile_bounds(tx, ty, zoom):
    n = 2 ** zoom
    w = tx / n * 360 - 180
    e = (tx + 1) / n * 360 - 180
    n_lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * ty / n))))
    s_lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (ty + 1) / n))))
    return n_lat, s_lat, w, e


def _pick_zoom(span_nm):
    deg_span = span_nm / 60 * 2
    for z in range(3, 16):
        tile_deg = 360 / (2 ** z)
        if deg_span / tile_deg >= 3:
            return z
    return 8


def _pick_zoom_view(deg_w, px_w):
    """The zoom whose tiles show about one tile pixel per screen pixel across deg_w degrees."""
    deg_w = max(1e-6, float(deg_w))
    z = round(math.log2(max(1e-9, 360.0 * max(64, px_w) / (TILE_SIZE * deg_w))))
    return max(MIN_ZOOM, min(MAX_ZOOM, int(z)))


EARTH_NM = 3440.065       # same sphere as eventbus.to_xy


def aeqd_inverse(home_lat, home_lon, x, y):
    """(lat, lon) for x east / y north nm from HOME in eventbus.to_xy's frame (azimuthal
    equidistant: true range and bearing from HOME). Numpy arrays or scalars. lon is unwrapped
    around home_lon (it may leave -180..180 across the antimeridian)."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    p1 = math.radians(home_lat)
    rho = np.hypot(x, y) / EARTH_NM
    az = np.arctan2(x, y)
    sin_lat = np.sin(p1) * np.cos(rho) + np.cos(p1) * np.sin(rho) * np.cos(az)
    lat = np.arcsin(np.clip(sin_lat, -1.0, 1.0))
    dl = np.arctan2(np.sin(az) * np.sin(rho) * np.cos(p1), np.cos(rho) - np.sin(p1) * sin_lat)
    return np.degrees(lat), home_lon + np.degrees(dl)


def _view_bbox(home_lat, home_lon, x0, x1, y0, y1):
    """North, south, west, east (degrees) of the ground under an nm rectangle of the AEQD frame."""
    gx, gy = np.meshgrid(np.linspace(x0, x1, 9), np.linspace(y0, y1, 9))
    lat, lon = aeqd_inverse(home_lat, home_lon, gx, gy)
    north = float(np.clip(lat.max(), -85.0, 85.0))
    south = float(np.clip(lat.min(), -85.0, 85.0))
    west = float(np.clip(lon.min(), -180.0, 179.999))
    east = float(np.clip(lon.max(), -180.0, 179.999))
    if x0 <= 0 <= x1 and y0 <= 0 <= y1:          # a view over a pole: every longitude
        if abs(home_lat) + math.degrees(max(abs(y0), abs(y1)) / EARTH_NM) >= 90:
            west, east = -180.0, 179.999
    return north, south, west, east


def tile_span(home_lat, home_lon, view, zoom=None):
    """The tile range covering a view. view = (x0, x1, y0, y1, px_w): nm east/north of HOME (the
    eventbus.to_xy frame) and the map's width in pixels. Returns (zoom, tx0, ty0, tx1, ty1) with a
    1-tile margin, at most MAX_TILES tiles. x is the tile column (west -> east), y the tile row
    (north -> south)."""
    x0, x1, y0, y1, px_w = view
    north, south, west, east = _view_bbox(home_lat, home_lon, x0, x1, y0, y1)
    z = _pick_zoom_view(east - west, px_w) if zoom is None else zoom
    while True:
        n = 2 ** z
        tx0, ty0 = _tile_xy(north, west, z)
        tx1, ty1 = _tile_xy(south, east, z)
        tx0, tx1 = sorted((tx0, tx1))
        ty0, ty1 = sorted((ty0, ty1))
        tx0, ty0 = max(0, tx0 - 1), max(0, ty0 - 1)
        tx1, ty1 = min(n - 1, tx1 + 1), min(n - 1, ty1 + 1)
        if (tx1 - tx0 + 1) * (ty1 - ty0 + 1) <= MAX_TILES or z <= MIN_ZOOM:
            return z, tx0, ty0, tx1, ty1
        z -= 1


def reproject(canvas, zoom, tx0, ty0, home_lat, home_lon, rect, out_w, out_h):
    """Resample a stitched Web-Mercator canvas (row 0 = north, tile (tx0, ty0) at its corner)
    onto an nm rectangle of the AEQD frame that contacts and range rings use (RA-UIP H1: the
    imagery was equirectangular, so with zoom a contact sat over the wrong ground). Returns an
    RGBA array, row 0 = NORTH; pixels with no tile under them are transparent."""
    x0, x1, y0, y1 = rect
    xs = x0 + (np.arange(out_w) + 0.5) / out_w * (x1 - x0)
    ys = y1 - (np.arange(out_h) + 0.5) / out_h * (y1 - y0)       # north first
    gx, gy = np.meshgrid(xs, ys)
    lat, lon = aeqd_inverse(home_lat, home_lon, gx, gy)
    lon = (lon + 180.0) % 360.0 - 180.0
    n = 2 ** zoom
    lat_r = np.radians(np.clip(lat, -85.05, 85.05))
    px = (lon + 180.0) / 360.0 * n * TILE_SIZE - tx0 * TILE_SIZE
    py = (1 - np.log(np.tan(lat_r) + 1 / np.cos(lat_r)) / math.pi) / 2 * n * TILE_SIZE \
        - ty0 * TILE_SIZE
    col = np.floor(px).astype(np.int64)
    row = np.floor(py).astype(np.int64)
    h, w = canvas.shape[:2]
    ok = (col >= 0) & (col < w) & (row >= 0) & (row < h)
    out = np.zeros((out_h, out_w, 4), dtype=np.uint8)
    out[ok] = canvas[row[ok], col[ok]]
    return out


def _blank(tile):
    """A tile with (almost) no detail: a source's 'no coverage here' answer. Try the next one."""
    rgb = tile[..., :3]
    return tile.size == 0 or float(rgb.std()) < 2.0 or int(tile[..., 3].max()) == 0


def _placeholder(tile):
    """A source's text-on-grey stand-in ("Map data not yet available", Esri's "API KEY REQUIRED"):
    almost every pixel is colourless. Imagery, even snow or desert, has colour in far more pixels.
    Such a tile is never shown and never kept in the cache (RA-UIP M1)."""
    rgb = tile[..., :3].astype(np.int16)
    spread = rgb.max(axis=-1) - rgb.min(axis=-1)
    return float((spread <= GREY_SPREAD).mean()) >= GREY_FRACTION


def imagery_state(why):
    """(state, text) for the map from a build's counts (see _fetch_one)."""
    n, shown = why.get("tiles", 0), why.get("shown", 0)
    if not n:
        return "none", ""
    if shown >= n:
        return "ok", ""
    if shown:
        if why.get("blocked"):
            return "partial", ("PART OF THE MAP HAS NO IMAGERY — NET is OFFLINE. Tap DOWNLOAD MAP "
                               "to fetch the rest of this area once")
        return "partial", "PART OF THE MAP HAS NO IMAGERY — some tiles failed to download"
    if why.get("blocked"):
        return "offline", ("NO SATELLITE IMAGERY — NET is OFFLINE. Tap DOWNLOAD MAP to fetch "
                           "this area once (NET stays OFFLINE), or turn NET on in the top strip")
    if why.get("failed"):
        return "failed", "NO SATELLITE IMAGERY — tile download failed: %s" % why.get("error", "?")
    return "failed", "NO SATELLITE IMAGERY — no imagery for this area"


def _netpolicy():
    import sys
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if root not in sys.path:
        sys.path.insert(0, root)
    import netpolicy
    if not getattr(netpolicy, "_tiles_grantable", False):
        # only the tile hosts may be reached by DOWNLOAD MAP (RA-S2 N4)
        hosts = {netpolicy._host_of(u) for u in TILE_URLS.values()}
        hosts |= {netpolicy._host_of(u) for srcs in TILE_SOURCES.values() for _n, u in srcs}
        netpolicy.allow_grant(hosts, "map tiles (operator download)")
        netpolicy._tiles_grantable = True
    return netpolicy


def _fetch_one(url_tpl, z, tx, ty, cache_dir, why=None, granted=False):
    """A tile's bytes from the cache, else the network, else None. why (a dict) counts the
    reasons a tile came back empty: 'blocked' (the NET mode refused it) or 'failed' (network
    error, bad answer). Device run 2026-11-18: with NET OFFLINE (the default) every fetch was
    refused and the map stayed blank with no word why."""
    path = cache_dir / ("%d_%d.png" % (tx, ty))
    if path.exists():
        return path.read_bytes()
    url = url_tpl.format(z=z, x=tx, y=ty)
    try:
        req = Request(url, headers={"User-Agent": "PALISADE/1.0"})
        data = _netpolicy().urlopen(req, timeout=8, granted=granted,
                                    purpose="map tiles (operator download)" if granted
                                    else "map tiles").read()
        path.write_bytes(data)
        return data
    except Exception as e:
        if why is not None:
            blocked = type(e).__name__ == "NetBlocked"
            k = "blocked" if blocked else "failed"
            why[k] = why.get(k, 0) + 1
            if not blocked:
                why.setdefault("error", " ".join(str(e).split())[:120])
        return None


def _qimg_to_rgb(data_bytes):
    img = QtGui.QImage()
    if not img.loadFromData(data_bytes):
        return None
    img = img.convertToFormat(QtGui.QImage.Format.Format_RGBA8888)
    w, h = img.width(), img.height()
    ptr = img.constBits()
    arr = np.frombuffer(ptr, dtype=np.uint8).reshape(h, w, 4).copy()
    return arr


class TileLayer(QtCore.QObject):
    """Fetches map tiles in a background thread, emits a stitched RGBA array + NM bounds."""

    # the stitched array, its nm rect, and the HOME it was built for: the receiver places it by
    # that HOME, since HOME can move between this emit and its queued delivery (RA-UIPd N2)
    ready = QtCore.Signal(object, float, float, float, float, object)
    # what the last build got: ("ok" | "partial" | "offline" | "failed" | "none", detail). The map
    # says it out loud instead of staying blank (device run 2026-11-18, "maps don't load")
    imagery = QtCore.Signal(str, str)

    def __init__(self, home_lat=47.6, home_lon=-122.3, span_nm=80, parent=None):
        super().__init__(parent)
        self.home_lat = home_lat
        self.home_lon = home_lon
        self.span_nm = span_nm
        self._lock = threading.Lock()
        self._busy = False
        self._pending = None
        self.view = None            # (x0, x1, y0, y1, px_w) in nm from HOME; None = +-span_nm

    def download(self, style):
        """The operator tapped DOWNLOAD MAP: fetch (and cache) this view's tiles once, even with
        NET OFFLINE. Each request is logged as granted (netpolicy.grant). The tiles then load from
        the cache offline; NET itself is not changed."""
        self._grant_next = True
        with self._lock:
            busy = self._busy
        if busy:
            self._pending = style
            return
        self.fetch(style)

    def fetch(self, style):
        # Never hit the network under the offscreen test platform or when asked to stay offline;
        # the map falls back to the scope (no tiles) style. Keeps the suite hermetic.
        if _seam_offscreen():
            return
        with self._lock:
            if self._busy:
                self._pending = style
                return
            self._busy = True
        t = threading.Thread(target=self._work, args=(style,), daemon=True)
        t.start()

    def _work(self, style):
        try:
            home = (self.home_lat, self.home_lon)
            self._why = {}
            self._granted = getattr(self, "_grant_next", False)
            self._grant_next = False
            arr, x0, y0, x1, y1 = self._build(style)
            self.imagery.emit(*imagery_state(self._why))
            # built for a HOME that has since moved (GPS follow): its nm rect is relative to the
            # old HOME, so drop it; the move queued a re-fetch (RA-UIP L3 / RA-UIPc M4)
            if arr is not None and (self.home_lat, self.home_lon) == home:
                self.ready.emit(arr, x0, y0, x1, y1, home)
        except Exception:
            pass
        finally:
            with self._lock:
                self._busy = False
                nxt = self._pending
                self._pending = None
            if nxt:
                self.fetch(nxt)

    def _build(self, style):
        sources = TILE_SOURCES.get(style)
        if not sources:
            return None, 0, 0, 0, 0
        span = self.span_nm
        view = self.view or (-span, span, -span, span, 800)
        zoom, tx0, ty0, tx1, ty1 = tile_span(self.home_lat, self.home_lon, view)

        nx = tx1 - tx0 + 1
        ny = ty1 - ty0 + 1
        canvas = np.zeros((ny * TILE_SIZE, nx * TILE_SIZE, 4), dtype=np.uint8)
        why = getattr(self, "_why", None)
        if why is None:
            why = self._why = {}
        why["tiles"] = nx * ny

        for tx in range(tx0, tx1 + 1):
            for ty in range(ty0, ty1 + 1):
                fallback = None
                for name, url_tpl in sources:
                    # per-source cache dir: an old cached placeholder (satellite/<z>/, before
                    # 2026-11-17) is never read again
                    cache_dir = CACHE_ROOT / style / name / str(zoom)
                    cache_dir.mkdir(parents=True, exist_ok=True)
                    data = _fetch_one(url_tpl, zoom, tx, ty, cache_dir, why,
                                      granted=getattr(self, "_granted", False))
                    tile = _qimg_to_rgb(data) if data is not None else None
                    if tile is None:
                        continue
                    if _placeholder(tile):      # never shown, and not kept: the next fetch retries
                        try:
                            (cache_dir / ("%d_%d.png" % (tx, ty))).unlink()
                        except OSError:
                            pass
                        continue
                    if _blank(tile):            # e.g. open sea, or no coverage: try the next,
                        fallback = fallback if fallback is not None else tile   # else keep it
                        continue
                    fallback = tile
                    break
                if fallback is not None:
                    why["shown"] = why.get("shown", 0) + 1
                    y_px = (ty - ty0) * TILE_SIZE
                    x_px = (tx - tx0) * TILE_SIZE
                    th, tw = fallback[:TILE_SIZE, :TILE_SIZE].shape[:2]
                    canvas[y_px:y_px + th, x_px:x_px + tw] = fallback[:TILE_SIZE, :TILE_SIZE]

        # one projection for imagery, rings and contacts (RA-UIP H1): resample the Mercator mosaic
        # onto the view (plus a margin, so a small pan shows imagery before the re-fetch lands)
        # in eventbus.to_xy's frame.
        x0, x1, y0, y1, px_w = view
        mx, my = (x1 - x0) * MARGIN, (y1 - y0) * MARGIN
        rect = (x0 - mx, x1 + mx, y0 - my, y1 + my)
        out_w = int(min(MAX_OUT_PX, max(256, px_w * OUT_SCALE * (1 + 2 * MARGIN))))
        out_h = int(min(MAX_OUT_PX, max(64, out_w * (rect[3] - rect[2]) / (rect[1] - rect[0]))))
        out = reproject(canvas, zoom, tx0, ty0, self.home_lat, self.home_lon, rect, out_w, out_h)
        # row 0 of `out` is the NORTH edge; the plot's y grows north, and the image item is
        # row-major with row 0 at the rect's bottom (y0 = south), so flip the rows once here.
        out = np.ascontiguousarray(out[::-1])
        return out, rect[0], rect[2], rect[1], rect[3]
