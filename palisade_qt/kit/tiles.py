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


def _nm_from_home(home_lat, home_lon, lat, lon):
    dy = (lat - home_lat) * 60
    dx = (lon - home_lon) * 60 * math.cos(math.radians(home_lat))
    return dx, dy


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


def tile_span(home_lat, home_lon, view, zoom=None):
    """The tile range covering a view. view = (x0, x1, y0, y1, px_w): nm east/north of HOME and
    the map's width in pixels. Returns (zoom, tx0, ty0, tx1, ty1) with a 1-tile margin, at most
    MAX_TILES tiles. x is the tile column (west -> east), y the tile row (north -> south)."""
    x0, x1, y0, y1, px_w = view
    cos_lat = max(0.05, math.cos(math.radians(home_lat)))
    north = max(-85.0, min(85.0, home_lat + y1 / 60.0))
    south = max(-85.0, min(85.0, home_lat + y0 / 60.0))
    west = max(-180.0, min(179.999, home_lon + x0 / (60.0 * cos_lat)))
    east = max(-180.0, min(179.999, home_lon + x1 / (60.0 * cos_lat)))
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


def _mercator_rows(n_lat, s_lat, ty0, zoom, height):
    """For each output row (north first, evenly spaced in latitude) the canvas row to copy."""
    top = ty0 * TILE_SIZE
    lats = n_lat - (np.arange(height) + 0.5) / height * (n_lat - s_lat)
    lat_r = np.radians(np.clip(lats, -85.05, 85.05))
    y = (1 - np.log(np.tan(lat_r) + 1 / np.cos(lat_r)) / math.pi) / 2 * (2 ** zoom) * TILE_SIZE
    return np.clip(np.floor(y - top).astype(int), 0, height - 1)


def _blank(tile):
    """A tile with (almost) no detail: a source's 'no coverage here' answer. Try the next one."""
    rgb = tile[..., :3]
    return tile.size == 0 or float(rgb.std()) < 2.0 or int(tile[..., 3].max()) == 0


def _netpolicy():
    import sys
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if root not in sys.path:
        sys.path.insert(0, root)
    import netpolicy
    return netpolicy


def _fetch_one(url_tpl, z, tx, ty, cache_dir):
    path = cache_dir / ("%d_%d.png" % (tx, ty))
    if path.exists():
        return path.read_bytes()
    url = url_tpl.format(z=z, x=tx, y=ty)
    try:
        req = Request(url, headers={"User-Agent": "PALISADE/1.0"})
        data = _netpolicy().urlopen(req, timeout=8, purpose="map tiles").read()
        path.write_bytes(data)
        return data
    except Exception:
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

    ready = QtCore.Signal(object, float, float, float, float)

    def __init__(self, home_lat=47.6, home_lon=-122.3, span_nm=80, parent=None):
        super().__init__(parent)
        self.home_lat = home_lat
        self.home_lon = home_lon
        self.span_nm = span_nm
        self._lock = threading.Lock()
        self._busy = False
        self._pending = None
        self.view = None            # (x0, x1, y0, y1, px_w) in nm from HOME; None = +-span_nm

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
            arr, x0, y0, x1, y1 = self._build(style)
            if arr is not None:
                self.ready.emit(arr, x0, y0, x1, y1)
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

        for tx in range(tx0, tx1 + 1):
            for ty in range(ty0, ty1 + 1):
                fallback = None
                for name, url_tpl in sources:
                    # per-source cache dir: an old cached placeholder (satellite/<z>/, before
                    # 2026-11-17) is never read again
                    cache_dir = CACHE_ROOT / style / name / str(zoom)
                    cache_dir.mkdir(parents=True, exist_ok=True)
                    data = _fetch_one(url_tpl, zoom, tx, ty, cache_dir)
                    tile = _qimg_to_rgb(data) if data is not None else None
                    if tile is None:
                        continue
                    if _blank(tile):            # e.g. open sea, or no coverage: try the next,
                        fallback = fallback if fallback is not None else tile   # else keep it
                        continue
                    fallback = tile
                    break
                if fallback is not None:
                    y_px = (ty - ty0) * TILE_SIZE
                    x_px = (tx - tx0) * TILE_SIZE
                    th, tw = fallback[:TILE_SIZE, :TILE_SIZE].shape[:2]
                    canvas[y_px:y_px + th, x_px:x_px + tw] = fallback[:TILE_SIZE, :TILE_SIZE]

        n_lat, _, w_lon, _ = _tile_bounds(tx0, ty0, zoom)
        _, s_lat, _, e_lon = _tile_bounds(tx1, ty1, zoom)
        nm_x0, nm_y0 = _nm_from_home(self.home_lat, self.home_lon, s_lat, w_lon)
        nm_x1, nm_y1 = _nm_from_home(self.home_lat, self.home_lon, n_lat, e_lon)

        # tiles are Web-Mercator rows; the plot is flat nm (lat * 60). Resample the rows so every
        # row sits at its own latitude — else a point near the view's edge drew a tile off.
        canvas = canvas[_mercator_rows(n_lat, s_lat, ty0, zoom, canvas.shape[0])]
        # row 0 of the canvas is the NORTH edge; the plot's y grows north, and the image item is
        # row-major with row 0 at the rect's bottom (y0 = south), so flip the rows once here.
        canvas = np.ascontiguousarray(canvas[::-1])
        return canvas, nm_x0, nm_y0, nm_x1, nm_y1
