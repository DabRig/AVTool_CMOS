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
# Windows without Developer Mode can't make symlinks; the model cache copies instead. Fine.
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

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
                # ctranslate2 loads cuDNN by name at run time, which searches PATH.
                if str(bin_dir) not in os.environ.get("PATH", ""):
                    os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ.get("PATH", "")


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
                load_wav_array(wav),  # hand over the sound itself: mlx never needs ffmpeg
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


def load_wav_array(wav: Path):
    """Read our own 16 kHz mono 16-bit temp WAV into the float array Whisper uses.

    Exactly what mlx-whisper would do itself, minus running the `ffmpeg`
    program (which can't always be found when the app is opened from Finder).
    The WAV is small: ~115 MB per hour, ~230 MB per hour as floats.
    """
    import numpy as np
    with wave.open(str(wav), "rb") as w:
        if (w.getframerate(), w.getnchannels(), w.getsampwidth()) != (16000, 1, 2):
            raise ValueError("unexpected temp audio format")
        frames = w.readframes(w.getnframes())
    return np.frombuffer(frames, np.int16).astype(np.float32) / 32768.0


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

_GPU_TEST_SCRIPT = r"""
import sys
import numpy as np
sys.path.insert(0, sys.argv[2])
from avtool.backends import _add_windows_cuda_dlls
_add_windows_cuda_dlls()
from faster_whisper import WhisperModel
noise = (np.random.default_rng(0).standard_normal(16000 * 2) * 0.01).astype(np.float32)
for compute_type in ("float16", "float32"):  # older cards may lack fast float16
    try:
        model = WhisperModel(sys.argv[1], device="cuda", compute_type=compute_type)
    except ValueError as exc:
        if "float16" in str(exc) and compute_type == "float16":
            continue
        raise
    segments, _ = model.transcribe(noise, language="en", vad_filter=False, word_timestamps=True)
    list(segments)
    print("GPU-OK", compute_type)
    break
"""
_gpu_test_result: dict = {}


def gpu_selftest(model_path: str) -> tuple[bool, str]:
    """Try the NVIDIA engine in a separate, throwaway process first.

    Returns (works, detail): the compute type to use if it works, else the reason.

    A missing or mismatched NVIDIA library (cuDNN, cuBLAS) can make the GPU engine
    crash the whole program with no error to catch. Testing in a child process
    means only the child dies; the app then uses the CPU instead. Runs once per
    session (about 10-20 seconds, while the model loads).
    """
    if os.environ.get("AVTOOL_SKIP_GPU_TEST"):
        return True, "float16"
    if model_path in _gpu_test_result:
        return _gpu_test_result[model_path]
    project = str(Path(__file__).resolve().parent.parent)
    try:
        proc = subprocess.run(
            [sys.executable, "-c", _GPU_TEST_SCRIPT, model_path, project],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        ok = proc.returncode == 0 and "GPU-OK" in proc.stdout
        lines = [l for l in (proc.stderr or "").strip().splitlines() if l.strip()]
        if ok:
            words = proc.stdout.split("GPU-OK", 1)[1].split()
            detail = words[0] if words else "float16"  # the compute type that worked
        else:
            detail = lines[-1] if lines else f"GPU test exited with code {proc.returncode}"
    except subprocess.TimeoutExpired:
        ok, detail = False, "GPU test took too long"
    _gpu_test_result[model_path] = (ok, detail)
    return ok, detail


def _looks_like_gpu_failure(exc: BaseException) -> bool:
    text = str(exc).lower()
    return any(k in text for k in ("cuda", "cudnn", "cublas", "out of memory", "gpu", "device"))


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

    def _use_cpu(self, reason: str) -> None:
        print(f"NVIDIA GPU unavailable ({reason}). Using the CPU instead (works, slower).")
        self.device, self.compute_type = "cpu", "int8"
        self.name = "faster-whisper CPU"
        self.model = None

    def load(self) -> None:
        self.ensure_model()
        from faster_whisper import WhisperModel
        _add_windows_cuda_dlls()
        if self.device == "cuda":
            print("Checking the NVIDIA GPU (first start of each session only)...")
            ok, detail = gpu_selftest(self.local_path)
            if not ok:
                self._use_cpu(detail)
            elif detail in ("float16", "float32"):
                self.compute_type = detail
        try:
            self.model = WhisperModel(
                self.local_path, device=self.device, compute_type=self.compute_type,
                cpu_threads=os.cpu_count() or 4,
            )
        except Exception as exc:
            if self.device != "cuda":
                raise
            self._use_cpu(f"didn't start: {exc}")
            self.load()

    def transcribe(self, wav, duration, language, prompt, progress) -> Transcript:
        if self.model is None:
            self.load()
        try:
            return self._transcribe(wav, duration, language, prompt, progress)
        except Exception as exc:
            # e.g. the graphics card runs out of memory mid-file: redo this file on the CPU.
            if self.device != "cuda" or not _looks_like_gpu_failure(exc):
                raise
            self._use_cpu(f"failed mid-file: {exc}")
            self.load()
            return self._transcribe(wav, duration, language, prompt, progress)

    def _transcribe(self, wav, duration, language, prompt, progress) -> Transcript:
        seg_iter, info = self.model.transcribe(
            # Hand over the sound itself. Given a file name, faster-whisper opens
            # it with PyAV, and PyAV 19 removed an option faster-whisper 1.2.1
            # still passes ("metadata_errors"), so every file failed on Windows.
            load_wav_array(wav),
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
