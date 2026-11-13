"""Tests for the RDS decoder (Phase 4 #22)."""
import rds


def test_parse_rds_ps_and_flags():
    r = rds.parse_rds('{"pi":"0x403A","group":"0A","ps":"CLASSIC","tp":true,"ta":false,'
                      '"prog_type":"Classics"}')
    assert r["pi"] == "0x403A" and r["ps"] == "CLASSIC" and r["pty"] == "Classics"
    assert r["tp"] is True and r["ta"] is False


def test_parse_rds_radiotext_variants():
    assert rds.parse_rds('{"pi":"0x1","radiotext":"hello"}')["rt"] == "hello"
    assert rds.parse_rds('{"pi":"0x1","rt":"hi"}')["rt"] == "hi"


def test_parse_rds_rejects_non_rds():
    assert rds.parse_rds('{"no_pi":1}') is None
    assert rds.parse_rds("not json") is None


def test_stations_accumulate_latest_ps_and_rt():
    s = rds.Stations()
    s.add(rds.parse_rds('{"pi":"0x403A","ps":"CLASSIC"}'), now=1)
    s.add(rds.parse_rds('{"pi":"0x403A","radiotext":"Beethoven"}'), now=2)
    s.add(rds.parse_rds('{"pi":"0x403A","ps":"CLASSIC2"}'), now=3)
    st = s.by_pi["0x403A"]
    assert st["ps"] == "CLASSIC2" and st["rt"] == "Beethoven" and st["n"] == 3


def test_stations_recent_orders_by_last():
    s = rds.Stations()
    s.add(rds.parse_rds('{"pi":"0xA"}'), now=1)
    s.add(rds.parse_rds('{"pi":"0xB"}'), now=2)
    assert s.recent()[0]["pi"] == "0xB"


def test_demo_lines_all_parse():
    dm = rds.Demo()
    for _ in range(len(rds.Demo.LINES)):
        assert rds.parse_rds(dm.lines()[0]) is not None
