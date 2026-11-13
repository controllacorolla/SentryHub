"""Tests for the power/thermal governor."""
import powergov as P


def test_decide_mode_scenarios():
    assert P.decide_mode(90, True, 45) == "full"            # plugged in, cool
    assert P.decide_mode(70, False, 45) == "reduced"        # on battery, healthy
    assert P.decide_mode(40, False, 45) == "minimal"        # on battery, mid
    assert P.decide_mode(8, False, 45) == "critical"        # nearly dead
    assert P.decide_mode(90, True, 80) == "critical"        # too hot even while charging
    assert P.decide_mode(90, True, 72) == "minimal"         # warm -> throttle
    assert P.decide_mode(90, True, 45, undervolt=True) == "critical"   # brownout flag wins


def test_policy_shape():
    assert P.policy_for("full")["num_thread"] == 4
    assert P.policy_for("critical")["allow"] == "none"
    assert P.policy_for("critical")["max_workers"] == 0


def test_governor_critical_applies_immediately():
    changes = []
    g = P.PowerGovernor(hysteresis=3)
    g.on_change = lambda m, pol: changes.append(m)
    g.update(5, False, 45)            # critical -> immediate despite hysteresis
    assert g.mode == "critical" and changes == ["critical"]


def test_governor_hysteresis_on_non_critical():
    g = P.PowerGovernor(hysteresis=2)
    g.mode = "full"
    g.update(70, False, 45)           # wants 'reduced' — 1st observation, not applied yet
    assert g.mode == "full"
    g.update(70, False, 45)           # 2nd consecutive — now applied
    assert g.mode == "reduced"


def test_allows_by_priority():
    g = P.PowerGovernor()
    g.mode = "minimal"
    assert g.allows("priority") is True and g.allows("normal") is False
    g.mode = "critical"
    assert g.allows("critical") is True and g.allows("priority") is False
    g.mode = "full"
    assert g.allows("normal") is True
