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


@pytest.fixture(autouse=True)
def _cl3_private_data_dir(monkeypatch, tmp_path_factory):
    """CL3: every engagement start writes a durable evidence chain under suite.DATA. Tests must
    never write into the developer's real ~/.local/share/uconsole-suite, so DATA is redirected to
    a per-test temp dir and the process-wide chain routing is reset."""
    try:
        import suite
        import chain
    except ImportError:
        yield
        return
    d = tmp_path_factory.mktemp("palisade-data")
    monkeypatch.setattr(suite, "DATA", str(d))
    chain.reset_for_tests()
    yield
    chain.reset_for_tests()


@pytest.fixture(autouse=True)
def _n_op1_private_config_dir(monkeypatch, tmp_path_factory):
    """N-op1: SYSTEM › SETTINGS › SAVE now writes the operator profile (operator.json under
    suite.CFG). Tests must never write into the developer's real ~/.config/uconsole-suite, so CFG
    is redirected to a per-test temp dir (same pattern as the CL3 DATA redirect above)."""
    try:
        import suite
    except ImportError:
        yield
        return
    monkeypatch.setattr(suite, "CFG", str(tmp_path_factory.mktemp("palisade-cfg")))
    yield
