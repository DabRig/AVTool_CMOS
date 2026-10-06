"""Command-line interface. Settings come from config.toml, then the command line."""

from __future__ import annotations

import argparse
import os
import platform
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Optional

from . import __version__
from .backends import has_module, is_apple_silicon, make_backend, resolve_backend, running_under_rosetta
from .media import MediaError, find_tool, probe, scan
from .text import CAPTION_PRESETS, load_glossary
from .timefmt import human_duration
from .writers import FORMATS

PROJECT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = PROJECT_DIR / "config.toml"

DEFAULTS = {
    "model": "large-v3-turbo",
    "lang": "auto",
    "backend": "auto",
    "audio_track": 0,
    "recursive": False,
    "out": "",
    "captions": "standard",
    "glossary": "glossary.txt",
    "formats": list(FORMATS),
    "boost_quiet": False,
    "keep_awake": True,
    "audio_tracks": {},
}


def load_config(path: Path) -> dict:
    config = dict(DEFAULTS)
    if not path.is_file():
        return config
    try:
        import tomllib  # Python 3.11+
    except ImportError:
        try:
            import tomli as tomllib
        except ImportError:
            print(f"(Skipping {path.name}: needs Python 3.11+)")
            return config
    with open(path, "rb") as f:
        try:
            config.update(tomllib.load(f))
        except Exception as exc:
            raise SystemExit(f"✗ {path.name} has a typo: {exc}")
    return config


def clean_dragged_path(raw: str) -> str:
    """Paths dragged into Terminal arrive quoted or with backslash-escaped spaces."""
    raw = raw.strip()
    if not raw:
        return raw
    if os.name == "nt":
        return raw.strip('"')
    try:
        parts = shlex.split(raw)
        return parts[0] if len(parts) == 1 else raw
    except ValueError:
        return raw.strip("'\"")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="transcribe.py",
        description="Free, offline transcripts and subtitles for video and audio files.",
        epilog='Example:  python transcribe.py "/Volumes/LaCie/Shoot" --lang en',
    )
    p.add_argument("path", nargs="?", help="a folder or a single file (drag it into the Terminal window)")
    p.add_argument("--model", help="large-v3-turbo (best, default), medium, small (fast drafts)…")
    p.add_argument("--lang", help="language: auto, en, es, … (setting it avoids mis-detection)")
    p.add_argument("--backend", choices=["auto", "mlx", "cuda", "cpu", "test"],
                   help="which engine; 'auto' picks the best for this computer")
    p.add_argument("--audio-track", type=int, metavar="N",
                   help="which audio track to use (1 = first). Default: automatic")
    p.add_argument("--recursive", action="store_true", default=None, help="include subfolders")
    p.add_argument("--out", metavar="FOLDER", help="put transcripts here instead of next to each file")
    p.add_argument("--force", action="store_true", help="redo files that are already transcribed")
    p.add_argument("--captions", choices=sorted(CAPTION_PRESETS),
                   help="standard (≤42 chars × 2 lines) or reels (short, 1 line)")
    p.add_argument("--glossary", metavar="FILE", help="names/terms file (default: glossary.txt)")
    p.add_argument("--formats", metavar="LIST",
                   help="comma list from: " + ",".join(FORMATS) + " (json is always written)")
    p.add_argument("--boost-quiet", action="store_true", default=None,
                   help="even out loud/quiet voices (helps catch audience questions)")
    p.add_argument("--no-keep-awake", action="store_true", help="let the computer sleep")
    p.add_argument("--dry-run", action="store_true", help="list what would be done, then stop")
    p.add_argument("--list-tracks", action="store_true", help="show each file's audio tracks, then stop")
    p.add_argument("--check", action="store_true", help="check the installation, then stop")
    p.add_argument("--download-model", action="store_true",
                   help="download the model now (needs internet once), then stop")
    p.add_argument("--config", metavar="FILE", help=f"settings file (default: {DEFAULT_CONFIG.name})")
    p.add_argument("--temp-dir", metavar="FOLDER", help=argparse.SUPPRESS)
    p.add_argument("--version", action="version", version=f"AVTool CMOS {__version__}")
    return p


def main(argv: Optional[list[str]] = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):  # so ✓ and emoji print on Windows too
        sys.stdout.reconfigure(errors="replace")
    args = build_parser().parse_args(argv)
    config_path = Path(args.config).expanduser() if args.config else DEFAULT_CONFIG
    cfg = load_config(config_path)

    def pick(cli_value, key):
        return cfg[key] if cli_value is None else cli_value

    model = pick(args.model, "model")
    backend = pick(args.backend, "backend")

    if args.check:
        return check_install(backend, model)
    if args.download_model:
        b = make_backend(backend, model)
        b.ensure_model(allow_download=True)
        print(f"✓ Model ready: {b.label()} — the tool now works offline.")
        return 0

    path = args.path
    if not path:
        print("Drag a folder (or a single file) into this window, then press Enter:")
        try:
            path = clean_dragged_path(input("> "))
        except (EOFError, KeyboardInterrupt):
            return 130
        if not path:
            print("No folder given.")
            return 2

    if args.list_tracks:
        return list_tracks(Path(path), bool(pick(args.recursive, "recursive")))

    formats = cfg["formats"] if args.formats is None else [f.strip() for f in args.formats.split(",") if f.strip()]
    unknown = [f for f in formats if f not in FORMATS]
    if unknown:
        print(f"✗ Unknown format(s): {', '.join(unknown)}. Choose from: {', '.join(FORMATS)}")
        return 2
    captions = pick(args.captions, "captions")
    if captions not in CAPTION_PRESETS:
        print(f"✗ Unknown captions preset '{captions}'. Choose: {', '.join(CAPTION_PRESETS)}")
        return 2

    glossary = pick(args.glossary, "glossary")
    glossary_path = None
    if glossary:
        glossary_path = Path(glossary).expanduser()
        if not glossary_path.is_absolute() and not glossary_path.exists():
            glossary_path = PROJECT_DIR / glossary_path
        if args.glossary and not glossary_path.is_file():
            print(f"✗ Glossary file not found: {glossary}")
            return 2

    out = pick(args.out, "out")
    from .batch import Settings, run  # imported here so --help stays instant
    settings = Settings(
        path=Path(path),
        model=model,
        lang=str(pick(args.lang, "lang") or "auto"),
        backend=backend,
        audio_track=int(pick(args.audio_track, "audio_track") or 0),
        track_overrides=dict(cfg.get("audio_tracks") or {}),
        recursive=bool(pick(args.recursive, "recursive")),
        out=Path(out) if out else None,
        force=args.force,
        captions=captions,
        glossary=glossary_path,
        formats=formats,
        boost_quiet=bool(pick(args.boost_quiet, "boost_quiet")),
        keep_awake=False if args.no_keep_awake else bool(cfg["keep_awake"]),
        dry_run=args.dry_run,
        temp_root=Path(args.temp_dir) if args.temp_dir else None,
    )
    try:
        return run(settings)
    except KeyboardInterrupt:
        print("\nStopped.")
        return 130


def list_tracks(path: Path, recursive: bool) -> int:
    try:
        files = scan(path, recursive)
    except MediaError as exc:
        print(f"✗ {exc}")
        return 2
    for source in files:
        print(f"\n{source.name}")
        try:
            info = probe(source)
        except MediaError as exc:
            print(f"   can't read: {exc}")
            continue
        print(f"   length: {human_duration(info.duration)}")
        if not info.audio_tracks:
            print("   no audio tracks")
        for t in info.audio_tracks:
            print(f"   audio track {t.number}: {t.describe()}")
    print('\nTo use a different track:  --audio-track 2   (or per file in config.toml)')
    return 0


def check_install(backend_choice: str, model: str) -> int:
    ok = True

    def line(good: bool, text: str, fix: str = "") -> None:
        nonlocal ok
        ok = ok and good
        print(f"  {'✓' if good else '✗'} {text}" + (f"\n      → {fix}" if fix and not good else ""))

    print(f"AVTool CMOS {__version__} — installation check\n")
    py_ok = sys.version_info >= (3, 10)
    line(py_ok, f"Python {platform.python_version()} ({platform.machine()})",
         "Python 3.10 or newer is needed; run the setup script")
    if running_under_rosetta():
        line(False, "Python is running in Intel mode (Rosetta) on an Apple Silicon Mac",
             "re-run setup_mac.command from a normal (not Rosetta) Terminal")
    for tool in ("ffmpeg", "ffprobe"):
        found = find_tool(tool)
        version = ""
        if found:
            try:
                version = subprocess.run([found, "-version"], capture_output=True, text=True,
                                         timeout=20).stdout.split("\n", 1)[0]
            except (OSError, subprocess.SubprocessError):
                found = None
        line(bool(found), f"{tool}: {version or 'not found'}", "brew install ffmpeg (Mac)")
    try:
        kind = resolve_backend(backend_choice)
        labels = {"mlx": "mlx-whisper on the Apple Silicon GPU", "cuda": "faster-whisper on NVIDIA GPU",
                  "cpu": "faster-whisper on CPU (works, slower)", "test": "test engine"}
        line(True, f"Engine: {labels[kind]}")
        if is_apple_silicon() and kind != "mlx":
            line(False, "This Mac could use the faster MLX engine", "pip install -r requirements-mac.txt")
        b = make_backend(backend_choice, model)
        try:
            b.ensure_model(allow_download=False)
            line(True, f"Model {model} downloaded (works offline)")
        except Exception as exc:
            line(False, f"Model {model} not downloaded yet", "python transcribe.py --download-model")
    except Exception as exc:
        line(False, f"Engine: {exc}")
    line(has_module("docx"), "Word (.docx) output available", "pip install python-docx")
    line(has_module("tqdm"), "Progress bars available", "pip install tqdm")
    g = load_glossary(PROJECT_DIR / "glossary.txt")
    print(f"  • Glossary: {', '.join(g.terms) if g.terms else '(empty)'}")
    print("\nAll good — ready to transcribe." if ok else "\nSome items need attention (see → above).")
    return 0 if ok else 1
