#!/usr/bin/env python3
"""Make the samples/clips/ test folder: one short clip per supported format,
plus the awkward cases the tool must survive.

    python samples/make_samples.py                      # spoken test clips (Mac voice)
    python samples/make_samples.py --from "/Volumes/LaCie/Shoot/IMG_0042.MOV" --start 60 --seconds 90
                                                        # cut real audio from one of your files

Speech comes from (first that works): --from FILE, the Mac's built-in `say`
voice, or a plain tone (fine for testing the plumbing, but nothing to transcribe).
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
CLIPS = HERE / "clips"

SCRIPT = (
    "Hi everyone, I'm Evan. Welcome to the Smooth Scaling workshop. "
    "Today I'll walk you through Lightning OS, step by step. "
    "Does anyone have a question before we start? "
    "Yes, great question. Let's get started."
)


def ffmpeg() -> str:
    for candidate in (shutil.which("ffmpeg"), "/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg"):
        if candidate and Path(candidate).exists():
            return candidate
    sys.exit("ffmpeg not found — run the setup script first.")


def run(args: list[str]) -> bool:
    proc = subprocess.run(args, capture_output=True, text=True)
    if proc.returncode != 0:
        print("   ffmpeg said:", (proc.stderr.strip().splitlines() or ["?"])[-1])
    return proc.returncode == 0


def encoders(ff: str) -> set[str]:
    out = subprocess.run([ff, "-hide_banner", "-encoders"], capture_output=True, text=True).stdout
    return {line.split()[1] for line in out.splitlines() if len(line.split()) > 1 and line.startswith(" ")}


def make_speech(ff: str, work: Path, source: str | None, start: float, seconds: float) -> tuple[Path, str]:
    speech = work / "speech.wav"
    if source:
        if not Path(source).is_file():
            sys.exit(f"Can't find that file: {source}")
        length = duration_of(ff, Path(source))
        if start >= length:
            print(f"(That video is only {length:.0f} s long, so cutting from the start instead.)")
            start = 0
        ok = run([ff, "-y", "-nostdin", "-ss", str(start), "-t", str(seconds), "-i", source,
                  "-map", "0:a:0", "-vn", "-ac", "2", "-ar", "44100", "-c:a", "pcm_s16le", str(speech)])
        if ok and duration_of(ff, speech) > 1:
            return speech, f"cut from {Path(source).name}"
        sys.exit("Couldn't cut audio from that file.")
    if shutil.which("say"):
        aiff = work / "speech.aiff"
        if run(["say", "-o", str(aiff), SCRIPT]):
            # 1 s of silence either side, stereo 44.1 kHz like a real recording
            run([ff, "-y", "-nostdin", "-i", str(aiff), "-af", "adelay=1000:all=1,apad=pad_dur=1",
                 "-ac", "2", "-ar", "44100", "-c:a", "pcm_s16le", str(speech)])
            return speech, "Mac 'say' voice"
    run([ff, "-y", "-nostdin", "-f", "lavfi", "-i", "sine=frequency=330:duration=8",
         "-af", "volume=0.5", "-ac", "2", "-ar", "44100", "-c:a", "pcm_s16le", str(speech)])
    return speech, "tone (no speech available on this computer)"


def duration_of(ff: str, path: Path) -> float:
    ffprobe = str(Path(ff).with_name("ffprobe" + (".exe" if os.name == "nt" else "")))
    out = subprocess.run([ffprobe, "-v", "error", "-show_entries", "format=duration",
                          "-of", "default=nw=1:nk=1", str(path)], capture_output=True, text=True).stdout
    return float(out.strip() or 10)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--from", dest="source", nargs="?", const="ASK",
                    help="cut the test audio from this real file (leave empty to drag one in)")
    ap.add_argument("--start", type=float, default=0, help="where to start cutting (seconds)")
    ap.add_argument("--seconds", type=float, default=60, help="how much to cut (seconds)")
    ap.add_argument("--out", default=str(CLIPS), help="where to put the clips")
    args = ap.parse_args()

    ff = ffmpeg()
    if args.source == "ASK":
        sys.path.insert(0, str(HERE.parent))
        from avtool.cli import clean_dragged_path
        print("Drag one of your video files into this window, then press Enter:")
        args.source = clean_dragged_path(input("> "))
    have = encoders(ff)
    out = Path(args.out)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    with tempfile.TemporaryDirectory() as tmp:
        speech, origin = make_speech(ff, Path(tmp), args.source, args.start, args.seconds)
        length = duration_of(ff, speech)
        print(f"Test audio: {origin}, {length:.1f} s\n")

        video = ["-f", "lavfi", "-i", f"testsrc2=size=320x240:rate=15:duration={length}"]
        speech_in = ["-i", str(speech)]
        h264 = ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p"] if "libx264" in have else ["-c:v", "mpeg4"]
        vp9 = (["-c:v", "libvpx-vp9", "-deadline", "realtime", "-cpu-used", "8", "-b:v", "200k"]
               if "libvpx-vp9" in have else ["-c:v", "libvpx", "-b:v", "200k"])
        opus = ["-c:a", "libopus"] if "libopus" in have else ["-c:a", "libvorbis"]
        mp3 = ["-c:a", "libmp3lame"] if "libmp3lame" in have else ["-c:a", "mp3"]

        jobs = {
            # one clip per supported format
            "sample.mov": video + speech_in + h264 + ["-c:a", "aac", "-shortest"],
            "sample.mp4": video + speech_in + h264 + ["-c:a", "aac", "-shortest"],
            "sample.mkv": video + speech_in + h264 + opus + ["-shortest"],
            "sample.webm": video + speech_in + vp9 + opus + ["-shortest"],
            "sample.wmv": video + speech_in + ["-c:v", "wmv2", "-c:a", "wmav2", "-shortest"],
            "sample.mp3": speech_in + mp3,
            "sample.wav": speech_in + ["-c:a", "pcm_s16le"],
            "sample.flac": speech_in + ["-c:a", "flac"],
            "sample.aac": speech_in + ["-c:a", "aac", "-f", "adts"],
            "sample.m4a": speech_in + ["-c:a", "aac"],
            # camera-style upper-case extension
            "CAMERA_CLIP.MOV": video + speech_in + h264 + ["-c:a", "aac", "-shortest"],
            # spaces, accents, emoji and an apostrophe in the name
            "Évan’s talk 🎤 (take 2).mp4": video + speech_in + h264 + ["-c:a", "aac", "-shortest"],
            # two audio tracks: 1 = a tone ("camera mic"), 2 = the speech ("lav")
            "two_tracks.mov": video + ["-f", "lavfi", "-i", f"sine=frequency=220:duration={length}"] + speech_in
                              + ["-map", "0:v", "-map", "1:a", "-map", "2:a"] + h264 + ["-c:a", "aac", "-shortest"],
            # silence: has an audio track, but nobody speaks
            "silent.mp4": video + ["-f", "lavfi", "-i", f"anullsrc=r=44100:cl=stereo:d={length}"]
                          + h264 + ["-c:a", "aac", "-shortest"],
            # video only, no audio track at all
            "no_audio.mp4": video + h264,
        }
        for name, spec in jobs.items():
            ok = run([ff, "-y", "-nostdin", "-loglevel", "error", *spec, str(out / name)])
            print(f"  {'✓' if ok else '✗'} {name}")

    # A damaged file: looks like a .mov, isn't one.
    (out / "corrupt.mov").write_bytes(os.urandom(64 * 1024))
    print("  ✓ corrupt.mov (random bytes — must be logged as failed, batch continues)")
    # macOS junk the tool must ignore completely.
    (out / "._sample.mov").write_bytes(b"\x00\x05\x16\x07" + os.urandom(4092))
    (out / ".hidden.mov").write_bytes(os.urandom(1024))
    print("  ✓ ._sample.mov and .hidden.mov (macOS junk — must be ignored)")
    print(f"\nClips are in: {out}")
    print('Now run:  python transcribe.py samples/clips')


if __name__ == "__main__":
    main()
