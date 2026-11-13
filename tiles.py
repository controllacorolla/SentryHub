"""Basemap tiles for the Sky map: Web Mercator maths, a disk cache and background fetching.

Layers are public, key-free tile servers.  Everything fetched is written to
~/.cache/uconsole-suite/tiles/<layer>/<z>/<x>/<y>.<ext> so the map keeps working
with no network, and "download area" pre-fills that cache for a region.
"""
import math
import os
import queue
import threading
import time
import urllib.error
import urllib.request

TILE = 256
UA = "uconsole-suite/1.0 (personal handheld; tkinter)"
CACHE_ROOT = os.path.join(os.path.expanduser("~"), ".cache", "uconsole-suite", "tiles")

LAYERS = {
    "dark": {
        "label": "Dark",
        # USGS Topo, darkened on-device with PIL. USGS is a keyless US-government service - no
        # registration, no API key, no app blocking - so the dark map can never ask for one.
        "url": "https://basemap.nationalmap.gov/arcgis/rest/services/USGSTopo/MapServer/tile/{z}/{y}/{x}",
        "ext": "jpg", "min": 3, "max": 16, "dim": 1.0, "transform": "dark",
        "credit": "USGS The National Map (dark)",
    },
    "sat": {
        "label": "Satellite",
        "url": "https://basemap.nationalmap.gov/arcgis/rest/services/USGSImageryOnly/MapServer/tile/{z}/{y}/{x}",
        "ext": "jpg", "min": 3, "max": 16, "dim": 0.6,
        "credit": "Imagery: USGS The National Map",
    },
    "streets": {
        "label": "Topo",
        "url": "https://basemap.nationalmap.gov/arcgis/rest/services/USGSTopo/MapServer/tile/{z}/{y}/{x}",
        "ext": "jpg", "min": 3, "max": 16, "dim": 1.0,
        "credit": "USGS The National Map",
    },
}
LAYER_ORDER = ["dark", "sat", "streets"]

# overlays: transparent PNGs drawn above the basemap.  ttl = seconds before a cached tile is re-fetched
OVERLAYS = {
    "radar": {
        "label": "Radar",
        "url": "https://mesonet.agron.iastate.edu/cache/tile.py/1.0.0/nexrad-n0q-900913/{z}/{x}/{y}.png",
        "ext": "png", "min": 3, "max": 15, "dim": 1.0, "alpha": 0.6, "ttl": 300,
        "credit": "Radar: NEXRAD via Iowa State Mesonet",
    },
}
LAYERS.update(OVERLAYS)

# test hook: point every layer at a local tile server (used by the suite's test harness)
if os.environ.get("UCS_TILE_BASE"):
    for _name, _spec in LAYERS.items():
        _spec["url"] = os.environ["UCS_TILE_BASE"].rstrip("/") + "/" + _name + "/{z}/{x}/{y}.png"
        _spec["ext"] = "png"
        if _name in OVERLAYS:
            _spec["ttl"] = 60

try:
    from PIL import Image, ImageEnhance, ImageOps, ImageTk
    HAVE_PIL = True
except Exception:  # pragma: no cover - depends on the device
    HAVE_PIL = False


def _to_dark(im):
    """Turn a light OSM tile into a muted dark-canvas tile, on-device (no dark-tile provider)."""
    g = ImageOps.grayscale(im)
    inv = ImageOps.invert(g)                      # light land -> dark, lines/labels -> light
    # map shadows to near-black, highlights to a cool gray: a clean dark basemap
    return ImageOps.colorize(inv, black=(13, 16, 19), mid=(42, 48, 55), white=(150, 162, 173))


# ------------------------------------------------------------------ mercator maths

def world_px(lat, lon, z):
    """Lat/lon -> absolute pixel coordinates in the zoom-z tile grid."""
    n = TILE * (1 << z)
    lat = max(-85.05, min(85.05, lat))
    x = (lon + 180.0) / 360.0 * n
    s = math.sin(math.radians(lat))
    y = (0.5 - math.log((1 + s) / (1 - s)) / (4 * math.pi)) * n
    return x, y


def from_world_px(x, y, z):
    n = TILE * (1 << z)
    lon = x / n * 360.0 - 180.0
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    return lat, lon


def px_per_nm(lat, z):
    """Pixels per nautical mile at this latitude and zoom (Mercator local scale)."""
    n = TILE * (1 << z)
    return n / (360.0 * 60.0 * max(0.05, math.cos(math.radians(lat))))


# ------------------------------------------------------------------ tile cache

class TileLayer:
    """Owns the on-disk cache, an in-memory PhotoImage cache and the fetch workers.

    draw(canvas, view_lat, view_lon, z, w, h) paints whatever is available and
    schedules fetches for the rest; `on_ready` is called from a worker thread
    when a new tile has landed, so the caller should hop back to the Tk thread.
    """

    def __init__(self, on_ready=None, workers=3):
        self.layer = "dark"
        self.on_ready = on_ready
        self.images = {}          # (layer, z, x, y) -> PhotoImage
        self.order = []           # LRU of the keys above
        self.failed = {}          # key -> time of failure (retry after a while)
        self.pending = set()
        self.refreshed = set()    # keys re-downloaded by a worker; the Tk thread drops its old image
        self.q = queue.PriorityQueue()
        self.lock = threading.Lock()
        self.online = True
        self.last_error = ""
        self.bulk = {"total": 0, "done": 0, "active": False}
        self.bulk_keys = set()    # keys that belong to the running bulk download
        self.loaded = {}          # key -> time its PhotoImage was made (TTL'd layers re-check)
        self.closed = False
        self._n_workers = workers
        for _ in range(workers):
            threading.Thread(target=self._worker, daemon=True).start()
        try:                              # in the workstation: stop with the workspace
            import theme
            theme.on_workspace_close(self.close)
        except Exception:
            pass

    def close(self):
        """Stop the fetch workers (queued tiles are dropped; the disk cache is untouched)."""
        self.closed = True
        for i in range(self._n_workers):
            self.q.put((float("-inf"), i, None))

    # ---- layer handling
    def cycle(self):
        i = LAYER_ORDER.index(self.layer)
        self.layer = LAYER_ORDER[(i + 1) % len(LAYER_ORDER)]
        return self.layer

    @property
    def spec(self):
        return LAYERS[self.layer]

    def clamp_zoom(self, z):
        return max(self.spec["min"], min(self.spec["max"], z))

    # ---- paths
    def path(self, layer, z, x, y):
        return os.path.join(CACHE_ROOT, layer, str(z), str(x), "%d.%s" % (y, LAYERS[layer]["ext"]))

    def cached_count(self, layer=None):
        root = os.path.join(CACHE_ROOT, layer or self.layer)
        n = 0
        for _, _, files in os.walk(root):
            n += len(files)
        return n

    # ---- drawing
    def draw(self, cv, lat, lon, z, w, h, tag="tile"):
        """Paint tiles covering a w×h canvas centred on lat/lon.  Returns #missing."""
        if z < self.spec["min"] or z > self.spec["max"]:
            return 0
        cx, cy = world_px(lat, lon, z)
        left, top = cx - w / 2.0, cy - h / 2.0
        n_tiles = 1 << z
        tx0, ty0 = int(math.floor(left / TILE)), int(math.floor(top / TILE))
        tx1, ty1 = int(math.floor((left + w) / TILE)), int(math.floor((top + h) / TILE))
        missing = 0
        now = time.time()
        for ty in range(max(0, ty0), min(n_tiles - 1, ty1) + 1):
            for tx in range(tx0, tx1 + 1):
                wx = tx % n_tiles
                key = (self.layer, z, wx, ty)
                img = self._image(key)
                if img is None:
                    missing += 1
                    if key not in self.failed or now - self.failed[key] > 90:
                        self._enqueue(key, priority=0)
                    continue
                cv.create_image(tx * TILE - left, ty * TILE - top, image=img, anchor="nw", tags=tag)
        return missing

    def _image(self, key):
        if self.refreshed:
            with self.lock:
                drop, self.refreshed = self.refreshed, set()
            for k in drop:
                self.images.pop(k, None)
                try:
                    self.order.remove(k)
                except ValueError:
                    pass
        img = self.images.get(key)
        if img is not None:
            ttl = LAYERS[key[0]].get("ttl")
            if ttl and self.online and time.time() - self.loaded.get(key, 0) > ttl:
                # an in-memory hit never reached the disk-age check below, so a radar tile
                # held in the LRU was never refreshed; re-check (the worker skips fresh files)
                self.loaded[key] = time.time()
                self._enqueue(key, priority=0)
            if self.order and self.order[-1] != key:
                try:
                    self.order.remove(key)
                except ValueError:
                    pass
                self.order.append(key)
            return img
        p = self.path(*key)
        if not os.path.exists(p):
            return None
        ttl = LAYERS[key[0]].get("ttl")
        if ttl:
            age = time.time() - os.path.getmtime(p)
            if age > ttl and self.online:
                self._enqueue(key, priority=0)      # refresh in the background, keep showing the old one
            if age > ttl * 6:
                return None                          # too stale to be useful
        try:
            img = self._load(p, LAYERS[key[0]]["dim"], LAYERS[key[0]].get("alpha"),
                             LAYERS[key[0]].get("transform"))
        except Exception:
            if not HAVE_PIL and LAYERS[key[0]]["ext"] != "png":
                return None    # Tk alone can't read JPEG: the file is fine, don't delete it
            try:
                os.remove(p)   # corrupt / truncated download
            except OSError:
                pass
            # remember the failure, or draw() re-downloads the same bad tile on every redraw
            self.failed[key] = time.time()
            return None
        self.images[key] = img
        self.loaded[key] = time.time()
        self.order.append(key)
        while len(self.order) > 240:
            old = self.order.pop(0)
            self.images.pop(old, None)
            self.loaded.pop(old, None)
        return img

    def _load(self, p, dim, alpha=None, transform=None):
        if HAVE_PIL:
            if alpha is not None:
                im = Image.open(p).convert("RGBA")
                if alpha < 0.999:
                    a = im.getchannel("A").point(lambda v: int(v * alpha))
                    im.putalpha(a)
                return ImageTk.PhotoImage(im)
            im = Image.open(p).convert("RGB")
            if transform == "dark":
                im = _to_dark(im)
            elif dim < 0.999:
                im = ImageEnhance.Brightness(im).enhance(dim)
                im = ImageEnhance.Color(im).enhance(0.75)
            return ImageTk.PhotoImage(im)
        import tkinter as tk
        return tk.PhotoImage(file=p)   # PNG only, no dimming

    # ---- fetching
    def _enqueue(self, key, priority):
        with self.lock:
            if key in self.pending:
                return
            self.pending.add(key)
        self.q.put((priority, time.time(), key))

    def _worker(self):
        while True:
            _, _, key = self.q.get()
            if key is None or self.closed:
                return
            try:
                ok = self._fetch(key)
            except Exception:
                ok = False
            with self.lock:
                self.pending.discard(key)
                # count only bulk tiles: view tiles fetched while panning used to finish the
                # count early ("download complete" with bulk tiles still queued)
                if self.bulk["active"] and key in self.bulk_keys:
                    self.bulk_keys.discard(key)
                    self.bulk["done"] += 1
                    if self.bulk["done"] >= self.bulk["total"]:
                        self.bulk["active"] = False
            if not ok:
                self.failed[key] = time.time()
            if self.on_ready:
                try:
                    self.on_ready(ok)
                except Exception:
                    pass

    def _fetch(self, key):
        layer, z, x, y = key
        p = self.path(layer, z, x, y)
        ttl = LAYERS[layer].get("ttl")
        if os.path.exists(p) and not (ttl and time.time() - os.path.getmtime(p) > ttl):
            return True
        url = LAYERS[layer]["url"].format(z=z, x=x, y=y)
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "image/*"})
        try:
            with urllib.request.urlopen(req, timeout=8) as r:
                data = r.read()
                ctype = r.headers.get_content_type() if r.headers else "image/x"
        except urllib.error.HTTPError as e:
            # the server answered (404 out of coverage, 5xx for one tile): we're online
            self.last_error = str(e)[:80]
            return False
        except Exception as e:
            self.online = False
            self.last_error = str(e)[:80]
            return False
        if len(data) < 100:
            return False
        if not (ctype.startswith("image/") or ctype == "application/octet-stream"):
            # captive-portal / proxy HTML with a 200: don't cache it as a tile
            self.last_error = "not an image (%s)" % ctype
            return False
        self.online = True
        os.makedirs(os.path.dirname(p), exist_ok=True)
        tmp = p + ".part"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, p)
        with self.lock:
            self.refreshed.add((layer, z, x, y))
        return True

    # ---- bulk download for offline use
    def area_tiles(self, lat, lon, z, w, h, extra_in=2, extra_out=1):
        """Keys covering the current view at zoom z, plus extra_out levels out and extra_in in."""
        cx, cy = world_px(lat, lon, z)
        # geographic bbox of the view at the current zoom
        lat1, lon1 = from_world_px(cx - w / 2.0, cy + h / 2.0, z)
        lat2, lon2 = from_world_px(cx + w / 2.0, cy - h / 2.0, z)
        keys = []
        zs = range(max(self.spec["min"], z - extra_out), min(self.spec["max"], z + extra_in) + 1)
        for zz in zs:
            x1, y2 = world_px(lat1, lon1, zz)
            x2, y1 = world_px(lat2, lon2, zz)
            for ty in range(int(y1 // TILE), int(y2 // TILE) + 1):
                for tx in range(int(x1 // TILE), int(x2 // TILE) + 1):
                    keys.append((self.layer, zz, tx % (1 << zz), ty))
        return keys

    @staticmethod
    def bbox_keys(layer, lat1, lon1, lat2, lon2, zmin, zmax):
        """Tile keys covering a lat/lon box across a zoom range (no file checks)."""
        lat1, lat2 = min(lat1, lat2), max(lat1, lat2)
        lon1, lon2 = min(lon1, lon2), max(lon1, lon2)
        spec = LAYERS[layer]
        keys = []
        for z in range(max(spec["min"], zmin), min(spec["max"], zmax) + 1):
            x1, y2 = world_px(lat1, lon1, z)
            x2, y1 = world_px(lat2, lon2, z)
            for ty in range(int(y1 // TILE), int(y2 // TILE) + 1):
                for tx in range(int(x1 // TILE), int(x2 // TILE) + 1):
                    keys.append((layer, z, tx % (1 << z), ty))
        return keys

    def bbox_count(self, layer, lat1, lon1, lat2, lon2, zmin, zmax):
        """(total tiles, tiles already cached) for a box - cheap enough to call on every slider move."""
        keys = self.bbox_keys(layer, lat1, lon1, lat2, lon2, zmin, zmax)
        have = sum(1 for k in keys if os.path.exists(self.path(*k)))
        return len(keys), have

    def download_bbox(self, layer, lat1, lon1, lat2, lon2, zmin, zmax, limit=20000):
        keys = [k for k in self.bbox_keys(layer, lat1, lon1, lat2, lon2, zmin, zmax)
                if not os.path.exists(self.path(*k))][:limit]
        with self.lock:
            if not self.bulk["active"]:
                self.bulk_keys = set()
            self.bulk_keys.update(keys)
            self.bulk = {"total": self.bulk["total"] + len(keys) if self.bulk["active"] else len(keys),
                         "done": self.bulk["done"] if self.bulk["active"] else 0, "active": bool(keys)}
        for k in keys:
            self._enqueue(k, priority=1)
        return len(keys)

    def cancel_bulk(self):
        """Drop queued bulk downloads (tiles already in flight finish)."""
        drained = 0
        try:
            while True:
                _, _, key = self.q.get_nowait()
                with self.lock:
                    self.pending.discard(key)
                drained += 1
        except queue.Empty:
            pass
        with self.lock:
            self.bulk = {"total": 0, "done": 0, "active": False}
            self.bulk_keys = set()
        return drained

    def cache_bytes(self, layer=None):
        root = os.path.join(CACHE_ROOT, layer) if layer else CACHE_ROOT
        total = 0
        for dp, _, files in os.walk(root):
            for f in files:
                try:
                    total += os.path.getsize(os.path.join(dp, f))
                except OSError:
                    pass
        return total

    def clear_cache(self, layer):
        import shutil
        shutil.rmtree(os.path.join(CACHE_ROOT, layer), ignore_errors=True)
        self.images = {k: v for k, v in self.images.items() if k[0] != layer}
        self.order = [k for k in self.order if k[0] != layer]

    def download_area(self, lat, lon, z, w, h, limit=2500):
        keys = [k for k in self.area_tiles(lat, lon, z, w, h) if not os.path.exists(self.path(*k))]
        keys = keys[:limit]
        with self.lock:
            self.bulk_keys = set(keys)
            self.bulk = {"total": len(keys), "done": 0, "active": bool(keys)}
        for k in keys:
            self._enqueue(k, priority=1)
        return len(keys)

    def newest_age(self, lat, lon, z, w, h):
        """Age in seconds of the freshest cached tile in view (None if none cached)."""
        ages = []
        for key in self.area_tiles(lat, lon, z, w, h, extra_in=0, extra_out=0):
            p = self.path(*key)
            if os.path.exists(p):
                ages.append(time.time() - os.path.getmtime(p))
        return min(ages) if ages else None

    def bulk_status(self):
        with self.lock:
            b = dict(self.bulk)
        return b
