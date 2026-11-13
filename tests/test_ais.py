"""Tests for the AIS/AIVDM decoder (Phase 4 #7). Offsets verified vs the gpsd AIVDM guide."""
import ais


def _mk(mtype=1, mmsi=123456789, sog=1023, lon=181 * 600000, lat=91 * 600000,
        cog=3600, hdg=511, status=0):
    bits = ["0"] * 168

    def put(start, length, val, signed=False):
        if signed and val < 0:
            val += (1 << length)
        b = format(val & ((1 << length) - 1), "0%db" % length)
        bits[start:start + length] = list(b)
    put(0, 6, mtype)
    put(8, 30, mmsi)
    put(38, 4, status)
    put(50, 10, sog)
    put(61, 28, lon, signed=True)
    put(89, 27, lat, signed=True)
    put(116, 12, cog)
    put(128, 9, hdg)
    return "".join(bits)


def test_real_vector_type1_mmsi_and_position():
    # Verified example from the gpsd AIVDM guide (vessel near Seattle).
    msg = ais.decode_sentence("!AIVDM,1,1,,B,177KQJ5000G?tO`K>RA1wUbN0TKH,0*5C")
    assert msg["type"] == 1 and msg["mmsi"] == 477553000
    assert abs(msg["lat"] - 47.5828) < 0.01
    assert abs(msg["lon"] - (-122.3458)) < 0.01
    assert abs(msg["cog_deg"] - 51.0) < 0.1
    assert msg["heading_deg"] == 181 and msg["status_name"] == "moored"
    assert msg["sog_kt"] == 0.0


def test_offsets_with_constructed_bits():
    m = ais.decode_bits(_mk(mmsi=366000001, sog=105, lon=-122 * 600000, lat=47 * 600000,
                            cog=905, hdg=90, status=1))
    assert m["mmsi"] == 366000001 and m["status_name"] == "anchored"
    assert m["sog_kt"] == 10.5 and m["cog_deg"] == 90.5 and m["heading_deg"] == 90
    assert abs(m["lon"] + 122.0) < 1e-6 and abs(m["lat"] - 47.0) < 1e-6


def test_not_available_sentinels_become_none():
    m = ais.decode_bits(_mk())      # all defaults are the n/a sentinels
    assert m["sog_kt"] is None and m["lat"] is None and m["lon"] is None
    assert m["cog_deg"] is None and m["heading_deg"] is None


def test_6bit_text_decode():
    # "SHIP": S->19, H->8, I->9, P->16 (values 0-31 map to '@'..'_')
    bits = "".join(format(v, "06b") for v in (19, 8, 9, 16))
    assert ais._text6(bits, 0, 4) == "SHIP"
    # '@' terminates and trailing spaces strip
    bits2 = "".join(format(v, "06b") for v in (19, 8, 0, 9))     # S H @ I -> "SH"
    assert ais._text6(bits2, 0, 4) == "SH"


def test_vessels_merge_position_and_static():
    vs = ais.Vessels()
    vs.ingest(ais.decode_bits(_mk(mmsi=111, lon=-122 * 600000, lat=47 * 600000, sog=50, cog=100)), now=1)
    vs.ingest({"type": 5, "mmsi": 111, "name": "EVER GIVEN", "callsign": "H3RC",
               "destination": "ROTTERDAM", "ship_type_name": "cargo"}, now=2)
    v = vs.by_mmsi[111]
    assert v["name"] == "EVER GIVEN" and v["lat"] == 47.0 and v["callsign"] == "H3RC"
    assert vs.label(v) == "EVER GIVEN"
    fc = vs.fusion_contact(v)
    assert fc["source"] == "ais" and fc["mmsi"] == 111 and fc["type"] == "vessel"


def test_assembler_single_fragment():
    asm = ais.AivdmAssembler()
    msg = asm.feed("!AIVDM,1,1,,B,177KQJ5000G?tO`K>RA1wUbN0TKH,0*5C")
    assert msg["mmsi"] == 477553000


def test_decode_sentence_rejects_multifragment_and_junk():
    assert ais.decode_sentence("!AIVDM,2,1,3,B,somepayload,0*00") is None    # multi -> use assembler
    assert ais.decode_sentence("not a sentence") is None
