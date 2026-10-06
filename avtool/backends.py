"""Whisper engines ("backends") and choosing the right one for this machine.

Pattern borrowed from Buzz (MIT): detect the hardware, pick the fastest
engine that runs on it, and let the user override the choice.

  Mac with Apple Silicon (M1-M4) -> mlx-whisper   (uses the Mac's GPU)
  NVIDIA GPU (Windows/Linux)     -> faster-whisper on CUDA, float16
  Anything else                  -> faster-whisper on CPU, int8 (slower, works)

Everything runs locally. The model is downloaded once; after that the
Hugging Face library is put in offline mode, so nothing leaves the machine.
"""

from __future__ import annotations

import contextlib
import importlib
import importlib.util
import os
import platform
import subprocess
import sys
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

# Never send usage statistics anywhere.
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

MLX_MODELS = {
    "tiny": "mlx-community/whisper-tiny-mlx",
    "tiny.en": "mlx-community/whisper-tiny.en-mlx",
    "base": "mlx-community/whisper-base-mlx",
    "base.en": "mlx-community/whisper-base.en-mlx",
    "small": "mlx-community/whisper-small-mlx",
    "small.en": "mlx-community/whisper-small.en-mlx",
    "medium": "mlx-community/whisper-medium-mlx",
    "medium.en": "mlx-community/whisper-medium.en-mlx",
    "large-v3": "mlx-community/whisper-large-v3-mlx",
    "large-v3-turbo": "mlx-community/whisper-large-v3-turbo",
    "turbo": "mlx-community/whisper-large-v3-turbo",
}

# Settings that stop Whisper inventing text over silence or looping a line.
HALLUCINATION_SILENCE_SECONDS = 2.0


# ---------------------------------------------------------------- data

@dataclass
class Word:
    start: float
    end: float
    text: str
    probability: float = 1.0


@dataclass
class Segment:
    start: float
    end: float
    text: str
    words: list[Word] = field(default_factory=list)
    avg_logprob: float = 0.0
    no_speech_prob: float = 0.0
    compression_ratio: float = 1.0


@dataclass
class Transcript:
    segments: list[Segment]
    language: Optional[str]


ProgressFn = Callable[[float], None]  # seconds of audio done


# ---------------------------------------------------------------- hardware

def is_apple_silicon() -> bool:
    return sys.platform == "darwin" and platform.machine() == "arm64"


def running_under_rosetta() -> bool:
    """True when an Intel copy of Python runs on an Apple Silicon Mac (slow, no MLX)."""
    if sys.platform != "darwin" or platform.machine() == "arm64":
        return False
    try:
        out = subprocess.run(
            ["sysctl", "-n", "sysctl.proc_translated"],
            capture_output=True, text=True, timeout=5,
        ).stdout.strip()
        return out == "1"
    except (OSError, subprocess.SubprocessError):
        return False


def has_module(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def _add_windows_cuda_dlls() -> None:
    """pip's nvidia-* packages put their DLLs where Windows won't look by default."""
    if sys.platform != "win32":
        return
    for base in map(Path, sys.path):
        nvidia = base / "nvidia"
        if nvidia.is_dir():
            for bin_dir in nvidia.glob("*/bin"):
                with contextlib.suppress(OSError):
                    os.add_dll_directory(str(bin_dir))


def cuda_device_count() -> int:
    if not has_module("ctranslate2"):
        return 0
    _add_windows_cuda_dlls()
    try:
        import ctranslate2
        return ctranslate2.get_cuda_device_count()
    except Exception:
        return 0


def resolve_backend(choice: str) -> str:
    """Turn 'auto' into a concrete backend: 'mlx', 'cuda' or 'cpu'."""
    choice = (choice or "auto").lower()
    if choice in ("mlx", "cuda", "cpu", "test"):
        return choice
    if choice in ("faster-whisper", "faster_whisper"):
        return "cuda" if cuda_device_count() else "cpu"
    if choice != "auto":
        raise ValueError(f"Unknown backend '{choice}'. Use auto, mlx, cuda or cpu.")
    if is_apple_silicon() and has_module("mlx_whisper"):
        return "mlx"
    if has_module("faster_whisper"):
        return "cuda" if cuda_device_count() else "cpu"
    if is_apple_silicon():
        raise RuntimeError("mlx-whisper isn't installed. Run setup_mac.command.")
    raise RuntimeError("No Whisper engine installed. Run the setup script (see README).")


# ---------------------------------------------------------------- base class

class Backend:
    name = "base"

    def __init__(self, model: str):
        self.model_name = model

    def label(self) -> str:
        return f"{self.model_name} ({self.name})"

    def ensure_model(self, allow_download: bool = True) -> None:
        """Make sure the model is on disk; download it once if needed."""

    def load(self) -> None:
        """Load the model into memory (done once per batch)."""

    def transcribe(
        self, wav: Path, duration: float, language: Optional[str],
        prompt: Optional[str], progress: Optional[ProgressFn],
    ) -> Transcript:
        raise NotImplementedError


def _offline_mode(offline: bool = True) -> None:
    """Once the model is cached, forbid the Hugging Face library from going online.
    Lifted (offline=False) only for an intended one-time model download."""
    os.environ["HF_HUB_OFFLINE"] = "1" if offline else "0"
    with contextlib.suppress(Exception):
        import huggingface_hub.constants as hf_constants
        hf_constants.HF_HUB_OFFLINE = offline


# ---------------------------------------------------------------- MLX (Mac)

class MLXBackend(Backend):
    name = "mlx"

    def __init__(self, model: str):
        super().__init__(model)
        self.repo = model if "/" in model else MLX_MODELS.get(model)
        if not self.repo:
            raise ValueError(
                f"Unknown model '{model}'. Try one of: " + ", ".join(MLX_MODELS)
            )
        self.local_path: Optional[str] = None

    def ensure_model(self, allow_download: bool = True) -> None:
        if Path(self.repo).exists():  # a folder on disk
            self.local_path = self.repo
            return
        from huggingface_hub import snapshot_download
        try:
            self.local_path = snapshot_download(self.repo, local_files_only=True)
            folder = Path(self.local_path)
            if not (folder / "config.json").exists() or not (
                (folder / "weights.safetensors").exists() or (folder / "weights.npz").exists()
            ):
                raise FileNotFoundError("model download incomplete")
        except Exception:
            if not allow_download:
                raise RuntimeError(
                    f"Model {self.repo} isn't downloaded yet. Connect to the internet "
                    f"once and run: python transcribe.py --download-model"
                )
            print(f"Downloading the model {self.repo} (one time only, up to 1.6 GB)...")
            _offline_mode(False)
            self.local_path = snapshot_download(self.repo)
        _offline_mode()

    def load(self) -> None:
        self.ensure_model()
        import mlx.core as mx
        transcribe_module = importlib.import_module("mlx_whisper.transcribe")
        transcribe_module.ModelHolder.get_model(self.local_path, mx.float16)

    def transcribe(self, wav, duration, language, prompt, progress) -> Transcript:
        import mlx_whisper
        transcribe_module = importlib.import_module("mlx_whisper.transcribe")
        with _glossary_on_every_window(transcribe_module, prompt), \
                _report_progress(transcribe_module, progress):
            result = mlx_whisper.transcribe(
                str(wav),
                path_or_hf_repo=self.local_path or self.repo,
                verbose=False,  # progress bar on; _report_progress reroutes it to ours
                language=language,
                condition_on_previous_text=False,
                word_timestamps=True,
                hallucination_silence_threshold=HALLUCINATION_SILENCE_SECONDS,
                initial_prompt=prompt or None,
            )
        segments = []
        for seg in result.get("segments", []):
            words = [
                Word(float(w["start"]), float(w["end"]), str(w["word"]),
                     float(w.get("probability", 1.0)))
                for w in seg.get("words", []) or []
            ]
            segments.append(Segment(
                float(seg["start"]), float(seg["end"]), str(seg["text"]), words,
                float(seg.get("avg_logprob", 0.0)),
                float(seg.get("no_speech_prob", 0.0)),
                float(seg.get("compression_ratio", 1.0)),
            ))
        return Transcript(segments, result.get("language"))


@contextlib.contextmanager
def _glossary_on_every_window(module, prompt: Optional[str]):
    """Keep the glossary active for the whole file, not just the first 30 seconds.

    mlx-whisper forgets `initial_prompt` after the first 30-second window when
    condition_on_previous_text=False (which we need, to stop looping). This
    re-applies the glossary to every window whose prompt would be empty, the
    same way faster-whisper's `hotwords` work. If a future mlx-whisper changes
    its internals, this quietly does nothing and the first window still gets
    the glossary.
    """
    original = getattr(module, "DecodingOptions", None)
    if not prompt or original is None:
        yield
        return

    def with_glossary(*args, **kwargs):
        if not kwargs.get("prompt"):
            kwargs["prompt"] = prompt
        return original(*args, **kwargs)

    module.DecodingOptions = with_glossary
    try:
        yield
    finally:
        module.DecodingOptions = original


@contextlib.contextmanager
def _report_progress(module, progress: Optional[ProgressFn]):
    """Route mlx-whisper's internal progress bar into our own progress display.

    mlx-whisper counts "frames" (100 per second of audio) on a tqdm bar. This
    swaps in a stand-in bar for the duration of one transcription, converts
    frames to seconds and passes them on. Restored afterwards; if mlx-whisper
    changes its internals, transcription still works, just without live progress.
    """
    original = getattr(module, "tqdm", None)
    if progress is None or original is None:
        yield
        return

    class _Bar:
        def __init__(self, *args, total=None, **kwargs):
            self.done = 0

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def update(self, n=1):
            self.done += n
            progress(self.done / 100.0)

        def close(self):
            pass

    module.tqdm = type("tqdm_shim", (), {"tqdm": _Bar})
    try:
        yield
    finally:
        module.tqdm = original


# ---------------------------------------------------------------- faster-whisper

class FasterWhisperBackend(Backend):
    def __init__(self, model: str, device: str):
        super().__init__(model)
        self.device = device
        self.name = "faster-whisper " + ("CUDA" if device == "cuda" else "CPU")
        self.compute_type = "float16" if device == "cuda" else "int8"
        self.local_path: Optional[str] = None
        self.model = None

    def ensure_model(self, allow_download: bool = True) -> None:
        if Path(self.model_name).exists():
            self.local_path = self.model_name
            return
        from faster_whisper import download_model
        try:
            self.local_path = download_model(self.model_name, local_files_only=True)
            if not (Path(self.local_path) / "model.bin").exists():
                raise FileNotFoundError("model download incomplete")
        except Exception:
            if not allow_download:
                raise RuntimeError(
                    f"Model {self.model_name} isn't downloaded yet. Connect to the "
                    f"internet once and run: python transcribe.py --download-model"
                )
            print(f"Downloading the model {self.model_name} (one time only, up to 1.6 GB)...")
            _offline_mode(False)
            self.local_path = download_model(self.model_name)
        _offline_mode()

    def load(self) -> None:
        self.ensure_model()
        from faster_whisper import WhisperModel
        _add_windows_cuda_dlls()
        try:
            self.model = WhisperModel(
                self.local_path, device=self.device, compute_type=self.compute_type,
                cpu_threads=os.cpu_count() or 4,
            )
        except Exception as exc:
            if self.device != "cuda":
                raise
            print(f"NVIDIA GPU didn't start ({exc}). Falling back to CPU (slower).")
            self.device, self.compute_type = "cpu", "int8"
            self.name = "faster-whisper CPU"
            self.load()

    def transcribe(self, wav, duration, language, prompt, progress) -> Transcript:
        if self.model is None:
            self.load()
        seg_iter, info = self.model.transcribe(
            str(wav),
            language=language,
            beam_size=5,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 500},
            condition_on_previous_text=False,
            word_timestamps=True,
            hallucination_silence_threshold=HALLUCINATION_SILENCE_SECONDS,
            hotwords=prompt or None,
        )
        segments = []
        for seg in seg_iter:  # a generator: transcription happens as we loop
            words = [
                Word(float(w.start), float(w.end), str(w.word), float(w.probability))
                for w in (seg.words or [])
            ]
            segments.append(Segment(
                float(seg.start), float(seg.end), str(seg.text), words,
                float(seg.avg_logprob), float(seg.no_speech_prob),
                float(seg.compression_ratio),
            ))
            if progress:
                progress(min(float(seg.end), duration))
        return Transcript(segments, getattr(info, "language", None))


# ---------------------------------------------------------------- test engine

class TestBackend(Backend):
    """A stand-in used by the automated tests, so they run without a 1.6 GB model.

    It doesn't understand speech: it reads the WAV in small chunks and writes a
    placeholder word wherever the audio isn't silent. That's enough to exercise
    everything around the transcriber (extraction, captions, outputs, resume).
    """

    name = "test"
    CHUNK = 0.4  # seconds per placeholder word
    WORDS = ("alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf", "hotel")

    def transcribe(self, wav, duration, language, prompt, progress) -> Transcript:
        if os.environ.get("AVTOOL_TEST_FAIL_ON") and os.environ["AVTOOL_TEST_FAIL_ON"] in str(wav):
            raise RuntimeError("simulated transcription failure")
        words: list[Word] = []
        with wave.open(str(wav), "rb") as w:
            rate = w.getframerate()
            frames_per_chunk = int(rate * self.CHUNK)
            index = 0
            while True:
                raw = w.readframes(frames_per_chunk)  # small chunk, never the whole file
                if not raw:
                    break
                samples = memoryview(raw).cast("h")
                peak = max((abs(s) for s in samples), default=0)
                start = index * self.CHUNK
                if peak > 600:
                    text = self.WORDS[len(words) % len(self.WORDS)]
                    words.append(Word(start, start + self.CHUNK * 0.9, " " + text))
                index += 1
                if progress:
                    progress(min(start + self.CHUNK, duration))
                if os.environ.get("AVTOOL_TEST_DELAY"):  # slow motion, for demos of the app
                    import time
                    time.sleep(float(os.environ["AVTOOL_TEST_DELAY"]))
                if os.environ.get("AVTOOL_TEST_INTERRUPT_AT") and start >= float(os.environ["AVTOOL_TEST_INTERRUPT_AT"]):
                    raise KeyboardInterrupt
        segments: list[Segment] = []
        for i in range(0, len(words), 9):
            chunk = words[i:i + 9]
            chunk[-1].text += "."
            segments.append(Segment(
                chunk[0].start, chunk[-1].end, "".join(w.text for w in chunk), chunk,
            ))
        return Transcript(segments, language or "en")


def make_backend(choice: str, model: str) -> Backend:
    kind = resolve_backend(choice)
    if kind == "mlx":
        return MLXBackend(model)
    if kind == "test":
        return TestBackend(model)
    return FasterWhisperBackend(model, kind)
