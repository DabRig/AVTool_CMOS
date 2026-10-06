"""End-to-end tests with the stand-in 'test' engine (no model download needed).

Run:  python -m pytest -q
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from avtool.cli import clean_dragged_path, main  # noqa: E402
from avtool.backends import Segment, Word  # noqa: E402
from avtool.media import choose_track, probe, scan  # noqa: E402
from avtool.text import CAPTION_PRESETS, build_cues, clean_segments, load_glossary  # noqa: E402
from avtool.writers import render_srt  # noqa: E402

FORMATS = [".txt", ".timestamped.txt", ".srt", ".vtt", ".docx", ".json"]


@pytest.fixture(scope="session")
def clip_source(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("clips")
    subprocess.run([sys.executable, str(ROOT / "samples" / "make_samples.py"), "--out", str(out)],
                   check=True, capture_output=True)
    return out


@pytest.fixture
def clips(clip_source, tmp_path) -> Path:
    """A fresh copy of the sample clips for each test."""
    dst = tmp_path / "clips with spaces"
    shutil.copytree(clip_source, dst)
    return dst


def run_tool(*args, tmp_path: Path) -> int:
    temp = tmp_path / "temp"
    return main([*map(str, args), "--backend", "test", "--lang", "en",
                 "--temp-dir", str(temp), "--no-keep-awake", "--glossary", str(ROOT / "glossary.txt")])


def temp_leftovers(tmp_path: Path) -> list[Path]:
    base = tmp_path / "temp" / "avtool_cmos"
    return [p for p in base.rglob("*") if p.is_file()] if base.exists() else []


# ------------------------------------------------------------------ batch

def test_full_batch_every_format(clips, tmp_path, capsys):
    code = run_tool(clips, tmp_path=tmp_path)
    assert code == 1  # one file (corrupt.mov) failed, so the exit code says so...
    out = capsys.readouterr().out
    assert "done 14" in out and "skipped 1" in out and "failed 1" in out  # ...but the batch finished

    for name in ["sample.mov", "sample.mp4", "sample.mkv", "sample.webm", "sample.wmv",
                 "sample.mp3", "sample.wav", "sample.flac", "sample.aac", "sample.m4a",
                 "CAMERA_CLIP.MOV", "Évan’s talk 🎤 (take 2).mp4", "two_tracks.mov", "silent.mp4"]:
        for suffix in FORMATS:
            assert (clips / (name + suffix)).is_file(), name + suffix

    # sample.mov and sample.mp4 share a base name but don't overwrite each other
    assert json.loads((clips / "sample.mov.json").read_text())["source"]["name"] == "sample.mov"
    assert json.loads((clips / "sample.mp4.json").read_text())["source"]["name"] == "sample.mp4"

    # junk, broken and silent files
    assert not list(clips.glob("._sample.mov.*")) and not list(clips.glob(".hidden.mov.*"))
    assert not list(clips.glob("corrupt.mov.*")) and not list(clips.glob("no_audio.mp4.*"))
    assert (clips / "silent.mp4.txt").read_text().strip() == "(No speech detected.)"
    assert json.loads((clips / "silent.mp4.json").read_text())["speech_found"] is False

    log = (clips / "log.txt").read_text()
    assert "FAILED | corrupt.mov" in log and "SKIPPED | no_audio.mp4 | no audio track" in log
    assert "DONE | sample.mov" in log
    assert not list(clips.glob("*.partial"))
    assert temp_leftovers(tmp_path) == []


def test_resume_skips_finished_and_force_redoes(clips, tmp_path, capsys):
    run_tool(clips / "sample.wav", tmp_path=tmp_path)
    first = (clips / "sample.wav.json").stat().st_mtime_ns
    capsys.readouterr()
    run_tool(clips / "sample.wav", tmp_path=tmp_path)
    assert "already done" in capsys.readouterr().out
    assert (clips / "sample.wav.json").stat().st_mtime_ns == first
    run_tool(clips / "sample.wav", "--force", tmp_path=tmp_path)
    assert (clips / "sample.wav.json").stat().st_mtime_ns != first


def test_not_done_without_json(clips, tmp_path):
    """A transcript without its .json (crash mid-write) is redone, not skipped."""
    (clips / "sample.flac.txt").write_text("half written")
    (clips / "sample.flac.srt.partial").write_text("junk")
    run_tool(clips / "sample.flac", tmp_path=tmp_path)
    assert (clips / "sample.flac.json").exists()
    assert (clips / "sample.flac.txt").read_text() != "half written"
    assert not (clips / "sample.flac.srt.partial").exists()


def test_interrupt_leaves_nothing_half_done(clips, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AVTOOL_TEST_INTERRUPT_AT", "3")
    code = run_tool(clips, tmp_path=tmp_path)
    assert code == 130
    assert "continue where it left off" in capsys.readouterr().out
    assert not list(clips.glob("*.json")) and not list(clips.glob("*.partial"))
    assert temp_leftovers(tmp_path) == []
    monkeypatch.delenv("AVTOOL_TEST_INTERRUPT_AT")
    assert run_tool(clips, tmp_path=tmp_path) == 1  # resumes and finishes (corrupt.mov still fails)
    assert len(list(clips.glob("*.json"))) == 14


def test_one_failure_does_not_stop_the_batch(clips, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AVTOOL_TEST_FAIL_ON", "002.wav")  # the 2nd file's temp audio
    run_tool(clips, tmp_path=tmp_path)
    out = capsys.readouterr().out
    assert "simulated transcription failure" in out
    assert "done 13" in out and "failed 2" in out
    assert temp_leftovers(tmp_path) == []


def test_out_folder_and_recursive(clips, tmp_path):
    sub = clips / "day 2"
    sub.mkdir()
    shutil.copy(clips / "sample.mp3", sub / "sample.mp3")
    out = tmp_path / "transcripts"
    run_tool(clips, "--recursive", "--out", out, "--formats", "srt", tmp_path=tmp_path)
    assert (out / "sample.mp3.srt").exists() and (out / "day 2" / "sample.mp3.srt").exists()
    assert (out / "sample.mp3.json").exists()  # json is always written (resume marker)
    assert not (out / "sample.mp3.txt").exists()
    assert (out / "log.txt").exists() and not (clips / "log.txt").exists()


def test_audio_track_choice(clips, tmp_path):
    info = probe(clips / "two_tracks.mov")
    assert [t.number for t in info.audio_tracks] == [1, 2]
    assert choose_track(info, 0)[0].number == 1
    assert choose_track(info, 2)[0].number == 2
    track, warning = choose_track(info, 5)
    assert track.number == 1 and "only has 2" in warning
    run_tool(clips / "two_tracks.mov", "--audio-track", "2", tmp_path=tmp_path)
    assert json.loads((clips / "two_tracks.mov.json").read_text())["source"]["audio_track"] == 2


def test_dry_run_writes_nothing(clips, tmp_path, capsys):
    assert run_tool(clips, "--dry-run", tmp_path=tmp_path) == 0
    assert "Dry run" in capsys.readouterr().out
    assert not list(clips.glob("*.json")) and not (clips / "log.txt").exists()


def test_scan_rules(clips):
    names = [p.name for p in scan(clips)]
    assert "CAMERA_CLIP.MOV" in names  # case-insensitive extensions
    assert "._sample.mov" not in names and ".hidden.mov" not in names


def test_long_file_streams(tmp_path):
    """A 40-minute file goes through without Python ever holding it in memory."""
    src = tmp_path / "long.m4a"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i",
                    "sine=frequency=300:duration=2400", "-c:a", "aac", "-b:a", "32k", str(src)], check=True)
    assert run_tool(src, "--formats", "srt", tmp_path=tmp_path) == 0
    data = json.loads((tmp_path / "long.m4a.json").read_text())
    assert abs(data["source"]["duration_seconds"] - 2400) < 1
    assert data["captions"][-1]["end"] > 2390


# ------------------------------------------------------------------ captions & text

def _words(text: str, start=0.0, step=0.3) -> list[Word]:
    out = []
    for i, w in enumerate(text.split()):
        out.append(Word(start + i * step, start + i * step + step * 0.9, " " + w))
    return out


def test_captions_follow_spec_limits():
    text = ("So the main thing I want to get across today is that scaling smoothly is about "
            "systems, not heroics, and it starts with the boring stuff nobody wants to do. "
            "Questions? Yes, in the back. Supercalifragilisticexpialidociousness happens.")
    segs = [Segment(0, 30, text, _words(text))]
    for name, style in CAPTION_PRESETS.items():
        cues = build_cues(segs, style)
        assert cues
        for i, c in enumerate(cues):
            assert len(c.lines) <= style.max_lines, name
            # a single word longer than a line (e.g. a URL) is allowed to overflow
            assert all(len(line) <= style.max_chars or " " not in line for line in c.lines), (name, c.lines)
            assert c.end - c.start <= style.max_seconds + 1e-6
            assert c.end > c.start
            if i:
                assert c.start >= cues[i - 1].end - 1e-6  # no overlaps
        joined = " ".join(" ".join(c.lines) for c in cues)
        assert joined.split() == text.split()  # nothing lost or reordered


def test_captions_split_on_pauses():
    a, b = _words("Hello there."), _words("Next part after a pause", start=5.0)
    cues = build_cues([Segment(0, 1, "Hello there.", a), Segment(5, 7, "x", b)], CAPTION_PRESETS["standard"])
    assert cues[0].lines == ["Hello there."]
    assert cues[0].end <= 5.0 and cues[1].start == pytest.approx(5.0)


def test_srt_format_is_valid():
    segs = [Segment(0, 2, "Hi there.", _words("Hi there."))]
    srt = render_srt(build_cues(segs, CAPTION_PRESETS["standard"]))
    assert re.fullmatch(r"1\n\d\d:\d\d:\d\d,\d{3} --> \d\d:\d\d:\d\d,\d{3}\nHi there\.\n", srt)


def test_glossary(tmp_path):
    g = tmp_path / "g.txt"
    g.write_text("# comment\nEvan\nLightning OS\nlightening os -> Lightning OS\nSmooth Scaling\n")
    gl = load_glossary(g)
    assert gl.terms == ["Evan", "Lightning OS", "Smooth Scaling"]
    assert gl.prompt == "Evan, Lightning OS, Smooth Scaling."
    assert gl.apply("welcome to smooth scaling and lightening-OS, says evan") == \
        "welcome to Smooth Scaling and Lightning OS, says Evan"
    assert gl.apply("Evangelist") == "Evangelist"  # whole words only


def test_cleanup_removes_phantoms_and_loops():
    segs = [
        Segment(0, 2, " Real words here.", avg_logprob=-0.2, no_speech_prob=0.01),
        Segment(2, 4, " Thanks for watching!", avg_logprob=-0.9, no_speech_prob=0.5),
        Segment(4, 6, " Same line.", avg_logprob=-0.3),
        Segment(6, 8, " Same line.", avg_logprob=-0.3),
        Segment(8, 10, " Same line.", avg_logprob=-0.3),
        Segment(10, 12, " Same line.", avg_logprob=-0.3),
        Segment(12, 14, " mumble", avg_logprob=-1.5, no_speech_prob=0.9),
        Segment(14, 16, " Evan, Lightning OS, Smooth Scaling.", avg_logprob=-0.5),
        Segment(16, 18, " Lightning OS.", avg_logprob=-0.3),  # really said: keep it
    ]
    kept = [s.text for s in clean_segments(segs, "Evan, Lightning OS, Smooth Scaling.")]
    assert kept == ["Real words here.", "Same line.", "Same line.", "Lightning OS."]


def test_dragged_paths():
    if os.name != "nt":
        assert clean_dragged_path("/Volumes/LaCie/My\\ Shoot/IMG\\ 1.MOV ") == "/Volumes/LaCie/My Shoot/IMG 1.MOV"
        assert clean_dragged_path("'/Volumes/LaCie/My Shoot'") == "/Volumes/LaCie/My Shoot"
