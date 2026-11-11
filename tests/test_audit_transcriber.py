"""Regression tests for bugs fixed in transcriber.py during the code audit."""
import os

import transcriber


def test_list_clips_skips_clip_deleted_mid_listing(tmp_path, monkeypatch):
    a, b = tmp_path / "a.mp3", tmp_path / "b.mp3"
    a.write_bytes(b"x"), b.write_bytes(b"y")
    os.utime(a, (100, 100)), os.utime(b, (200, 200))
    monkeypatch.setattr(transcriber, "REC_DIR", str(tmp_path))
    real_glob = transcriber.glob.glob
    # the glob still lists a clip that cleanup removed a moment later
    monkeypatch.setattr(transcriber.glob, "glob",
                        lambda pat: real_glob(pat) + [str(tmp_path / "gone.mp3")])
    clips = transcriber.list_clips()
    assert [os.path.basename(f) for f, _ in clips] == ["a.mp3", "b.mp3"]
    assert clips[0][1] == 100
