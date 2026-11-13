"""Regression tests for bugs fixed in assistant.py during the code audit."""
import assistant as A


def test_espeak_text_cannot_be_parsed_as_options():
    cmd = A.espeak_cmd("/usr/bin/espeak-ng", "en-us", 160, "- First item.")
    assert cmd[-2:] == ["--", "- First item."]


def test_short_first_sentence_does_not_block_streaming_speech():
    buf = "Sure. The next weather satellite pass is at noon. More text"
    out = []
    while True:
        nxt = A.next_sentence(buf)
        if not nxt:
            break
        out.append(nxt[0])
        buf = nxt[1]
    assert out == ["Sure. The next weather satellite pass is at noon."]
    assert buf == "More text"


# ---- AI improvements: model choice, on-device thread cap, power advice, live status

def test_best_model_keeps_the_configured_one_and_never_picks_an_embedder():
    models = ["nomic-embed-text:latest", "llama3.2:3b", "qwen-smart:latest"]
    assert A.best_model(models, "llama3.2:3b") == "llama3.2:3b"
    assert A.best_model(models, "qwen-smart") == "qwen-smart"          # ":latest" on the server
    assert A.best_model(models, "") == "qwen-smart:latest"
    assert A.best_model(models, "gone:7b") == "qwen-smart:latest"      # configured one was removed
    assert A.best_model(["nomic-embed-text:latest", "tinydolphin"]) == "tinydolphin"
    assert A.best_model(["nomic-embed-text:latest"]) == "nomic-embed-text:latest"   # nothing else


def test_is_local():
    assert A.is_local("http://127.0.0.1:11434") and A.is_local("http://localhost:11434/")
    assert A.is_local("http://[::1]:11434")
    assert not A.is_local("http://desktop:11434") and not A.is_local("http://10.0.0.2:11434")


def test_on_device_model_is_thread_capped_but_a_remote_one_is_not():
    s = {"local_threads": 2}
    assert A.chat_body(s, "http://127.0.0.1:11434", "m", [])["options"] == {"num_thread": 2}
    assert "options" not in A.chat_body(s, "http://desktop:11434", "m", [])
    assert "options" not in A.chat_body({"local_threads": 0}, "http://127.0.0.1:11434", "m", [])
    assert A.chat_body({}, "http://localhost:11434", "m", [], stream=False) == {
        "model": "m", "messages": [], "stream": False, "options": {"num_thread": 2}}


def test_power_warning_only_for_an_on_device_model_on_a_weak_supply():
    low = {"pct": 30, "charging": False, "undervolt_now": False}
    assert "30%" in A.power_warning(low, True)
    assert A.power_warning(low, False) == ""                                  # desktop does the work
    assert A.power_warning({"pct": 30, "charging": True}, True) == ""
    assert A.power_warning({"pct": 80, "charging": False}, True) == ""
    assert "Under-voltage" in A.power_warning({"pct": 90, "charging": True, "undervolt_now": True}, True)
    assert A.power_warning({"pct": None, "charging": False}, True) == ""      # no battery gauge


def test_live_context_states_only_what_is_known():
    d = {"aircraft_airborne": 3, "highest": {"cs": "UAL12", "alt": 36000},
         "metar": {"cat": "VFR", "station": "KAPA", "temp": 12, "wind_dir": 270, "wind_spd": 8},
         "gps": {"lat": 39.6260, "lon": -104.9068, "mode": 3},
         "next_pass": {"sat": "NOAA 19", "in_min": 14}}
    txt = A.live_context(d, {"pct": 62, "status": "Discharging", "temp": 64.2})
    for want in ("3 aircraft airborne", "UAL12 at 36000 feet", "KAPA: VFR, 12 C, wind 270 at 8",
                 "39.6260, -104.9068", "NOAA 19 in 14 minutes", "Battery 62%, discharging, CPU 64 C"):
        assert want in txt
    assert A.live_context({}) == "GPS: no fix."
    assert A.live_context(None) == "GPS: no fix."
    assert "aircraft" not in A.live_context({"battery": {"pct": 50, "status": "Full"}})


def test_system_prompt_carries_the_status_only_when_there_is_one():
    s = {"system": "Be brief."}
    assert A.system_prompt(s).startswith("Be brief. Current local time: ")
    assert "Live status" not in A.system_prompt(s)
    assert A.system_prompt(s, "GPS: no fix.").endswith("GPS: no fix.")


def test_live_context_cache_never_blocks_and_survives_a_failed_refresh():
    jobs, calls = [], []

    def gather():
        calls.append(1)
        if len(calls) == 2:
            raise OSError("offline")
        return {"aircraft_airborne": len(calls)}
    lc = A.LiveContext(ttl=0, gather=gather, power=lambda: {}, spawn=jobs.append)
    assert lc.get() == "" and len(jobs) == 1        # first call: nothing yet, refresh queued
    assert lc.get() == "" and len(jobs) == 1        # still running: not queued twice
    jobs.pop()()
    assert "1 aircraft" in lc.get()
    jobs.pop()()                                    # this refresh fails
    assert "1 aircraft" in lc.get()                 # old snapshot kept
    lc2 = A.LiveContext(ttl=3600, gather=gather, power=lambda: {}, spawn=jobs.append)
    lc2.get(); jobs.pop()()
    n = len(jobs)
    lc2.get()
    assert len(jobs) == n                           # fresh: no new refresh
