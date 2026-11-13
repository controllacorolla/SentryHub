"""Tests for the IMSI-catcher detector (Phase 6 #15)."""
import imsicatch as I


def _cell(mcc=310, mnc=260, lac=100, cid=5000, arfcn=128, rxlevel=-80, encryption="A5/3"):
    return {"mcc": mcc, "mnc": mnc, "lac": lac, "cid": cid, "arfcn": arfcn,
            "rxlevel": rxlevel, "encryption": encryption}


def _baseline(*cells):
    return {I._key(c): c for c in cells}


def test_known_cell_clean():
    bl = _baseline(_cell())
    assert I.analyze_cell(_cell(), bl) == []


def test_unknown_cell_flagged():
    flags = I.analyze_cell(_cell(cid=9999), _baseline(_cell()))
    assert any(f[0] == "unknown_cell" for f in flags)


def test_no_encryption_is_high():
    flags = I.analyze_cell(_cell(encryption="A5/0"), _baseline(_cell()))
    assert any(f[0] == "no_encryption" and f[2] == "high" for f in flags)


def test_arfcn_lac_mismatch():
    bl = _baseline(_cell(lac=100, cid=5000, arfcn=128))
    # same ARFCN 128 but a different LAC + CID -> fake BTS tell
    flags = I.analyze_cell(_cell(lac=777, cid=6000, arfcn=128), bl)
    assert any(f[0] == "lac_mismatch" and f[2] == "high" for f in flags)


def test_power_anomaly():
    bl = _baseline(_cell(rxlevel=-90))
    flags = I.analyze_cell(_cell(rxlevel=-50), bl)      # 40 dB stronger
    assert any(f[0] == "power_anomaly" for f in flags)


def test_detector_lac_flapping():
    d = I.IMSICatcherDetector()
    d.learn(_cell(lac=100))
    for lac in (100, 200, 300):                         # 3 distinct LACs in a row
        flags = d.observe(_cell(lac=lac))
    assert any(f[0] == "lac_flapping" for f in flags)


def test_detector_fires_callback():
    got = []
    d = I.IMSICatcherDetector()
    d.on_alert = lambda f: got.append(f[0])
    d.observe(_cell(encryption="A5/0"))
    assert "no_encryption" in got
