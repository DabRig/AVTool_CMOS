"""The app's private engine room: queue, settings, live progress, transcripts.

A tiny web server that only answers on 127.0.0.1 (this Mac), on a random
port, and only to requests carrying a secret key that changes every launch.
The window (avtool/gui/app.py) shows the page it serves. Nothing is uploaded:
the page talks to this server, and this server talks to the transcriber.
"""

from __future__ import annotations

import json
import mimetypes
import os
import secrets
import subprocess
import sys
import threading
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import parse_qs, urlparse

from .. import __version__
from ..backends import is_apple_silicon, make_backend, resolve_backend
from ..batch import Settings, run
from ..cli import DEFAULT_CONFIG, PROJECT_DIR, load_config
from ..media import MediaError, find_tool, probe, scan
from ..text import load_glossary
from ..timefmt import human_duration
from ..writers import FORMATS, done_marker, output_path

STATIC = Path(__file__).resolve().parent / "static"
GUI_SETTINGS = PROJECT_DIR / "gui_settings.json"
MODELS = ["small", "medium", "large-v3-turbo"]
EDITABLE = ("model", "lang", "captions", "boost_quiet", "recursive", "force",
            "keep_awake", "out", "formats", "tour_done")
ALWAYS_EDITABLE = {"tour_done"}  # not a transcription setting: fine to change mid-batch


# ---------------------------------------------------------------- state

@dataclass
class Item:
    id: str
    path: str
    name: str
    folder: str
    size: int = 0
    duration: Optional[float] = None
    tracks: int = 0
    status: str = "probing"  # probing ready done running stopped failed skipped
    note: str = ""
    stage: str = ""          # extract | transcribe | write
    fraction: float = 0.0
    seconds: Optional[float] = None


class AppState:
    def __init__(self, backend_choice: Optional[str] = None, temp_root: Optional[Path] = None):
        self.lock = threading.RLock()
        self.items: dict[str, Item] = {}
        self.log: deque[tuple[int, str]] = deque(maxlen=1500)
        self.log_seq = 0
        self.running = False
        self.loading = False
        self.stop = threading.Event()
        self.thread: Optional[threading.Thread] = None
        self.batch = {"index": 0, "total": 0, "fraction": 0.0, "eta": None, "current": None}
        self.last_run: Optional[dict] = None
        self.temp_root = temp_root
        self.config = load_config(DEFAULT_CONFIG)
        if backend_choice:
            self.config["backend"] = backend_choice
        self.settings = self._load_settings()
        self.engine = {"checked": False}
        # A function(kind) -> list[str] for native Open dialogs; set by app.py.
        self.dialogs: Optional[Callable[[str], list]] = None
        threading.Thread(target=self._check_engine, daemon=True).start()

    # ---- settings
    def _load_settings(self) -> dict:
        s = {
            "model": self.config["model"], "lang": self.config["lang"],
            "captions": self.config["captions"], "boost_quiet": bool(self.config["boost_quiet"]),
            "recursive": bool(self.config["recursive"]), "force": False,
            "keep_awake": bool(self.config["keep_awake"]), "out": self.config["out"] or "",
            "formats": [f for f in self.config["formats"] if f in FORMATS],
            "tour_done": False,
        }
        try:
            saved = json.loads(GUI_SETTINGS.read_text())
            s.update({k: v for k, v in saved.items() if k in EDITABLE})
        except (OSError, ValueError):
            pass
        return s

    def update_settings(self, changes: dict) -> dict:
        with self.lock:
            if self.running and not set(changes) <= ALWAYS_EDITABLE:
                raise ValueError("Settings are locked while a batch is running.")
            old_model = self.settings.get("model")
            for key, value in changes.items():
                if key not in EDITABLE:
                    continue
                if key == "model" and value not in MODELS:
                    continue
                if key == "captions" and value not in ("standard", "reels"):
                    continue
                if key == "formats":
                    value = [f for f in value if f in FORMATS]
                if key == "tour_done":
                    value = bool(value)
                self.settings[key] = value
            if "json" not in self.settings["formats"]:
                self.settings["formats"].append("json")  # resume marker, always written
            try:
                GUI_SETTINGS.write_text(json.dumps(self.settings, indent=2))
            except OSError:
                pass
            self._refresh_done_flags()
            if self.settings.get("model") != old_model:  # is the new model downloaded?
                self.engine = {"checked": False}
                threading.Thread(target=self._check_engine, daemon=True).start()
            return dict(self.settings)

    def out_dir_for(self, source: Path) -> Path:
        out = self.settings.get("out") or ""
        return Path(out).expanduser() if out else source.parent

    # ---- engine check (runs once in the background at launch)
    def _check_engine(self) -> None:
        info = {"checked": True, "ffmpeg": bool(find_tool("ffmpeg") and find_tool("ffprobe")),
                "backend": None, "label": "", "model_ready": False, "error": ""}
        try:
            kind = resolve_backend(self.config["backend"])
            info["backend"] = kind
            info["label"] = {"mlx": "MLX · APPLE GPU", "cuda": "CUDA · NVIDIA GPU",
                             "cpu": "CPU", "test": "TEST ENGINE"}[kind]
            b = make_backend(self.config["backend"], self.settings["model"])
            try:
                b.ensure_model(allow_download=False)
                info["model_ready"] = True
            except Exception:
                info["model_ready"] = kind == "test"
        except Exception as exc:
            info["error"] = str(exc)
        info["apple_silicon"] = is_apple_silicon()
        self.engine = info

    # ---- log
    def add_log(self, text: str) -> None:
        with self.lock:
            for line in (text.splitlines() or [""]):
                self.log_seq += 1
                self.log.append((self.log_seq, line))

    # ---- queue
    def add_paths(self, paths: list[str]) -> dict:
        added, problems = 0, []
        recursive = bool(self.settings.get("recursive"))
        new_items: list[Item] = []
        for raw in paths:
            if not raw:
                continue
            try:
                found = scan(Path(raw), recursive)
            except MediaError as exc:
                problems.append(str(exc))
                continue
            if not found and Path(raw).is_dir():
                problems.append(f"No media files in {Path(raw).name}"
                                + ("" if recursive else " (turn on 'Include subfolders'?)"))
            with self.lock:
                known = {i.path for i in self.items.values()}
                for f in found:
                    if str(f) in known:
                        continue
                    item = Item(id=secrets.token_hex(4), path=str(f), name=f.name, folder=str(f.parent))
                    try:
                        item.size = f.stat().st_size
                    except OSError:
                        pass
                    self.items[item.id] = item
                    new_items.append(item)
                    known.add(str(f))
                    added += 1
        for p in problems:
            self.add_log(f"⚠ {p}")
        if new_items:
            threading.Thread(target=self._probe_items, args=(new_items,), daemon=True).start()
        return {"added": added, "problems": problems}

    def _probe_items(self, items: list[Item]) -> None:
        for item in items:
            status, note, duration, tracks = "ready", "", None, 0
            try:
                info = probe(Path(item.path))
                duration, tracks = info.duration, len(info.audio_tracks)
                if not info.audio_tracks:
                    status, note = "skipped", "no audio track"
            except MediaError as exc:
                status, note = "failed", str(exc)
            with self.lock:
                if item.id not in self.items or item.status == "running":
                    continue
                item.duration, item.tracks, item.note = duration, tracks, note
                item.status = status
                if status == "ready" and self._is_done(item):
                    item.status, item.note = "done", "already transcribed"

    def _is_done(self, item: Item) -> bool:
        source = Path(item.path)
        return done_marker(self.out_dir_for(source), source).exists()

    def _refresh_done_flags(self) -> None:
        for item in self.items.values():
            if item.status in ("ready", "done", "stopped"):
                is_done = self._is_done(item)
                if is_done and item.status != "done":
                    item.status, item.note = "done", "already transcribed"
                elif not is_done and item.status == "done":
                    item.status, item.note = "ready", ""

    def remove(self, item_id: str) -> None:
        with self.lock:
            item = self.items.get(item_id)
            if item and item.status != "running":
                del self.items[item_id]

    def clear(self, which: str) -> None:
        with self.lock:
            for item in list(self.items.values()):
                if item.status == "running":
                    continue
                if which == "all" or (which == "finished" and item.status in ("done", "skipped", "failed")):
                    del self.items[item.id]

    # ---- running a batch
    def start(self) -> dict:
        with self.lock:
            if self.running:
                return {"ok": False, "error": "Already running."}
            force = bool(self.settings.get("force"))
            todo = [i for i in self.items.values()
                    if i.status in ("ready", "stopped") or (i.status == "failed" and i.duration)
                    or (force and i.status == "done")]
            if not todo:
                return {"ok": False, "error": "Nothing to transcribe. Add files, or turn on 'Redo finished files'."}
            out = self.settings.get("out") or ""
            glossary = Path(self.config.get("glossary") or "glossary.txt")
            if not glossary.is_absolute():
                glossary = PROJECT_DIR / glossary
            settings = Settings(
                path=Path(todo[0].folder),
                files=[i.path for i in todo],
                model=self.settings["model"],
                lang=self.settings["lang"],
                backend=self.config["backend"],
                audio_track=int(self.config.get("audio_track") or 0),
                track_overrides=dict(self.config.get("audio_tracks") or {}),
                out=Path(out).expanduser() if out else None,
                force=force,
                captions=self.settings["captions"],
                glossary=glossary,
                formats=list(self.settings["formats"]),
                boost_quiet=bool(self.settings["boost_quiet"]),
                keep_awake=bool(self.settings["keep_awake"]),
                temp_root=self.temp_root,
                on_event=self._on_event,
                stop=self.stop,
            )
            for i in todo:
                i.status, i.stage, i.fraction, i.note = "queued", "", 0.0, ""
            self.stop.clear()
            self.running = True
            self.batch = {"index": 0, "total": len(todo), "fraction": 0.0, "eta": None,
                          "current": None, "started": time.time()}
            self.last_run = None
            self.thread = threading.Thread(target=self._run, args=(settings,), daemon=True)
            self.thread.start()
            return {"ok": True, "count": len(todo)}

    def _run(self, settings: Settings) -> None:
        code = 2
        try:
            code = run(settings)
        except Exception as exc:  # never leave the app stuck in "running"
            self.add_log(f"✗ Unexpected error: {exc}")
        finally:
            with self.lock:
                for item in self.items.values():
                    if item.status in ("queued", "running"):
                        item.status = "stopped" if self.stop.is_set() else "ready"
                        item.stage, item.fraction = "", 0.0
                self.running = False
                self.loading = False
                self.batch["current"] = None
                if self.last_run is None:
                    self.last_run = {"code": code, "interrupted": self.stop.is_set(), "counts": {}}
                self.stop.clear()

    def request_stop(self) -> None:
        if self.running:
            self.stop.set()
            self.add_log("■ Stopping… (cleaning up the current file)")

    def _find(self, path: str) -> Optional[Item]:
        for item in self.items.values():
            if item.path == path:
                return item
        return None

    def _on_event(self, kind: str, data: dict) -> None:
        with self.lock:
            if kind == "log":
                self.add_log(data.get("text", ""))
            elif kind == "loading":
                self.loading = True
            elif kind == "plan":
                for j in data["jobs"]:
                    item = self._find(j["path"])
                    if not item:
                        continue
                    if j["status"] == "done-before":
                        item.status, item.note = "done", "already transcribed"
                    elif j["status"] in ("skipped", "failed"):
                        item.status, item.note = j["status"], j["note"]
                    elif j["note"]:
                        item.note = j["note"]
            elif kind == "batch":
                self.loading = False
                self.batch.update({k: data[k] for k in ("index", "total", "fraction", "eta")})
            elif kind == "file":
                item = self._find(data["path"])
                if item:
                    state = data["state"]
                    if state == "running":
                        item.status, item.stage, item.fraction = "running", "extract", 0.0
                        self.batch["current"] = item.id
                    else:
                        item.status = {"pending": "stopped"}.get(state, state)
                        item.note = data.get("note", "")
                        item.seconds = data.get("seconds")
                        item.stage, item.fraction = "", 1.0 if state == "done" else 0.0
                        if self.batch.get("current") == item.id:
                            self.batch["current"] = None
            elif kind == "progress":
                item = self._find(data["path"])
                if item:
                    item.stage, item.fraction = data["stage"], float(data["fraction"])
                    self._update_batch_fraction(item)
            elif kind == "end":
                self.last_run = {"code": data["code"], "interrupted": data["interrupted"],
                                 "counts": data["counts"]}

    def _update_batch_fraction(self, current: Item) -> None:
        """Smooth overall progress: finished files plus the share of the current one."""
        stage_start = {"extract": 0.0, "transcribe": 0.08, "write": 0.98}
        stage_size = {"extract": 0.08, "transcribe": 0.90, "write": 0.02}
        within = stage_start.get(current.stage, 0) + stage_size.get(current.stage, 0) * current.fraction
        index = max(self.batch.get("index", 1), 1)
        count = max(self.batch.get("total", 1), 1)
        self.batch["fraction"] = min(((index - 1) + within) / count, 1.0)

    # ---- transcripts
    def transcript(self, item_id: str) -> dict:
        with self.lock:
            item = self.items.get(item_id)
        if not item:
            raise KeyError("Unknown file")
        source = Path(item.path)
        out_dir = self.out_dir_for(source)
        marker = done_marker(out_dir, source)
        if not marker.exists():
            raise KeyError("Not transcribed yet")
        data = json.loads(marker.read_text(encoding="utf-8"))
        files = {fmt: str(output_path(out_dir, source, fmt)) for fmt in FORMATS
                 if output_path(out_dir, source, fmt).exists()}
        return {
            "name": item.name,
            "language": data.get("language"),
            "model": data.get("model"),
            "created": data.get("created"),
            "duration": data.get("source", {}).get("duration_seconds"),
            "segments": [{"start": s["start"], "end": s["end"], "text": s["text"]}
                         for s in data.get("segments", [])],
            "files": files,
        }

    def allowed_path(self, path: str) -> bool:
        """Only files the app itself knows about may be opened or revealed."""
        p = str(Path(path).expanduser())
        with self.lock:
            for item in self.items.values():
                if p == item.path:
                    return True
                source = Path(item.path)
                out_dir = self.out_dir_for(source)
                if p == str(out_dir) or any(p == str(output_path(out_dir, source, f)) for f in FORMATS):
                    return True
        out = self.settings.get("out")
        return bool(out) and p == str(Path(out).expanduser())

    # ---- snapshot for the page
    def snapshot(self, since: int = 0) -> dict:
        with self.lock:
            items = []
            for i in self.items.values():
                d = asdict(i)
                d["duration_text"] = human_duration(i.duration) if i.duration else ""
                items.append(d)
            audio = sum(i.duration or 0 for i in self.items.values() if i.status in ("ready", "stopped", "queued", "running"))
            return {
                "version": __version__,
                "running": self.running,
                "loading": self.loading,
                "stopping": self.running and self.stop.is_set(),
                "items": items,
                "batch": dict(self.batch),
                "last_run": self.last_run,
                "settings": dict(self.settings),
                "engine": dict(self.engine),
                "queued_audio": audio,
                "log": [{"n": n, "text": t} for n, t in self.log if n > since],
                "log_seq": self.log_seq,
                "dialogs": self.dialogs is not None or sys.platform == "darwin",
            }


# ---------------------------------------------------------------- OS helpers

def mac_choose(kind: str) -> list[str]:
    """Native Finder dialog via AppleScript (used when no window dialog is available)."""
    if kind == "folder" or kind == "outdir":
        prompt = "Choose where to save transcripts" if kind == "outdir" else "Add a folder of videos"
        script = [f'POSIX path of (choose folder with prompt "{prompt}")']
    else:
        script = ['set picked to choose file with prompt "Add videos or audio" with multiple selections allowed',
                  'set out to ""',
                  'repeat with f in picked',
                  'set out to out & POSIX path of f & linefeed',
                  'end repeat',
                  'return out']
    args = ["osascript"]
    for line in script:
        args += ["-e", line]
    proc = subprocess.run(args, capture_output=True, text=True)
    if proc.returncode != 0:  # cancelled
        return []
    return [line for line in proc.stdout.splitlines() if line.strip()]


def reveal(path: str, open_file: bool = False) -> None:
    if sys.platform == "darwin":
        subprocess.Popen(["open", path] if open_file else ["open", "-R", path])
    elif sys.platform == "win32":
        if open_file:
            os.startfile(path)  # noqa: S606 - local file the user asked to open
        else:
            subprocess.Popen(["explorer", "/select,", path])
    else:
        target = path if open_file else str(Path(path).parent)
        subprocess.Popen(["xdg-open", target])


# ---------------------------------------------------------------- HTTP

class Handler(BaseHTTPRequestHandler):
    app: AppState
    token: str
    port: int
    server_version = "AVTool"

    def log_message(self, fmt, *args):  # keep the Terminal quiet
        pass

    # -- helpers
    def _send(self, status: int, body: bytes, ctype: str, extra: Optional[dict] = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, data, status: int = 200) -> None:
        self._send(status, json.dumps(data).encode("utf-8"), "application/json; charset=utf-8")

    def _host_ok(self) -> bool:
        # Blocks "DNS rebinding": a website pretending to be 127.0.0.1.
        return self.headers.get("Host", "") in (f"127.0.0.1:{self.port}", f"localhost:{self.port}")

    def _authorised(self) -> bool:
        return self._host_ok() and secrets.compare_digest(self.headers.get("X-AVTool-Token", ""), self.token)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length > 2_000_000:
            raise ValueError("Request too large")
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw or b"{}")

    # -- routes
    def do_GET(self):
        url = urlparse(self.path)
        if not self._host_ok():
            return self._send(403, b"Forbidden", "text/plain")
        if url.path.startswith("/api/"):
            if not self._authorised():
                return self._json({"error": "unauthorised"}, 403)
            q = parse_qs(url.query)
            if url.path == "/api/state":
                return self._json(self.app.snapshot(int((q.get("since") or ["0"])[0] or 0)))
            if url.path == "/api/glossary":
                path = self._glossary_path()
                text = path.read_text(encoding="utf-8") if path.exists() else ""
                g = load_glossary(path)
                return self._json({"text": text, "terms": g.terms, "prompt": g.prompt or ""})
            if url.path == "/api/transcript":
                try:
                    return self._json(self.app.transcript((q.get("id") or [""])[0]))
                except (KeyError, ValueError, OSError) as exc:
                    return self._json({"error": str(exc).strip("'")}, 404)
            return self._json({"error": "not found"}, 404)
        return self._static(url.path)

    def do_POST(self):
        url = urlparse(self.path)
        if not self._authorised():
            return self._json({"error": "unauthorised"}, 403)
        try:
            body = self._body()
        except (ValueError, json.JSONDecodeError):
            return self._json({"error": "bad request"}, 400)
        app = self.app
        try:
            if url.path == "/api/add":
                return self._json(app.add_paths([str(p) for p in body.get("paths", [])]))
            if url.path == "/api/choose":
                kind = body.get("kind", "files")
                chooser = app.dialogs or (mac_choose if sys.platform == "darwin" else None)
                if chooser is None:
                    return self._json({"error": "Native dialogs aren't available here. Paste a path instead."}, 400)
                paths = chooser(kind)
                if kind == "outdir":
                    if paths:
                        app.update_settings({"out": paths[0]})
                    return self._json({"paths": paths, "settings": app.settings})
                return self._json({"paths": paths, **app.add_paths(paths)})
            if url.path == "/api/remove":
                app.remove(body.get("id", ""))
                return self._json({"ok": True})
            if url.path == "/api/clear":
                app.clear(body.get("which", "finished"))
                return self._json({"ok": True})
            if url.path == "/api/start":
                return self._json(app.start())
            if url.path == "/api/stop":
                app.request_stop()
                return self._json({"ok": True})
            if url.path == "/api/settings":
                return self._json(app.update_settings(body))
            if url.path == "/api/glossary":
                text = str(body.get("text", ""))
                if len(text) > 20_000:
                    return self._json({"error": "Glossary is too long. Keep it to a few dozen terms."}, 400)
                if app.running:
                    return self._json({"error": "Save the glossary after the batch finishes."}, 409)
                path = self._glossary_path()
                tmp = path.with_name(path.name + ".partial")
                tmp.write_text(text if text.endswith("\n") or not text else text + "\n", encoding="utf-8")
                os.replace(tmp, path)
                g = load_glossary(path)
                return self._json({"ok": True, "terms": g.terms, "prompt": g.prompt or "",
                                   "truncated": g.truncated})
            if url.path in ("/api/reveal", "/api/open"):
                path = str(body.get("path", ""))
                if not path or not app.allowed_path(path) or not Path(path).exists():
                    return self._json({"error": "That file isn't available."}, 404)
                reveal(path, open_file=url.path == "/api/open")
                return self._json({"ok": True})
        except ValueError as exc:
            return self._json({"error": str(exc)}, 409)
        return self._json({"error": "not found"}, 404)

    def _glossary_path(self) -> Path:
        g = Path(self.app.config.get("glossary") or "glossary.txt")
        return g if g.is_absolute() else PROJECT_DIR / g

    def _static(self, path: str) -> None:
        if path in ("", "/"):
            path = "/index.html"
        target = (STATIC / path.lstrip("/")).resolve()
        if STATIC not in target.parents or not target.is_file():
            return self._send(404, b"Not found", "text/plain")
        ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if target.suffix == ".woff2":
            ctype = "font/woff2"
        if ctype.startswith("text/") or ctype in ("application/javascript", "image/svg+xml"):
            ctype += "; charset=utf-8"
        extra = {}
        if target.name == "index.html":
            # The page may only load its own files and talk to this server.
            extra["Content-Security-Policy"] = (
                "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
                "font-src 'self'; connect-src 'self'; script-src 'self'; frame-ancestors 'none'"
            )
        self._send(200, target.read_bytes(), ctype, extra)


def start_server(app: AppState, port: int = 0) -> tuple[ThreadingHTTPServer, str]:
    token = secrets.token_urlsafe(24)
    handler = type("BoundHandler", (Handler,), {"app": app, "token": token})
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    handler.port = server.server_address[1]
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{handler.port}/#t={token}"
