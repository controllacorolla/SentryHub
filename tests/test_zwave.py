"""Tests for Z-Wave assessment (authorized, engagement-gated)."""
import pytest

import engagement as E
import zwave as Z


@pytest.fixture(autouse=True)
def _reset():
    E.reset()
    yield
    E.reset()


def test_region_freq():
    assert Z.region_freq("US") == 908_420_000 and Z.region_freq("EU") == 868_420_000
    assert Z.region_freq("xx") is None


def test_grade_node_security():
    assert Z.grade_node({"id": 2, "security": "none"})[0] == "weak"
    assert Z.grade_node({"id": 3, "security": "S0"})[0] == "weak"
    assert Z.grade_node({"id": 4, "security": "S2_authenticated"})[0] == "ok"


def test_assess_summary():
    nodes = [{"id": 1, "security": "S2_authenticated"}, {"id": 2, "security": "S0"},
             {"id": 3, "security": "none"}]
    a = Z.assess(nodes)
    assert len(a["weak"]) == 2 and len(a["ok"]) == 1 and "2 of 3" in a["summary"]


def test_sniff_ungated_query_gated():
    ok, why, argv = Z.prepare("sniff", region="US", out="z.pcap")
    assert ok and argv[0] == "zwave-sniffer"
    assert Z.prepare("query", target="node5", node_id=5)[0] is False     # no engagement
    E.start("audit", "self-owned", ["node5"], "KD0ABC")
    ok, _, argv = Z.prepare("query", target="node5", region="US", node_id=5)
    assert ok and "5" in argv
