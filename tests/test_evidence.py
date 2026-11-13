"""Tests for the evidence/engagement infrastructure (Phase 3f)."""
import evidence as E


# ---- timeline -----------------------------------------------------------------------------
def test_timeline_filter_and_search():
    tl = E.Timeline()
    tl.add("dronewatch", "detection", "Drone UAS-1 seen", contact="UAS-1", ts=100)
    tl.add("aprs", "contact", "KD0ABC heard", contact="KD0ABC", ts=110)
    tl.add("dronewatch", "alert", "Drone below 120m", contact="UAS-1", ts=120)
    assert len(tl.filter(module="dronewatch")) == 2
    assert len(tl.filter(contact="UAS-1")) == 2
    assert len(tl.filter(etype="alert")) == 1
    assert len(tl.filter(since=105, until=115)) == 1
    assert len(tl.filter(query="kd0abc")) == 1


def test_timeline_export(tmp_path):
    tl = E.Timeline()
    tl.add("m", "t", "second", ts=200)
    tl.add("m", "t", "first", ts=100)
    p = tl.export_jsonl(str(tmp_path / "tl.jsonl"))
    lines = open(p).read().strip().splitlines()
    import json
    assert json.loads(lines[0])["text"] == "first"      # sorted by ts


# ---- evidence chain -----------------------------------------------------------------------
def test_evidence_chain_links_and_verifies():
    ch = E.EvidenceChain()
    ch.add("capture1.iq", data=b"aaaa", ts=1)
    ch.add("capture2.png", data=b"bbbb", ts=2)
    assert ch.records[0]["prev"] == E.GENESIS
    assert ch.records[1]["prev"] == ch.records[0]["chain"]
    assert ch.verify() == (True, None)


def test_evidence_chain_detects_tampering():
    ch = E.EvidenceChain()
    ch.add("a", data=b"one", ts=1)
    ch.add("b", data=b"two", ts=2)
    ch.add("c", data=b"three", ts=3)
    ch.records[1]["sha256"] = E.sha256_bytes(b"forged")    # tamper with a past record
    ok, bad = ch.verify()
    assert ok is False and bad == 1


def test_evidence_chain_hashes_a_file(tmp_path):
    p = tmp_path / "cap.bin"
    p.write_bytes(b"\x00\x01\x02\x03")
    ch = E.EvidenceChain()
    rec = ch.add("cap.bin", file_path=str(p), ts=1)
    assert rec["sha256"] == E.sha256_bytes(b"\x00\x01\x02\x03")
    assert ch.verify()[0]


# ---- QSO / ADIF ---------------------------------------------------------------------------
def test_adif_field_length_prefix():
    assert E.adif_field("CALL", "KD0ABC") == "<CALL:6>KD0ABC"


def test_qso_to_adif_and_export():
    q = {"call": "KD0ABC", "band": "20m", "mode": "FT8", "freq_mhz": "14.074",
         "rst_sent": "-10", "rst_rcvd": "-12", "qso_date": "20261112", "time_on": "1830"}
    adif = E.qso_to_adif(q)
    assert "<CALL:6>KD0ABC" in adif and "<MODE:3>FT8" in adif and adif.endswith("<EOR>")
    doc = E.adif_export([q])
    assert "<EOH>" in doc and doc.count("<EOR>") == 1


def test_qsolog_autofills_date_time():
    log = E.QSOLog()
    log.add(call="W1AW", band="40m", mode="CW")
    q = log.qsos[0]
    assert q["qso_date"] and q["time_on"] and "<CALL:4>W1AW" in log.to_adif()


# ---- vault --------------------------------------------------------------------------------
def test_vault_commands_and_availability():
    v = E.Vault("/tmp/eng.age", backend="age")
    assert v.available(which=lambda n: "/usr/bin/age" if n == "age" else None) is True
    assert v.available(which=lambda n: None) is False
    lock = v.lock_argv("/tmp/findings", "age1recipientkey")
    assert "age -r age1recipientkey -o /tmp/eng.age" in lock[2]
    unlock = v.unlock_argv("/tmp/out", "/tmp/key.txt")
    assert "age -d -i /tmp/key.txt /tmp/eng.age" in unlock[2]


# ---- report -------------------------------------------------------------------------------
def test_report_html_has_all_sections():
    tl = E.Timeline()
    tl.add("dronewatch", "detection", "Drone seen", ts=100)
    ch = E.EvidenceChain()
    ch.add("cap.iq", data=b"x", ts=1)
    doc = E.report_html("Engagement A", timeline_events=tl.events,
                        evidence_records=ch.records,
                        findings=[{"title": "Open AP", "detail": "WEP in use"}],
                        meta={"Operator": "KD0ABC", "Date": "2026-11-12"})
    for needle in ("Engagement A", "Summary", "Findings", "Open AP",
                   "Engagement timeline", "Drone seen", "Evidence appendix", "cap.iq"):
        assert needle in doc


def test_report_escapes_html():
    doc = E.report_html("T", findings=["<script>alert(1)</script>"])
    assert "<script>alert(1)</script>" not in doc and "&lt;script&gt;" in doc


def test_pdf_argv_selection():
    assert E.pdf_from_html_argv("r.html", "r.pdf", which=lambda n: "/usr/bin/" + n
                                if n == "wkhtmltopdf" else None)[0] == "wkhtmltopdf"
    assert E.pdf_from_html_argv("r.html", "r.pdf", which=lambda n: None) is None
