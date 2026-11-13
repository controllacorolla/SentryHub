"""Tests for the offline AI RF copilot (LLM call injected — no model needed)."""
import copilot as C


def test_gather_context_from_providers():
    ctx = C.gather_context({
        "signal": lambda: {"mod": "FSK", "freq_mhz": 433.92},
        "contacts": lambda: [{"id": "UAS-1", "type": "drone"}],
        "allocation": lambda: "ISM / Amateur (433 ISM)",
        "engagement": lambda: {"active": True, "name": "job", "scope": ["AA:*"]},
    })
    assert ctx["signal"]["mod"] == "FSK" and ctx["allocation"].startswith("ISM")
    assert ctx["contacts"][0]["id"] == "UAS-1"


def test_gather_context_tolerates_bad_provider():
    def boom():
        raise RuntimeError("x")
    ctx = C.gather_context({"signal": boom, "allocation": lambda: "FM broadcast"})
    assert "signal" not in ctx and ctx["allocation"] == "FM broadcast"


def test_build_prompt_includes_context_and_question():
    ctx = {"signal": {"mod": "FSK", "freq_mhz": 433.92}, "allocation": "433 ISM",
           "contacts": [{"id": "a"}], "engagement": {"active": True, "name": "j", "scope": ["x"]}}
    p = C.build_prompt(ctx, "what is this?")
    assert "RF/SIGINT analyst" in p and "FSK" in p and "433 ISM" in p
    assert "OPERATOR QUESTION: what is this?" in p and p.rstrip().endswith("ANALYSIS:")


def test_build_prompt_quiet_when_empty():
    p = C.build_prompt({}, "anything?")
    assert "quiet" in p and "anything?" in p


def test_ask_llm_uses_injected_caller():
    seen = {}

    def caller(payload):
        seen.update(payload)
        return "it is a 2-FSK ISM remote; try rtl_433"
    ans = C.ask_llm("PROMPT", model="qwen-obl", caller=caller)
    assert ans.startswith("it is a 2-FSK") and seen["model"] == "qwen-obl" and seen["prompt"] == "PROMPT"


def test_analyze_end_to_end_with_mock():
    ans, prompt = C.analyze("identify this", providers={"allocation": lambda: "GPS L1"},
                            caller=lambda payload: "GNSS band — do not transmit")
    assert "GNSS" in ans and "GPS L1" in prompt
