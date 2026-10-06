"""Finding, probing and extracting audio from media files.

Python never opens the media files itself: ffprobe reads the header, and ffmpeg
streams the audio out to a small 16 kHz WAV. So a 3+ GB .mov costs almost no
memory. Every ffmpeg/ffprobe call uses an argument list (never a shell string),
so paths with spaces, emoji, quotes or accents are safe.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

VIDEO_EXTS = {".mov", ".mp4", ".mkv", ".webm", ".wmv"}
AUDIO_EXTS = {".mp3", ".wav", ".flac", ".aac", ".m4a"}
SUPPORTED_EXTS = VIDEO_EXTS | AUDIO_EXTS

WAV_BYTES_PER_SECOND = 16_000 * 2  # 16 kHz, mono, 16-bit
PROBE_TIMEOUT = 180  # seconds; a sleeping external drive can take a while to spin up


class MediaError(Exception):
    """A problem with one file. The batch logs it and moves on."""


class NoAudioError(MediaError):
    """The file has no usable audio. Logged as 'skipped', not 'failed'."""


def is_supported(path: Path) -> bool:
    return path.suffix.lower() in SUPPORTED_EXTS


def is_hidden_or_junk(name: str) -> bool:
    # Covers macOS "._name.mov" sidecar files (AppleDouble), ".DS_Store",
    # and any other hidden file. External drives are full of these.
    return name.startswith(".")


def scan(path: Path, recursive: bool = False) -> list[Path]:
    """Return supported media files under `path` (or `path` itself), sorted by name."""
    path = path.expanduser()
    if path.is_file():
        if is_hidden_or_junk(path.name):
            raise MediaError(f"{path.name} is a hidden/system file, not real media.")
        if not is_supported(path):
            raise MediaError(
                f"{path.name}: unsupported type. Supported: "
                + " ".join(sorted(SUPPORTED_EXTS))
            )
        return [path.resolve()]
    if not path.is_dir():
        raise MediaError(f"Can't find {path}. Is the drive plugged in?")

    found: list[Path] = []

    def walk(folder: Path) -> None:
        try:
            entries = sorted(os.scandir(folder), key=lambda e: e.name.lower())
        except PermissionError:
            return
        for entry in entries:
            if is_hidden_or_junk(entry.name):
                continue
            if entry.is_dir(follow_symlinks=False):
                if recursive:
                    walk(Path(entry.path))
            elif entry.is_file() and is_supported(Path(entry.name)):
                found.append(Path(entry.path).resolve())

    walk(path)
    return found


# ---------------------------------------------------------------- tools

def find_tool(name: str) -> Optional[str]:
    found = shutil.which(name)
    if found:
        return found
    # Homebrew locations, in case the PATH wasn't updated in this Terminal yet.
    for prefix in ("/opt/homebrew/bin", "/usr/local/bin"):
        candidate = Path(prefix) / name
        if candidate.exists():
            return str(candidate)
    return None


def require_tool(name: str) -> str:
    found = find_tool(name)
    if not found:
        raise RuntimeError(
            f"{name} isn't installed. Run the setup script (see README), "
            f"or on a Mac: brew install ffmpeg"
        )
    return found


# ---------------------------------------------------------------- probe

@dataclass
class AudioTrack:
    number: int  # 1-based, as people count: "track 1", "track 2"
    codec: Optional[str]
    channels: Optional[int]
    sample_rate: Optional[int]
    language: Optional[str]
    title: Optional[str]

    @property
    def decodable(self) -> bool:
        return bool(self.codec) and self.codec not in ("none", "unknown")

    def describe(self) -> str:
        bits = [self.codec or "unknown codec"]
        if self.channels:
            bits.append({1: "mono", 2: "stereo"}.get(self.channels, f"{self.channels} ch"))
        if self.sample_rate:
            bits.append(f"{self.sample_rate / 1000:g} kHz")
        if self.language and self.language != "und":
            bits.append(self.language)
        if self.title:
            bits.append(f'"{self.title}"')
        return ", ".join(bits)


@dataclass
class ProbeResult:
    duration: Optional[float]
    format_name: str
    has_video: bool
    audio_tracks: list[AudioTrack] = field(default_factory=list)


def _float(value) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def probe(path: Path) -> ProbeResult:
    ffprobe = require_tool("ffprobe")
    args = [
        ffprobe, "-v", "error", "-print_format", "json",
        "-show_format", "-show_streams", str(path),
    ]
    try:
        proc = subprocess.run(
            args, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=PROBE_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        raise MediaError("ffprobe timed out reading the file (drive asleep or file damaged?)")
    if proc.returncode != 0:
        detail = (proc.stderr.strip().splitlines() or ["unknown error"])[-1]
        detail = detail.replace(str(path) + ": ", "")  # ffprobe repeats the full path
        raise MediaError(f"unreadable or damaged file ({detail})")
    try:
        info = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        raise MediaError("ffprobe returned garbage; the file is probably damaged")

    streams = info.get("streams") or []
    fmt = info.get("format") or {}
    if not streams and not fmt:
        raise MediaError("Not a media file ffmpeg recognises")

    duration = _float(fmt.get("duration"))
    if duration is None:
        durations = [_float(s.get("duration")) for s in streams]
        durations = [d for d in durations if d]
        duration = max(durations) if durations else None

    tracks: list[AudioTrack] = []
    for stream in streams:
        if stream.get("codec_type") != "audio":
            continue
        tags = stream.get("tags") or {}
        tracks.append(AudioTrack(
            number=len(tracks) + 1,
            codec=stream.get("codec_name"),
            channels=stream.get("channels"),
            sample_rate=int(stream["sample_rate"]) if str(stream.get("sample_rate", "")).isdigit() else None,
            language=tags.get("language"),
            title=tags.get("title"),
        ))
    has_video = any(
        s.get("codec_type") == "video"
        and not (s.get("disposition") or {}).get("attached_pic")
        for s in streams
    )
    return ProbeResult(duration, fmt.get("format_name", "?"), has_video, tracks)


def choose_track(info: ProbeResult, requested: int = 0) -> tuple[AudioTrack, Optional[str]]:
    """Pick which audio track to transcribe. Returns (track, warning-or-None).

    requested=0 means automatic: the first track ffmpeg can decode. That is
    normally track 1. (Some new iPhones add a "spatial audio" track that older
    ffmpeg builds can't decode; this skips past it instead of failing.)
    """
    if not info.audio_tracks:
        raise NoAudioError("no audio track")
    warning = None
    if requested:
        if requested <= len(info.audio_tracks):
            return info.audio_tracks[requested - 1], None
        warning = (
            f"asked for audio track {requested} but the file only has "
            f"{len(info.audio_tracks)}; using automatic choice"
        )
    for track in info.audio_tracks:
        if track.decodable:
            return track, warning
    raise MediaError(
        "audio track uses a codec this ffmpeg can't decode ("
        + ", ".join(t.codec or "unknown" for t in info.audio_tracks)
        + "). Try: brew upgrade ffmpeg"
    )


# ---------------------------------------------------------------- extract

def extract_audio(
    src: Path,
    dst_wav: Path,
    track: AudioTrack,
    boost_quiet: bool = False,
    on_progress: Optional[Callable[[float], None]] = None,
) -> float:
    """Stream one audio track out of `src` into a 16 kHz mono 16-bit WAV.

    Returns the length of the WAV in seconds. `on_progress(seconds_done)` is
    called as ffmpeg works through the file.
    """
    ffmpeg = require_tool("ffmpeg")
    args = [
        ffmpeg, "-hide_banner", "-nostdin", "-y", "-loglevel", "error",
        "-i", str(src),
        "-map", f"0:a:{track.number - 1}",  # exactly one track, never a blind mix
        "-vn", "-sn", "-dn", "-map_metadata", "-1",
        "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le",
    ]
    if boost_quiet:
        # Evens out loud and quiet voices (e.g. audience questions far from the
        # mic). Works on a sliding window, so it still streams.
        args += ["-af", "dynaudnorm=f=250:g=15:m=20"]
    args += ["-progress", "pipe:1", "-nostats", str(dst_wav)]

    # stderr goes to a temp file, not a pipe: a damaged file can make ffmpeg print
    # thousands of errors, and a full pipe would freeze both programs.
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace") as err:
        proc = subprocess.Popen(
            args, stdout=subprocess.PIPE, stderr=err, stdin=subprocess.DEVNULL,
            text=True, encoding="utf-8", errors="replace",
        )
        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                key, _, value = line.strip().partition("=")
                if key == "out_time_us" and on_progress and value.isdigit():
                    on_progress(int(value) / 1_000_000)
            proc.wait()
        finally:
            if proc.poll() is None:  # interrupted (Ctrl+C) or crashed mid-way
                proc.kill()
                proc.wait()
        if proc.returncode != 0:
            err.seek(0)
            lines = [l for l in err.read().strip().splitlines() if l.strip()]
            detail = lines[-1] if lines else f"exit code {proc.returncode}"
            raise MediaError(f"ffmpeg couldn't extract audio: {detail}")

    size = dst_wav.stat().st_size if dst_wav.exists() else 0
    seconds = max(0, size - 44) / WAV_BYTES_PER_SECOND
    if seconds < 0.05:
        raise NoAudioError("audio track is empty")
    return seconds
