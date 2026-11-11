"""Transcriber: spoken-number normalization and callsign matching."""
import transcriber


def test_normalize_spoken_numbers():
    assert transcriber.normalize("fifty five thirty") == "5530"
    assert transcriber.normalize("two two oh one") == "2201"


def test_normalize_joins_digit_runs():
    assert "1200" in transcriber.normalize("one two zero zero")


def test_mentioned_callsigns_matches_airline_number():
    flights = ["SKW5530", "N734SP", "UAL890"]
    hits = transcriber.mentioned_callsigns("skywest fifty five thirty descend", flights)
    assert "SKW5530" in hits


def test_mentioned_callsigns_empty_on_no_match():
    assert transcriber.mentioned_callsigns("good morning", ["UAL1"]) == set()


def test_parse_name_extracts_freq():
    # rtl_airband names clips <label>_<YYYYMMDD>_<HHMMSS>_<freq_hz>.mp3; parse_name pulls those out
    freq, stamp = transcriber.parse_name("/x/DEN_Tower_20261108_120000_118900000.mp3")
    assert freq == "118.900"
    assert stamp == "20261108120000"


def test_parse_name_rejects_foreign_names():
    assert transcriber.parse_name("/x/random.mp3") == (None, None)


def test_controller_phrasing_links_to_flight():
    from transcriber import mentioned_callsigns
    flights = ["UAL1234", "SKW5530", "N425CP", "FFT508"]
    assert mentioned_callsigns(
        "United twelve thirty four, descend and maintain one zero thousand", flights) == {"UAL1234"}
    assert "SKW5530" in mentioned_callsigns("Skywest fifty five thirty, contact departure", flights)
    assert "N425CP" in mentioned_callsigns(
        "Cessna four two five charlie papa, runway one seven left, cleared to land", flights)
    assert mentioned_callsigns("wind three five zero at six, altimeter three zero one two",
                               flights) == set()
