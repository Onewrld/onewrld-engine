"""Phase 3.2: dead-air cuts, word timing after cuts, word-by-word captions, SRT, and a real
render of a spoken clip with known word timings (no speech model needed)."""

import shutil

import pytest

from onewrld import speech, studio
from onewrld.speech import Word

W = [Word("Heavy", 0.6, 1.0), Word("cotton.", 1.1, 1.6),       # 2.4s pause follows
     Word("Built", 4.0, 4.3), Word("to", 4.35, 4.5), Word("last.", 4.55, 5.0)]


def test_long_pauses_are_cut_short_ones_kept():
    segs = speech.keep_segments(W, duration=8.0)
    assert len(segs) == 2                       # one cut, between "cotton." and "Built"
    assert segs[0][0] == pytest.approx(0.48)    # leading dead air removed (padding kept)
    assert segs[-1][1] == pytest.approx(5.12)   # trailing dead air removed


def test_every_word_survives_the_cuts_and_keeps_its_length():
    segs = speech.keep_segments(W, duration=8.0)
    new = speech.remap(W, segs)
    assert [w.text for w in new] == [w.text for w in W]
    for old, nw in zip(W, new):
        assert nw.end - nw.start == pytest.approx(old.end - old.start, abs=1e-3)
    # the 2.4s pause shrank to just the padding on each side
    assert new[2].start - new[1].end == pytest.approx(2 * speech.PAD, abs=0.01)


def test_no_words_keeps_everything():
    assert speech.keep_segments([], duration=5.0) == [(0.0, 5.0)]


def test_chunks_break_at_sentence_ends():
    assert [[w.text for w in c] for c in speech.chunks(W)] == [["Heavy", "cotton."],
                                                              ["Built", "to", "last."]]


def test_ass_highlights_one_word_at_a_time():
    events = speech.ass_events(W)
    assert len(events) == len(W)
    assert all(e.count("\\c&H00FFFFFF&") == 1 for e in events)  # exactly one white word
    assert "{\\c&H00FFFFFF&}Built" in events[2]


def test_srt_sidecar(tmp_path):
    text = speech.write_srt(W, tmp_path / "a.srt").read_text()
    assert "00:00:00,600 --> 00:00:01,600\nHeavy cotton." in text
    assert "Built to last." in text


def test_braces_in_speech_cant_break_subtitles():
    ev = speech.ass_events([Word("{weird}", 0, 1)])[0]
    assert "(weird)" in ev


def test_command_has_cuts_and_relative_subtitle_path(tmp_path):
    spec = studio.RenderSpec(speech_captions=True, cut_silence=True, caption="post text")
    cmd = studio.build_command(tmp_path / "in.mp4", {"duration": 8.0, "has_audio": True},
                               spec, tmp_path / "out.mp4", tmp_path, words=W)
    fc = cmd[cmd.index("-filter_complex") + 1]
    assert "select='between(t," in fc and "aselect='between(t," in fc
    assert "subtitles=captions.ass:fontsdir=fonts" in fc  # relative: safe on Windows
    assert (tmp_path / "captions.ass").exists() and (tmp_path / "fonts").is_dir()
    assert not (tmp_path / "caption.png").exists()  # static caption not burned in


def test_speech_needs_words(tmp_path):
    from onewrld.errors import PermanentError
    with pytest.raises(PermanentError):
        studio.build_command(tmp_path / "in.mp4", {"duration": 8.0, "has_audio": True},
                             studio.RenderSpec(cut_silence=True), tmp_path / "o.mp4", tmp_path)


def test_missing_speech_install_gives_plain_instructions(tmp_path, monkeypatch):
    from onewrld.errors import PermanentError
    monkeypatch.setattr(speech, "speech_available", lambda: False)
    with pytest.raises(PermanentError, match=r"\[speech\]"):
        speech.transcribe(tmp_path / "x.mp4", tmp_path, "sha")


def test_cached_transcript_is_reused_without_the_model(tmp_path, monkeypatch):
    import json
    (tmp_path / "abc.small.en.json").write_text(json.dumps([w.__dict__ for w in W]))
    monkeypatch.setattr(speech, "speech_available", lambda: False)  # model not even installed
    assert speech.transcribe(tmp_path / "x.mp4", tmp_path, "abc") == W


# --- real render with a synthesized talking clip ---------------------------------

def _flite():
    if not shutil.which("ffmpeg"):
        return False
    from spoken_clip import flite_available
    return flite_available()


@pytest.mark.skipif(not _flite(), reason="ffmpeg with flite text-to-speech not available")
def test_talking_clip_renders_with_cuts_and_word_captions(tmp_path):
    from spoken_clip import make_spoken_clip
    script = [("Heavy", 0.1), ("cotton.", 1.8), ("Built", 0.1), ("to", 0.1), ("last.", 1.5)]
    clip, words = make_spoken_clip(tmp_path / "src", script)
    src_dur = studio.probe(clip)["duration"]
    spec = studio.RenderSpec(speech_captions=True, cut_silence=True, look="bw")
    r = studio.render(clip, spec, tmp_path / "out", words_provider=lambda p, h: words)
    assert r["qc"]["passed"], r["qc"]["checks"]
    kept = sum(e - s for s, e in speech.keep_segments(words, src_dur))
    assert r["qc"]["info"]["duration"] == pytest.approx(kept + studio.END_CARD_SECONDS, abs=0.25)
    assert r["qc"]["info"]["duration"] < src_dur  # the pauses really were cut
    assert r["srt"] and "Built to last." in open(r["srt"]).read()
