"""Tests for the IQ recorder metadata + command building (Phase 6 #4)."""
import iqtool


def test_sidecar_write_read_roundtrip(tmp_path):
    iq = str(tmp_path / "cap_001.cu8")
    meta = iqtool.write_sidecar(iq, freq_hz=433_920_000, sample_rate=2_048_000, gain=30,
                                fmt="cu8", device="rtlsdr", gps={"lat": 39.6, "lon": -104.9},
                                duration_s=5.0, ts=1000)
    assert meta["freq_hz"] == 433_920_000
    back = iqtool.read_sidecar(iq)
    assert back["sample_rate"] == 2_048_000 and back["gps"]["lat"] == 39.6
    assert back["device"] == "rtlsdr"


def test_read_missing_sidecar_is_none(tmp_path):
    assert iqtool.read_sidecar(str(tmp_path / "nope.cu8")) is None


def test_capture_argv_rtlsdr():
    argv = iqtool.capture_argv("rtlsdr", 100_000_000, 2_048_000, "/tmp/x.cu8", gain=20, seconds=2)
    assert argv[0] == "rtl_sdr" and "/tmp/x.cu8" in argv
    assert "-f" in argv and "100000000" in argv and "-n" in argv


def test_capture_argv_hackrf():
    argv = iqtool.capture_argv("hackrf", 915_000_000, 8_000_000, "/tmp/y.cs8", gain=16, seconds=1)
    assert argv[0] == "hackrf_transfer" and "-r" in argv
    assert str(8_000_000) in argv


def test_list_captures_sorted_newest_first(tmp_path):
    iqtool.write_sidecar(str(tmp_path / "a.cu8"), 1e6, 2e6, ts=100)
    iqtool.write_sidecar(str(tmp_path / "b.cu8"), 2e6, 2e6, ts=200)
    caps = iqtool.list_captures(str(tmp_path))
    assert [c["iq_file"] for c in caps] == ["b.cu8", "a.cu8"]


def test_file_sha256_matches_evidence(tmp_path):
    p = tmp_path / "cap.cu8"
    p.write_bytes(b"\x01\x02\x03\x04")
    import evidence
    assert iqtool.file_sha256(str(p)) == evidence.sha256_bytes(b"\x01\x02\x03\x04")
