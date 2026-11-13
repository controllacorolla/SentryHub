"""Map tile fetcher + cache for ATLAS/OVERWATCH map backgrounds.

Fetches web map tiles (dark, light, satellite) in a background thread, caches them
locally under ~/.cache/palisade/tiles/ so the map works offline after first view.
Emits a stitched numpy array that the MapPanel renders as an ImageItem behind the
range rings and contacts.
"""
import math
import threading
from pathlib import Path
from urllib.request import urlopen, Request

import numpy as np
from PySide6 import QtCore, QtGui

TILE_URLS = {
    "dark": "https://a.basemaps.cartocdn.com/dark_nolabels/{z}/{x}/{y}.png",
    "light": "https://a.basemaps.cartocdn.com/light_nolabels/{z}/{x}/{y}.png",
    "satellite": ("https://server.arcgisonline.com/ArcGIS/rest/services/"
                  "World_Imagery/MapServer/tile/{z}/{y}/{x}"),
}
TILE_SIZE = 256
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


def _fetch_one(url_tpl, z, tx, ty, cache_dir):
    path = cache_dir / ("%d_%d.png" % (tx, ty))
    if path.exists():
        return path.read_bytes()
    url = url_tpl.format(z=z, x=tx, y=ty)
    try:
        req = Request(url, headers={"User-Agent": "PALISADE/1.0"})
        data = urlopen(req, timeout=8).read()
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

    def fetch(self, style):
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
        url_tpl = TILE_URLS.get(style)
        if url_tpl is None:
            return None, 0, 0, 0, 0
        zoom = _pick_zoom(self.span_nm)
        cos_lat = math.cos(math.radians(self.home_lat))
        north = self.home_lat + self.span_nm / 60
        south = self.home_lat - self.span_nm / 60
        west = self.home_lon - self.span_nm / (60 * cos_lat)
        east = self.home_lon + self.span_nm / (60 * cos_lat)

        tx0, ty0 = _tile_xy(north, west, zoom)
        tx1, ty1 = _tile_xy(south, east, zoom)
        if tx0 > tx1:
            tx0, tx1 = tx1, tx0
        if ty0 > ty1:
            ty0, ty1 = ty1, ty0
        tx0 -= 1
        ty0 -= 1
        tx1 += 1
        ty1 += 1

        cache_dir = CACHE_ROOT / style / str(zoom)
        cache_dir.mkdir(parents=True, exist_ok=True)

        nx = tx1 - tx0 + 1
        ny = ty1 - ty0 + 1
        canvas = np.zeros((ny * TILE_SIZE, nx * TILE_SIZE, 4), dtype=np.uint8)

        for tx in range(tx0, tx1 + 1):
            for ty in range(ty0, ty1 + 1):
                data = _fetch_one(url_tpl, zoom, tx, ty, cache_dir)
                if data is None:
                    continue
                tile = _qimg_to_rgb(data)
                if tile is None:
                    continue
                ix = tx - tx0
                iy = ty - ty0
                y_px = iy * TILE_SIZE
                x_px = ix * TILE_SIZE
                th, tw = tile.shape[:2]
                canvas[y_px:y_px + th, x_px:x_px + tw] = tile

        n_lat, _, w_lon, _ = _tile_bounds(tx0, ty0, zoom)
        _, s_lat, _, e_lon = _tile_bounds(tx1, ty1, zoom)
        nm_x0, nm_y0 = _nm_from_home(self.home_lat, self.home_lon, s_lat, w_lon)
        nm_x1, nm_y1 = _nm_from_home(self.home_lat, self.home_lon, n_lat, e_lon)

        canvas = canvas[::-1]
        return canvas, nm_x0, nm_y0, nm_x1, nm_y1
