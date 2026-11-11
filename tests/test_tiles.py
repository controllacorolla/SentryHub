"""Tile engine: projection round-trip and the on-device dark transform."""
import tiles


def test_world_px_roundtrip():
    # projecting lat/lon to world pixels and back should return the original within rounding
    lat, lon, z = 39.7392, -104.9903, 12
    x, y = tiles.world_px(lat, lon, z)
    lat2, lon2 = tiles.from_world_px(x, y, z)
    assert abs(lat - lat2) < 1e-6
    assert abs(lon - lon2) < 1e-6


def test_world_px_monotonic_in_longitude():
    z = 10
    xa, _ = tiles.world_px(39.0, -105.0, z)
    xb, _ = tiles.world_px(39.0, -104.0, z)
    assert xb > xa   # east is larger x


def test_layers_are_keyless_usgs():
    # guards the regression that cost real debugging time: no API-key provider sneaks back in
    for name in ("dark", "sat", "streets"):
        url = tiles.LAYERS[name]["url"]
        assert "nationalmap.gov" in url
        assert "key=" not in url and "token=" not in url and "apikey" not in url.lower()


def test_to_dark_returns_image():
    # needs PIL *and* ImageTk (so a Tk-less CI box skips it); runs for real on the device / py3.12
    import pytest
    if not tiles.HAVE_PIL:
        pytest.skip("PIL/ImageTk unavailable in this interpreter")
    from PIL import Image
    src = Image.new("RGB", (16, 16), (200, 200, 200))
    out = tiles._to_dark(src)
    assert out.size == (16, 16)
    # a light input should map to a dark output (mean brightness drops)
    px = out.convert("L").tobytes()
    assert sum(px) / len(px) < 160
