"""Running a whole batch: scan -> probe -> extract -> transcribe -> write.

Reliability rules this file enforces:
- One file at a time; one bad file is logged and the batch moves on.
- A file is "done" only when its .json exists, so a re-run resumes cleanly.
- Temp audio lives in the system temp folder (not on the external drive) and is
  deleted after every file, on errors, on Ctrl+C, and at the next start if the
  computer crashed.
- Disk space is checked before starting; the computer is kept awake meanwhile.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from . import __version__
from .backends import Backend, make_backend
from .media import (
    WAV_BYTES_PER_SECOND, AudioTrack, MediaError, NoAudioError, ProbeResult,
    choose_track, extract_audio, probe, scan,
)
from .text import CAPTION_PRESETS, Glossary, clean_segments, load_glossary
from .timefmt import human_bytes, human_duration
from .writers import FORMATS, done_marker, remove_partials, write_all

try:
    from tqdm import tqdm
except ImportError:  # progress bars are nice-to-have, not required
    tqdm = None


@dataclass
class Settings:
    path: Path
    model: str = "large-v3-turbo"
    lang: str = "auto"
    backend: str = "auto"
    audio_track: int = 0
    track_overrides: dict = field(default_factory=dict)
    recursive: bool = False
    out: Optional[Path] = None
    force: bool = False
    captions: str = "standard"
    glossary: Optional[Path] = None
    formats: list = field(default_factory=lambda: list(FORMATS))
    boost_quiet: bool = False
    keep_awake: bool = True
    dry_run: bool = False
    temp_root: Optional[Path] = None
    # Used by the app window (avtool/gui): an explicit file list instead of
    # scanning `path`, a listener for live events, and a Stop button.
    files: Optional[list] = None
    on_event: Optional[Callable] = None
    stop: Optional[threading.Event] = None


class StopRequested(KeyboardInterrupt):
    """The Stop button was pressed. Handled exactly like Ctrl+C."""


@dataclass
class Job:
    source: Path
    out_dir: Path
    status: str = "pending"  # pending | done | skipped | failed | interrupted
    note: str = ""
    info: Optional[ProbeResult] = None
    track: Optional[AudioTrack] = None
    seconds_taken: float = 0.0

    @property
    def duration(self) -> float:
        return (self.info.duration if self.info and self.info.duration else 0.0)


# ---------------------------------------------------------------- console + log

class Log:
    """log.txt next to the transcripts: one line per event, flushed immediately."""

    def __init__(self, path: Path):
        self.path = path
        self.file = open(path, "a", encoding="utf-8")

    def write(self, message: str) -> None:
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for line in message.rstrip().splitlines() or [""]:
            self.file.write(f"{stamp} | {line}\n")
        self.file.flush()

    def close(self) -> None:
        self.file.close()


_listener: Optional[Callable] = None
_stop: Optional[threading.Event] = None


def emit(kind: str, **data) -> None:
    """Send a live event to the app window, if one is listening."""
    if _listener is not None:
        try:
            _listener(kind, data)
        except Exception:
            pass  # a display problem must never break a transcription


def check_stop() -> None:
    if _stop is not None and _stop.is_set():
        raise StopRequested


def say(message: str = "") -> None:
    print(message, flush=True)
    emit("log", text=message)


def _bar(fraction: float, width: int = 24) -> str:
    filled = int(round(max(0.0, min(1.0, fraction)) * width))
    return "█" * filled + "░" * (width - filled)


class Progress:
    """A per-step progress bar measured in seconds of audio."""

    def __init__(self, label: str, total: float, on_update: Optional[Callable[[float], None]] = None):
        self.total = max(total, 0.001)
        self.on_update = on_update
        self.bar = None
        if tqdm is not None and sys.stderr.isatty():
            self.bar = tqdm(
                total=round(self.total, 1), desc=label, unit="s", leave=False,
                bar_format="  {desc}: {percentage:3.0f}%|{bar:24}| {n:.0f}/{total:.0f}s audio [{elapsed}<{remaining}]",
            )

    def update(self, seconds_done: float) -> None:
        check_stop()  # the Stop button takes effect within a second
        if self.on_update:
            self.on_update(min(seconds_done / self.total, 1.0))
        if self.bar is not None:
            self.bar.n = round(min(seconds_done, self.total), 1)
            self.bar.refresh()

    def close(self) -> None:
        if self.bar is not None:
            self.bar.close()


# ---------------------------------------------------------------- system helpers

def _pid_alive(pid: int) -> bool:
    if pid == os.getpid():
        return True
    if sys.platform == "win32":
        import ctypes
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def make_temp_dir(root: Optional[Path]) -> Path:
    """A private temp folder for this run, after clearing leftovers from crashed runs."""
    base = (root or Path(tempfile.gettempdir())) / "avtool_cmos"
    base.mkdir(parents=True, exist_ok=True)
    for old in base.glob("run-*"):
        try:
            pid = int(old.name.split("-", 1)[1])
        except ValueError:
            continue
        if not _pid_alive(pid):
            shutil.rmtree(old, ignore_errors=True)
    run_dir = base / f"run-{os.getpid()}"
    run_dir.mkdir(exist_ok=True)
    return run_dir


class KeepAwake:
    """Stop the computer sleeping mid-batch (caffeinate on Mac)."""

    def __init__(self, enabled: bool):
        self.enabled = enabled
        self.proc = None

    def __enter__(self):
        if not self.enabled:
            return self
        if sys.platform == "darwin" and shutil.which("caffeinate"):
            # -i: no idle sleep, -s: no system sleep on power, -w: stop when we exit
            self.proc = subprocess.Popen(
                ["caffeinate", "-i", "-s", "-w", str(os.getpid())],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        elif sys.platform == "win32":
            import ctypes
            ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001)
        return self

    def __exit__(self, *exc):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
        if self.enabled and sys.platform == "win32":
            import ctypes
            ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)
        return False


def _raise_interrupt(signum, frame):
    raise KeyboardInterrupt


def _check_writable(folder: Path) -> Optional[str]:
    try:
        folder.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=folder, prefix=".avtool-write-test-", delete=True):
            pass
        return None
    except OSError as exc:
        return f"Can't write to {folder} ({exc.strerror or exc})."


# ---------------------------------------------------------------- the batch

def plan_jobs(settings: Settings) -> tuple[list[Job], Path]:
    """Find the files and decide where each one's transcripts go."""
    if settings.files is not None:
        return _plan_explicit(settings)
    root = settings.path.expanduser().resolve()
    files = scan(root, settings.recursive)
    jobs = []
    for source in files:
        if settings.out:
            out_dir = settings.out.expanduser().resolve()
            if root.is_dir():  # mirror subfolders so same-named files can't collide
                out_dir = out_dir / source.parent.relative_to(root)
        else:
            out_dir = source.parent
        jobs.append(Job(source, out_dir))
    log_dir = settings.out.expanduser().resolve() if settings.out else (root if root.is_dir() else root.parent)
    return jobs, log_dir


def _plan_explicit(settings: Settings) -> tuple[list[Job], Path]:
    """The app window hands over an exact list of files (already scanned)."""
    sources = [Path(f).expanduser().resolve() for f in settings.files]
    out = settings.out.expanduser().resolve() if settings.out else None
    jobs = [Job(src, out or src.parent) for src in sources]
    if out:
        log_dir = out
    else:
        parents = [str(src.parent) for src in sources] or [str(settings.path)]
        try:
            log_dir = Path(os.path.commonpath(parents))
        except ValueError:
            log_dir = Path(parents[0])
        if len(log_dir.parts) <= 2:  # e.g. "/" or "/Volumes": too broad for a log
            log_dir = Path(parents[0])
    return jobs, log_dir


def run(settings: Settings) -> int:
    """Run a batch. Wires up the app window's listener and Stop button, if any."""
    global _listener, _stop
    _listener, _stop = settings.on_event, settings.stop
    try:
        return _run(settings)
    finally:
        _listener, _stop = None, None


def _run(settings: Settings) -> int:
    started = time.time()
    try:
        jobs, log_dir = plan_jobs(settings)
    except MediaError as exc:
        say(f"✗ {exc}")
        return 2

    say(f"\nAVTool CMOS {__version__} — offline transcription")
    say(f"Input:    {settings.path}")
    say(f"Outputs:  {settings.out or 'next to each file'}")
    if not jobs:
        say("No supported media files found. (Tip: --recursive includes subfolders.)")
        return 0

    write_problem = None
    if not settings.dry_run:
        for folder in sorted({log_dir, *(j.out_dir for j in jobs)}):
            write_problem = _check_writable(folder)
            if write_problem:
                break
    if write_problem:
        say(f"✗ {write_problem}")
        say("  If the files are on a drive the Mac can only read (e.g. NTFS-formatted),")
        say('  send the transcripts elsewhere:  --out "~/Documents/Transcripts"')
        return 2
    log = Log(log_dir / "log.txt") if not settings.dry_run else None

    def logline(msg: str) -> None:
        if log:
            log.write(msg)

    style = CAPTION_PRESETS[settings.captions]
    glossary: Glossary = load_glossary(settings.glossary)
    prompt = glossary.prompt
    language = None if settings.lang in ("", "auto") else settings.lang

    # 1) Probe every file that still needs doing (fast: only reads the header).
    say(f"\nChecking {len(jobs)} file(s)...")
    for job in jobs:
        if not settings.force and done_marker(job.out_dir, job.source).exists():
            job.status, job.note = "done-before", "already transcribed"
            continue
        try:
            job.info = probe(job.source)
            requested = int(settings.track_overrides.get(job.source.name, settings.audio_track) or 0)
            job.track, warning = choose_track(job.info, requested)
            if warning:
                job.note = warning
        except NoAudioError as exc:
            job.status, job.note = "skipped", str(exc)
        except MediaError as exc:
            job.status, job.note = "failed", str(exc)

    pending = [j for j in jobs if j.status == "pending"]
    total_audio = sum(j.duration for j in pending)
    width = min(max(len(j.source.name) for j in jobs), 44)
    for i, job in enumerate(jobs, 1):
        name = job.source.name if len(job.source.name) <= width else job.source.name[: width - 1] + "…"
        length = human_duration(job.info.duration) if job.info else ""
        state = {
            "pending": "ready" + (f" (audio track {job.track.number} of {len(job.info.audio_tracks)})"
                                  if job.info and len(job.info.audio_tracks) > 1 else ""),
            "done-before": "already done — skipping (use --force to redo)",
            "skipped": f"skip: {job.note}",
            "failed": f"can't read: {job.note}",
        }[job.status]
        say(f"  {i:>2}. {name:<{width}}  {length:>8}  {state}")
    say(f"\n{len(pending)} to transcribe · {human_duration(total_audio)} of audio")

    for job in jobs:
        if job.status in ("skipped", "failed"):
            logline(f"{job.status.upper()} | {job.source.name} | {job.note}")
    emit("plan", jobs=[{"path": str(j.source), "status": j.status, "note": j.note,
                        "duration": j.duration} for j in jobs])

    if settings.dry_run or not pending:
        if log:
            log.close()
        code = _summary(jobs, started, log_dir, settings.dry_run)
        emit("end", counts=_count_dict(jobs), interrupted=False, code=code)
        return code

    # 2) Disk space: the temp WAV for the longest file, twice over, plus margin.
    run_dir = make_temp_dir(settings.temp_root)
    largest_wav = max(j.duration for j in pending) * WAV_BYTES_PER_SECOND
    needed_temp = 2 * largest_wav + 50 * 1024**2
    free_temp = shutil.disk_usage(run_dir).free
    free_out = shutil.disk_usage(log_dir).free
    needed_out = total_audio / 3600 * 10 * 1024**2 + 20 * 1024**2  # ~10 MB per hour, generous
    if free_temp < needed_temp or free_out < needed_out:
        say(f"✗ Not enough free disk space. Temp needs {human_bytes(needed_temp)} "
            f"(free {human_bytes(free_temp)}); outputs need {human_bytes(needed_out)} "
            f"(free {human_bytes(free_out)}).")
        shutil.rmtree(run_dir, ignore_errors=True)
        log.close()
        return 2

    old_handlers = {}
    if threading.current_thread() is threading.main_thread():  # signals only work there
        for sig_name in ("SIGTERM", "SIGHUP"):  # closing the Terminal window = clean stop
            sig = getattr(signal, sig_name, None)
            if sig is not None:
                old_handlers[sig] = signal.signal(sig, _raise_interrupt)

    backend: Optional[Backend] = None
    interrupted = False
    try:
        with KeepAwake(settings.keep_awake):
            backend = make_backend(settings.backend, settings.model)
            say(f"\nEngine:   {backend.label()} · language: {settings.lang} · captions: {settings.captions}")
            if prompt:
                say(f"Glossary: {prompt}" + (" (trimmed: keep it short!)" if glossary.truncated else ""))
            say("Loading the model (the first time can take a minute)...")
            emit("loading", label=backend.label())
            backend.load()
            logline(f"RUN START | AVTool {__version__} | {backend.label()} | lang={settings.lang} | "
                    f"{len(pending)} file(s), {human_duration(total_audio)}")

            audio_done = 0.0
            time_spent = 0.0
            for n, job in enumerate(pending, 1):
                remaining_audio = total_audio - audio_done
                if time_spent > 0 and audio_done > 0:
                    eta = f"about {human_duration(remaining_audio / (audio_done / time_spent))} left"
                else:
                    eta = "time left: estimating after the first file"
                fraction = audio_done / total_audio if total_audio else 0
                check_stop()
                say(f"\n[{n}/{len(pending)}] {job.source.name} · {human_duration(job.duration)}")
                say(f"  Batch {_bar(fraction)} {fraction:4.0%} · {eta}")
                eta_seconds = (remaining_audio / (audio_done / time_spent)
                               if time_spent > 0 and audio_done > 0 else None)
                emit("batch", index=n, total=len(pending), fraction=fraction, eta=eta_seconds,
                     audio_total=total_audio, audio_done=audio_done)
                _process(job, n, backend, settings, style, glossary, prompt, language, run_dir, logline)
                audio_done += job.duration
                time_spent += job.seconds_taken
    except KeyboardInterrupt:
        interrupted = True
        say("\n\n■ Stopped. Temp audio removed and no half-written files left behind.")
        say("  Start again (same files) to continue where it left off.")
        for job in jobs:
            if job.status == "pending":
                job.status = "interrupted"
        logline("RUN STOPPED by user (Ctrl+C) — re-run to resume")
    except Exception as exc:  # e.g. the model failed to load: no file can succeed
        say(f"\n✗ Couldn't start the transcriber: {exc}")
        logline(f"RUN ABORTED | {exc}\n{traceback.format_exc()}")
        for job in jobs:
            if job.status == "pending":
                job.status, job.note = "failed", "transcriber didn't start"
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)
        for sig, handler in old_handlers.items():
            signal.signal(sig, handler)

    code = _summary(jobs, started, log_dir, False)
    logline("RUN END | " + _counts(jobs))
    log.close()
    code = 130 if interrupted else code
    emit("end", counts=_count_dict(jobs), interrupted=interrupted, code=code)
    return code


def _process(job, index, backend, settings, style, glossary, prompt, language, run_dir, logline) -> None:
    """Do one file. Never raises, except for Ctrl+C."""
    t0 = time.time()
    wav = run_dir / f"{index:03d}.wav"  # plain ASCII name; the original name can be anything
    path = str(job.source)

    def stage(name: str):
        def update(fraction: float) -> None:
            emit("progress", path=path, stage=name, fraction=fraction)
        update(0.0)
        return update

    emit("file", path=path, state="running")
    written: list = []
    try:
        remove_partials(job.out_dir, job.source)
        if job.note:
            say(f"  ⚠ {job.note}")
        if job.info and len(job.info.audio_tracks) > 1:
            say(f"  Using audio track {job.track.number}: {job.track.describe()}")

        bar = Progress("Extracting audio", job.duration, stage("extract"))
        try:
            wav_seconds = extract_audio(job.source, wav, job.track, settings.boost_quiet, bar.update)
        finally:
            bar.close()
        duration = job.duration or wav_seconds

        bar = Progress("Transcribing", duration, stage("transcribe"))
        try:
            result = backend.transcribe(wav, duration, language, prompt, bar.update)
        finally:
            bar.close()

        stage("write")
        segments = clean_segments(result.segments, prompt)
        written = write_all(
            job.out_dir, job.source, segments,
            formats=settings.formats, style=style, style_name=settings.captions,
            glossary=glossary, language=result.language, model_label=backend.label(),
            duration=duration, audio_track=job.track.number,
            settings={"lang": settings.lang, "boost_quiet": settings.boost_quiet,
                      "glossary": bool(prompt)},
        )
        job.seconds_taken = time.time() - t0
        job.status = "done"
        speed = duration / job.seconds_taken if job.seconds_taken else 0
        job.note = "no speech detected" if not segments else ""
        say(f"  ✓ Done in {human_duration(job.seconds_taken)} ({speed:.1f}× real time), "
            f"language: {result.language or '?'} · {len(written)} files written"
            + (" · no speech detected" if not segments else ""))
        logline(f"DONE | {job.source.name} | {human_duration(duration)} | {backend.label()} | "
                f"lang={result.language} | track {job.track.number} | took "
                f"{human_duration(job.seconds_taken)} ({speed:.1f}x)"
                + (" | no speech detected" if not segments else ""))
    except KeyboardInterrupt:
        remove_partials(job.out_dir, job.source)
        raise
    except NoAudioError as exc:
        job.status, job.note = "skipped", str(exc)
        job.seconds_taken = time.time() - t0
        say(f"  – Skipped: {exc}")
        logline(f"SKIPPED | {job.source.name} | {exc}")
    except Exception as exc:
        job.status, job.note = "failed", str(exc) or type(exc).__name__
        job.seconds_taken = time.time() - t0
        say(f"  ✗ Failed: {job.note}  (details in log.txt; moving on)")
        logline(f"FAILED | {job.source.name} | {job.note}\n{traceback.format_exc()}")
        remove_partials(job.out_dir, job.source)
    finally:
        if wav.exists():
            wav.unlink()  # temp audio never outlives its file
        emit("file", path=path, state=job.status, note=job.note,
             seconds=round(time.time() - t0, 1), outputs=[str(p) for p in written])


def _count_dict(jobs: list[Job]) -> dict:
    states = ("done", "done-before", "skipped", "failed", "interrupted")
    return {state: sum(1 for j in jobs if j.status == state) for state in states}


def _counts(jobs: list[Job]) -> str:
    def count(*states):
        return sum(1 for j in jobs if j.status in states)
    return (f"done {count('done')} · already done {count('done-before')} · "
            f"skipped {count('skipped')} · failed {count('failed')}"
            + (f" · not started {count('interrupted')}" if count("interrupted") else ""))


def _summary(jobs: list[Job], started: float, log_dir: Path, dry_run: bool) -> int:
    if dry_run:
        say("\nDry run only — nothing was transcribed.")
        return 0
    say("\n" + "─" * 60)
    say(f"Summary: {_counts(jobs)}")
    for job in jobs:
        if job.status in ("failed", "skipped"):
            say(f"  {'✗' if job.status == 'failed' else '–'} {job.source.name}: {job.note}")
    say(f"Total time: {human_duration(time.time() - started)} · log: {log_dir / 'log.txt'}")
    return 1 if any(j.status == "failed" for j in jobs) else 0
