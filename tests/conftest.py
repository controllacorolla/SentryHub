"""Shared pytest setup for the uConsole suite.

These tests cover the pure, display-free logic: parsers, the SDR-lease-free helpers,
power status, backup/restore, the session log, the Wi-Fi detector, TFR filtering, and
the sitrep template. Anything needing a live radio, gpsd, or a Tk display is out of scope.
"""
import os
import sys

# the suite modules live one level up from tests/
SUITE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SUITE_DIR not in sys.path:
    sys.path.insert(0, SUITE_DIR)


import pytest  # noqa: E402

TEST_OPERATOR = "KD0ABC"


@pytest.fixture(autouse=True)
def _cl2_operator_profile(monkeypatch):
    """CL2/G13: the engagement operator comes from the operator profile, never free text. Tests get
    a fixed profile identity instead of reading the developer's real ~/.config profile."""
    try:
        import engagement
    except ImportError:
        yield
        return
    monkeypatch.setattr(engagement, "_profile_operator", lambda: TEST_OPERATOR)
    monkeypatch.delenv("PALISADE_GATE_STATE", raising=False)
    yield
