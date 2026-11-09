"""The real faster-whisper engine (the one Windows and Intel Macs use), run end to
end with a tiny randomly-initialised model built locally (tests/tiny_whisper.py).

The other tests use a stand-in engine; that's how the V2.0 Windows failure
("open() got an unexpected keyword argument 'metadata_errors'") slipped through.
These run faster-whisper's own code: audio input, voice detection, decoding,
word timings, glossary hotwords.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

pytest.importorskip("faster_whisper")
pytest.importorskip("ctranslate2")

from avtool.cli import main  # noqa: E402
import tiny_whisper  # noqa: E402


@pytest.fixture(scope="module")
def tiny_model(tmp_path_factory) -> Path:
    return tiny_whisper.build(tmp_path_factory.mktemp("tiny-whisper"))


def _run(source: Path, model: Path, out: Path, tmp: Path) -> int:
    return main([str(source), "--backend", "cpu", "--model", str(model), "--out", str(out),
                 "--lang", "en", "--no-keep-awake", "--temp-dir", str(tmp / "temp"),
                 "--glossary", str(ROOT / "glossary.txt")])


def test_m4a_through_faster_whisper(tiny_model, tmp_path):
    src = tmp_path / "11-8-26 - Deciding on Price.m4a"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=300:duration=6",
                    "-c:a", "aac", str(src)], check=True)
    out = tmp_path / "out"
    assert _run(src, tiny_model, out, tmp_path) == 0
    data = json.loads((out / (src.name + ".json")).read_text(encoding="utf-8"))
    assert "faster-whisper CPU" in data["model"]
    for suffix in (".txt", ".srt", ".vtt", ".timestamped.txt", ".docx"):
        assert (out / (src.name + suffix)).exists(), suffix


@pytest.mark.skipif(not shutil.which("espeak-ng"), reason="needs espeak-ng for spoken test audio")
def test_speech_reaches_decoder_and_word_timings(tiny_model, tmp_path):
    wav = tmp_path / "speech.wav"
    subprocess.run(["espeak-ng", "-s", "150", "-w", str(wav),
                    "Hi everyone, I'm Evan. Welcome to the Smooth Scaling workshop. Any questions?"], check=True)
    src = tmp_path / "talk.m4a"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(wav), "-af", "apad=pad_dur=2",
                    "-c:a", "aac", str(src)], check=True)
    out = tmp_path / "out"
    assert _run(src, tiny_model, out, tmp_path) == 0
    data = json.loads((out / "talk.m4a.json").read_text(encoding="utf-8"))
    assert data["segments"], "voice detection should find the speech and the decoder should run"
    assert any(seg["words"] for seg in data["segments"]), "word timings missing"
    assert data["captions"]


def test_gpu_failure_falls_back_to_cpu(tiny_model, tmp_path, capsys):
    """No usable NVIDIA GPU (here: none at all). The GPU check runs in a throwaway
    process, fails safely, and the file is transcribed on the CPU instead."""
    from avtool.backends import FasterWhisperBackend, load_wav_array  # noqa: F401
    b = FasterWhisperBackend(str(tiny_model), "cuda")
    b.load()
    out = capsys.readouterr().out
    assert "Checking the NVIDIA GPU" in out and "Using the CPU instead" in out
    assert b.device == "cpu" and b.name == "faster-whisper CPU" and b.model is not None
    wav = tmp_path / "a.wav"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=300:duration=3",
                    "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(wav)], check=True)
    assert b.transcribe(wav, 3.0, "en", None, None).language == "en"
