"""Regression tests for bugs fixed in tiles.py during the code audit."""
import io
import time
import urllib.error

import tiles


def _layer(monkeypatch, tmp_path):
    monkeypatch.setattr(tiles, "CACHE_ROOT", str(tmp_path))
    return tiles.TileLayer(workers=0)


class _Resp(io.BytesIO):
    def __init__(self, data, ctype):
        super().__init__(data)
        import email.message
        self.headers = email.message.Message()
        self.headers["Content-Type"] = ctype

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass


def test_http_404_does_not_mark_layer_offline(monkeypatch, tmp_path):
    t = _layer(monkeypatch, tmp_path)

    def boom(req, timeout=0):
        raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, None)
    monkeypatch.setattr(tiles.urllib.request, "urlopen", boom)
    assert t._fetch(("dark", 5, 1, 1)) is False
    assert t.online is True


def test_captive_portal_html_is_not_cached(monkeypatch, tmp_path):
    t = _layer(monkeypatch, tmp_path)
    html = b"<html><body>Please log in to the hotel Wi-Fi</body></html>" * 5
    monkeypatch.setattr(tiles.urllib.request, "urlopen", lambda req, timeout=0: _Resp(html, "text/html"))
    key = ("dark", 5, 1, 1)
    assert t._fetch(key) is False
    import os
    assert not os.path.exists(t.path(*key))


def test_undecodable_tile_is_marked_failed(monkeypatch, tmp_path):
    t = _layer(monkeypatch, tmp_path)
    key = ("dark", 5, 1, 1)
    import os
    p = t.path(*key)
    os.makedirs(os.path.dirname(p))
    open(p, "wb").write(b"garbage" * 50)
    assert t._image(key) is None
    assert key in t.failed, "draw() would re-download it on every redraw"


def test_bulk_progress_ignores_view_tiles(monkeypatch, tmp_path):
    t = _layer(monkeypatch, tmp_path)
    t.bulk_keys = {("dark", 9, 1, 1), ("dark", 9, 1, 2)}
    t.bulk = {"total": 2, "done": 0, "active": True}
    monkeypatch.setattr(t, "_fetch", lambda k: True)

    class Stop(Exception):
        pass

    class FakeQ:
        items = [(0, 0, ("dark", 9, 5, 5)), (0, 0, ("dark", 9, 6, 6)),  # 2 view tiles
                 (1, 0, ("dark", 9, 1, 1))]                             # 1 bulk tile

        def get(self):
            if not self.items:
                raise Stop
            return self.items.pop(0)
    t.q = FakeQ()
    try:
        t._worker()
    except Stop:
        pass
    assert t.bulk == {"total": 2, "done": 1, "active": True}


def test_radar_tile_in_memory_is_refreshed_after_ttl(monkeypatch, tmp_path):
    t = _layer(monkeypatch, tmp_path)
    ttl_layer = next(k for k, v in tiles.LAYERS.items() if v.get("ttl"))
    key = (ttl_layer, 6, 1, 1)
    t.images[key], t.order = object(), [key]
    t.loaded[key] = time.time() - 10_000
    queued = []
    monkeypatch.setattr(t, "_enqueue", lambda k, priority: queued.append(k))
    assert t._image(key) is not None
    assert queued == [key]
