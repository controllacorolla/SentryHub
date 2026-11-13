"""Tests for the POCSAG/FLEX pager decoder (Phase 4 #11)."""
import pager


def test_parse_pocsag_alpha():
    p = pager.parse_pocsag("POCSAG1200: Address: 1234567  Function: 3  Alpha:   Hello world")
    assert p["proto"] == "POCSAG" and p["baud"] == 1200 and p["address"] == 1234567
    assert p["function"] == 3 and p["kind"] == "alpha" and p["text"] == "Hello world"


def test_parse_pocsag_numeric():
    p = pager.parse_pocsag("POCSAG512: Address:  980312  Function: 0  Numeric: 5551212")
    assert p["baud"] == 512 and p["address"] == 980312 and p["kind"] == "numeric"
    assert p["text"] == "5551212"


def test_parse_pocsag_no_payload():
    p = pager.parse_pocsag("POCSAG2400: Address: 1000001  Function: 1")
    assert p["address"] == 1000001 and p["kind"] == "" and p["text"] == ""


def test_parse_flex():
    p = pager.parse_flex("FLEX: 2026-11-12 18:30:01 1600/2/K/A 00.000 [0001234567] ALN Test page")
    assert p["proto"] == "FLEX" and p["address"] == 1234567 and p["kind"] == "aln"
    assert p["text"] == "Test page"


def test_parse_line_dispatches_and_ignores_junk():
    assert pager.parse_line("POCSAG1200: Address: 7  Function: 0  Alpha: hi")["proto"] == "POCSAG"
    assert pager.parse_line("FLEX: x [42] NUM 999")["proto"] == "FLEX"
    assert pager.parse_line("random noise line") is None


def test_pagers_groups_by_address_and_counts():
    pg = pager.Pagers()
    pg.add(pager.parse_line("POCSAG1200: Address: 100  Function: 3  Alpha: a"), now=1)
    pg.add(pager.parse_line("POCSAG1200: Address: 100  Function: 3  Alpha: b"), now=2)
    pg.add(pager.parse_line("POCSAG1200: Address: 200  Function: 3  Alpha: c"), now=3)
    assert len(pg.by_addr) == 2
    rec = pg.by_addr[("POCSAG", 100)]
    assert rec["n"] == 2 and rec["msgs"][-1]["text"] == "b"
    assert pg.recent()[0]["address"] == 200       # most recent first


def test_watch_callback_fires():
    fired = []
    pg = pager.Pagers()
    pg.on_page = lambda p: fired.append(p["address"])
    pg.add(pager.parse_line("POCSAG1200: Address: 555  Function: 3  Alpha: hi"))
    assert fired == [555]


def test_demo_lines_all_parse():
    dm = pager.Demo()
    for _ in range(len(pager.Demo.LINES)):
        line = dm.lines()[0]
        assert pager.parse_line(line) is not None
