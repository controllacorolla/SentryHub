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
