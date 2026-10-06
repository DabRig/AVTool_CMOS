"""Tests for the app's engine room (avtool/gui/server.py), using the test engine.

The window itself is plain HTML/JS on top of these calls.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from avtool.gui import server as srv  # noqa: E402


@pytest.fixture(scope="module")
def clip_source(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("clips")
    subprocess.run([sys.executable, str(ROOT / "samples" / "make_samples.py"), "--out", str(out)],
                   check=True, capture_output=True)
    return out


@pytest.fixture
def app(tmp_path, clip_source, monkeypatch):
    monkeypatch.setattr(srv, "GUI_SETTINGS", tmp_path / "gui_settings.json")
    clips = tmp_path / "clips"
    shutil.copytree(clip_source, clips)
    glossary = tmp_path / "glossary.txt"
    glossary.write_text("Evan\nSmooth Scaling\n")
    state = srv.AppState(backend_choice="test", temp_root=tmp_path / "temp")
    state.config["glossary"] = str(glossary)
    state.settings["keep_awake"] = False
    server, url = srv.start_server(state)
    base, token = url.split("/#t=")
    yield {"state": state, "base": base, "token": token, "clips": clips, "glossary": glossary}
    server.shutdown()


def call(app, path, body=None, token=None, host=None):
    req = urllib.request.Request(app["base"] + path, data=None if body is None else json.dumps(body).encode())
    req.add_header("X-AVTool-Token", app["token"] if token is None else token)
    if body is not None:
        req.add_header("Content-Type", "application/json")
    if host:
        req.add_header("Host", host)
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())


def wait_until(app, condition, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        s = call(app, "/api/state")
        if condition(s):
            return s
        time.sleep(0.2)
    raise AssertionError("timed out")


def test_locked_down(app):
    with pytest.raises(urllib.error.HTTPError) as e:
        call(app, "/api/state", token="wrong")
    assert e.value.code == 403
    with pytest.raises(urllib.error.HTTPError) as e:  # DNS-rebinding style request
        call(app, "/api/state", host="evil.example:80")
    assert e.value.code == 403
    with pytest.raises(urllib.error.HTTPError) as e:  # files outside the app can't be opened
        call(app, "/api/open", {"path": "/etc/passwd"})
    assert e.value.code == 404
    with pytest.raises(urllib.error.HTTPError) as e:  # no escaping the static folder
        urllib.request.urlopen(app["base"] + "/../../cli.py", timeout=5)
    assert e.value.code in (403, 404)
    page = urllib.request.urlopen(app["base"] + "/", timeout=5)
    assert "SEBASTIAN SUCCESS" in page.read().decode()
    assert "default-src 'self'" in page.headers["Content-Security-Policy"]


def test_queue_run_and_view(app):
    r = call(app, "/api/add", {"paths": [str(app["clips"])]})
    assert r["added"] == 16  # 18 files minus the ._sample.mov and .hidden.mov junk
    s = wait_until(app, lambda s: not any(i["status"] == "probing" for i in s["items"]))
    by_name = {i["name"]: i for i in s["items"]}
    assert by_name["corrupt.mov"]["status"] == "failed"
    assert by_name["no_audio.mp4"]["status"] == "skipped"
    assert by_name["sample.mov"]["status"] == "ready" and by_name["sample.mov"]["duration"] > 1

    assert call(app, "/api/add", {"paths": [str(app["clips"])]})["added"] == 0  # no duplicates

    assert call(app, "/api/start", {})["ok"] is True
    with pytest.raises(urllib.error.HTTPError) as e:  # settings locked while running
        call(app, "/api/settings", {"model": "small"})
    assert e.value.code == 409
    s = wait_until(app, lambda s: not s["running"])
    statuses = {i["name"]: i["status"] for i in s["items"]}
    assert list(statuses.values()).count("done") == 14
    assert s["last_run"]["counts"]["done"] == 14

    item = by_name["sample.mov"]
    t = call(app, f"/api/transcript?id={item['id']}")
    assert t["segments"] and set(t["files"]) == {"txt", "timestamped", "srt", "vtt", "docx", "json"}
    assert app["state"].allowed_path(t["files"]["srt"])  # its own outputs may be opened
    assert not app["state"].allowed_path(str(ROOT / "transcribe.py"))  # nothing else

    assert call(app, "/api/start", {})["ok"] is False  # nothing left to do
    call(app, "/api/settings", {"force": True})
    assert call(app, "/api/start", {})["ok"] is True  # redo finished files
    wait_until(app, lambda s: not s["running"])


def test_stop_cleans_up(app, monkeypatch):
    monkeypatch.setenv("AVTOOL_TEST_DELAY", "0.02")
    call(app, "/api/add", {"paths": [str(app["clips"] / "sample.wav"), str(app["clips"] / "sample.mp3")]})
    wait_until(app, lambda s: all(i["status"] == "ready" for i in s["items"]))
    call(app, "/api/start", {})
    wait_until(app, lambda s: any(i["status"] == "running" and i["stage"] == "transcribe" for i in s["items"]))
    call(app, "/api/stop", {})
    s = wait_until(app, lambda s: not s["running"])
    assert s["last_run"]["interrupted"] is True
    assert {i["status"] for i in s["items"]} == {"stopped"}
    assert not list(app["clips"].glob("*.partial")) and not list(app["clips"].glob("sample.wav.json"))
    temp = app["state"].temp_root / "avtool_cmos"
    assert not [p for p in temp.rglob("*") if p.is_file()]
    monkeypatch.delenv("AVTOOL_TEST_DELAY")
    call(app, "/api/start", {})  # resume
    s = wait_until(app, lambda s: not s["running"])
    assert {i["status"] for i in s["items"]} == {"done"}


def test_settings_and_glossary(app, tmp_path):
    s = call(app, "/api/settings", {"model": "medium", "captions": "reels", "formats": ["srt"], "lang": "auto"})
    assert s["model"] == "medium" and s["captions"] == "reels" and s["formats"] == ["srt", "json"]
    s = call(app, "/api/settings", {"model": "gigantic", "captions": "weird", "bogus": 1})
    assert s["model"] == "medium" and s["captions"] == "reels" and "bogus" not in s
    assert json.loads((tmp_path / "gui_settings.json").read_text())["model"] == "medium"

    g = call(app, "/api/glossary")
    assert g["terms"] == ["Evan", "Smooth Scaling"]
    r = call(app, "/api/glossary", {"text": "Evan\nlightening os -> Lightning OS"})
    assert r["terms"] == ["Evan", "Lightning OS"]
    assert "Lightning OS" in app["glossary"].read_text()


def test_custom_output_folder(app, tmp_path):
    out = tmp_path / "Transcripts"
    out.mkdir()
    call(app, "/api/settings", {"out": str(out)})
    call(app, "/api/add", {"paths": [str(app["clips"] / "sample.flac")]})
    wait_until(app, lambda s: s["items"] and s["items"][0]["status"] == "ready")
    call(app, "/api/start", {})
    wait_until(app, lambda s: not s["running"])
    assert (out / "sample.flac.srt").exists() and not (app["clips"] / "sample.flac.srt").exists()
