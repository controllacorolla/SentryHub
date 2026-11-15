"""Tests for Zigbee assessment (authorized, engagement-gated)."""
import pytest

import engagement as E
import zigbee as Z


@pytest.fixture(autouse=True)
def _reset():
    E.reset()
    yield
    E.reset()


def test_channel_to_mhz():
    assert Z.channel_to_mhz(11) == 2405 and Z.channel_to_mhz(26) == 2480
    assert Z.channel_to_mhz(99) is None


def test_sniff_is_ungated():
    ok, why, argv = Z.prepare("sniff", channel=15, out="x.pcap")
    assert ok and argv[0] == "zbdump" and "15" in argv and "ungated" in why


def test_active_discover_gated():
    assert Z.prepare("discover")[0] is False                 # no engagement
    E.start("iot audit", "self-owned", ["pan:0x1A2B@15"], "KD0ABC")    # PAN + channel (CL2/G5)
    ok, why, t = Z.prepare("discover")
    assert ok and t.argv[0] == "zbstumbler"
    assert Z.prepare("discover", channel=20)[0] is False      # channel not in scope


def test_inject_out_of_scope_blocked():
    E.start("iot audit", "self-owned", ["pan:0x1A2B@15"], "KD0ABC")
    assert Z.prepare("inject", pan=0x9999, channel=15)[0] is False
    assert Z.prepare("inject", pan=0x1A2B, channel=20)[0] is False
