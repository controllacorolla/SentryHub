"""N-op1 (v0.1 blocker, found on device 2026-11-17): SYSTEM › SETTINGS › SAVE SETTINGS wrote the
operator into palisade_ui.json while the engagement gate reads operator.json (opprofile.load), so
no engagement could ever be opened from the UI. These tests drive the real SETTINGS save and the
real engagement._profile_operator() / engagement.start() against a private config dir."""
import json
import os

import pytest

pytest.importorskip("PySide6")

import engagement  # noqa: E402
import opprofile  # noqa: E402
import suite  # noqa: E402

# conftest stubs engagement._profile_operator for every test; capture the real one at import time
# (module import happens before the autouse fixture patches it).
_REAL_PROFILE_OPERATOR = engagement._profile_operator


@pytest.fixture
def real_gate(monkeypatch):
    monkeypatch.setattr(engagement, "_profile_operator", _REAL_PROFILE_OPERATOR)
    engagement.end()
    yield
    engagement.end()


def _app():
    from PySide6 import QtWidgets
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def _settings_page():
    _app()
    from palisade_qt.system import MoreApp
    p = MoreApp(demo=False, mode="dark")
    p._write_settings = lambda data: True          # HOME/theme store is not under test here
    return p


def _profile():
    return json.load(open(os.path.join(suite.CFG, "operator.json")))


def _start():
    return engagement.start("N-op1 test", "ROE-1", ["10.0.0.0/24"], None, hours=1)


def test_empty_profile_refuses_engagement(real_gate):
    ok, why = _start()
    assert not ok and "no operator profile" in why


def test_saving_a_name_in_settings_opens_an_engagement(real_gate):
    p = _settings_page()
    p.set_operator.setText("DALTON")
    p._save_settings()
    assert _profile()["name"] == "DALTON" and _profile()["callsign"] == ""
    assert engagement._profile_operator() == "DALTON"
    ok, why = _start()
    assert ok, why
    assert engagement.info()["operator"] == "DALTON"
    assert "operator saved: name DALTON" in p.set_msg.text()


def test_saving_a_callsign_in_settings_opens_an_engagement(real_gate):
    p = _settings_page()
    p.set_operator.setText("kd0xyz")
    p._save_settings()
    assert _profile()["callsign"] == "KD0XYZ"
    assert engagement._profile_operator() == "KD0XYZ"
    ok, why = _start()
    assert ok, why
    assert "operator saved: callsign KD0XYZ" in p.set_msg.text()


def test_typed_name_replaces_an_older_callsign_identity(real_gate):
    """The field shows callsign-else-name; what is typed must be what the engagement records."""
    suite.save_json(os.path.join(suite.CFG, "operator.json"),
                    dict(opprofile.DEFAULTS, callsign="KD0XYZ", name="OLD"))
    p = _settings_page()
    p.set_operator.setText("DALTON")
    p._save_settings()
    assert engagement._profile_operator() == "DALTON"


def test_clearing_the_operator_refuses_engagements_again(real_gate):
    p = _settings_page()
    p.set_operator.setText("DALTON")
    p._save_settings()
    p.set_operator.setText("   ")
    p._save_settings()
    assert engagement._profile_operator() is None
    ok, why = _start()
    assert not ok and "no operator profile" in why
    assert "operator cleared" in p.set_msg.text()


@pytest.mark.parametrize("prior", [None, True, False, "yes"])
def test_save_never_touches_tx_enabled_or_other_keys(real_gate, prior):
    """CL2 strict default: a callsign saved in SETTINGS never enables TX, and unrelated profile keys
    (grid, authorization, tx_enabled) survive the save unchanged."""
    path = os.path.join(suite.CFG, "operator.json")
    base = dict(opprofile.DEFAULTS, grid="DM79", authorization="AUTH-9")
    if prior is not None:
        base["tx_enabled"] = prior
    suite.save_json(path, base)
    p = _settings_page()
    p.set_operator.setText("KD0XYZ")
    p._save_settings()
    prof = _profile()
    assert prof.get("tx_enabled", "<absent>") == (prior if prior is not None else "<absent>")
    assert prof["grid"] == "DM79" and prof["authorization"] == "AUTH-9"
    assert opprofile.tx_settings(opprofile.load(suite.settings))["tx_enabled"] is (prior is True)


def test_operator_is_no_longer_written_to_the_ui_store(real_gate):
    _app()
    from palisade_qt.system import MoreApp
    p = MoreApp(demo=False, mode="dark")
    captured = {}
    p._write_settings = lambda data: (captured.update(data), True)[1]
    p.set_operator.setText("DALTON")
    p._save_settings()
    assert "callsign" not in captured and "name" not in captured


def test_save_message_is_honest_when_no_operator_store(real_gate, monkeypatch):
    p = _settings_page()
    monkeypatch.setattr(suite, "save_json", lambda *a, **k: (_ for _ in ()).throw(OSError("ro")))
    p.set_operator.setText("DALTON")
    p._save_settings()
    msg = p.set_msg.text()
    assert "operator NOT saved" in msg and "operator saved" not in msg


def test_settings_prefill_round_trips(real_gate):
    p = _settings_page()
    p.set_operator.setText("DALTON")
    p._save_settings()
    q = _settings_page()
    assert q.set_operator.text() == "DALTON"
