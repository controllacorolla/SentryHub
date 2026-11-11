"""Regression tests for bugs fixed in sensors.py during the code audit."""
import sensors as SN


def test_rtl433_cmd_requests_si_units():
    cmd = SN.rtl433_cmd("433.92M", 0)
    assert "-C" in cmd and cmd[cmd.index("-C") + 1] == "si"
