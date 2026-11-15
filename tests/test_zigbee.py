"""Tests for Zigbee assessment (authorized, engagement-gated)."""
import pytest

import engagement as E
import txguard
import zigbee as Z


@pytest.fixture(autouse=True)
def _reset():
    E.reset()
    txguard.reset_session()
    yield
    E.reset()
    txguard.reset_session()


def test_channel_to_mhz():
    assert Z.channel_to_mhz(11) == 2405 and Z.channel_to_mhz(26) == 2480
    assert Z.channel_to_mhz(99) is None


def test_sniff_is_ungated():
    ok, why, argv = Z.prepare("sniff", channel=15, out="x.pcap")
    assert ok and argv[0] == "zbdump" and "15" in argv and "ungated" in why


def test_active_discover_gated():
    assert Z.prepare("discover")[0] is False                 # no engagement
    E.start("iot audit", "self-owned", ["pan:0x1A2B@15"], "KD0ABC")    # PAN + channel (CL2/G5)
    txguard.arm(True)    # CL2-fix N2: an RF emitter also needs the TX kill switch armed
    ok, why, t = Z.prepare("discover")
    assert ok and t.argv[0] == "zbstumbler"
    assert Z.prepare("discover", channel=20)[0] is False      # channel not in scope


def test_inject_out_of_scope_blocked():
    assert E.start("iot audit", "self-owned", ["pan:0x1A2B@15"], "KD0ABC")[0]
    txguard.arm(True)    # CL2-fix2 R2: armed + unlocked, so only SCOPE can refuse (not the RF gate)
    txguard.unlock_session(True)
    for pan, ch in ((0x9999, 15), (0x1A2B, 20)):
        ok, why, t = Z.prepare("inject", pan=pan, channel=ch)
        assert not ok and t is None and "not in the engagement scope" in why, why
    assert Z.prepare("inject", pan=0x1A2B, channel=15)[0] is True
