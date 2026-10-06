"""Open the AVTool window.

    python -m avtool.gui            # the app (what AVTool.app runs)
    python -m avtool.gui --browser  # same interface in a browser tab instead

The window is a native macOS window (WebKit, via pywebview). If pywebview
isn't installed, the interface opens in the default browser instead.
"""

from __future__ import annotations

import argparse
import sys
import threading
import time
import webbrowser
from pathlib import Path

from .. import __version__
from .server import STATIC, AppState, start_server

TITLE = "AVTool — Sebastian Success"
ICON = STATIC / "img" / "icon-1024.png"


def _mac_branding() -> None:
    """Show 'AVTool' in the menu bar instead of 'Python'. (The Dock icon is set
    by webview.start(icon=...).) Must run before the window starts."""
    if sys.platform != "darwin":
        return
    try:
        from Foundation import NSBundle
        info = NSBundle.mainBundle().infoDictionary()
        if info is not None:
            info["CFBundleName"] = "AVTool"
    except Exception:
        pass  # purely cosmetic


def _webview_dialogs(window):
    import webview
    dialog = getattr(webview, "FileDialog", None)
    open_kind = dialog.OPEN if dialog else webview.OPEN_DIALOG
    folder_kind = dialog.FOLDER if dialog else webview.FOLDER_DIALOG
    media = ("Video & audio (*.mov;*.MOV;*.mp4;*.MP4;*.mkv;*.webm;*.wmv;*.mp3;*.wav;*.flac;*.aac;*.m4a)",
             "All files (*.*)")

    def choose(kind: str) -> list[str]:
        if kind in ("folder", "outdir"):
            result = window.create_file_dialog(folder_kind)
        else:
            result = window.create_file_dialog(open_kind, allow_multiple=True, file_types=media)
        if not result:
            return []
        return [str(p) for p in (result if isinstance(result, (list, tuple)) else [result])]

    return choose


def _bind_drop(window, app: AppState) -> None:
    """Files and folders dragged from Finder onto the window join the queue."""
    try:
        from webview.dom import DOMEventHandler
    except ImportError:
        return

    def on_drop(event):
        files = (event.get("dataTransfer") or {}).get("files") or []
        # pywebview 6 calls it pywebviewFullPath; 5.x called it pywebview_full_path.
        paths = [f.get("pywebviewFullPath") or f.get("pywebview_full_path") for f in files]
        paths = [p for p in paths if p]
        if paths:
            result = app.add_paths(paths)
            app.add_log(f"＋ Added {result['added']} file(s) by drag and drop")

    def ignore(event):
        pass

    doc = window.dom.document
    doc.events.dragenter += DOMEventHandler(ignore, True, True)
    doc.events.dragover += DOMEventHandler(ignore, True, True, debounce=500)
    doc.events.drop += DOMEventHandler(on_drop, True, True)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="avtool.gui", description=TITLE)
    parser.add_argument("--browser", action="store_true", help="open in the browser instead of a window")
    parser.add_argument("--port", type=int, default=0, help=argparse.SUPPRESS)
    parser.add_argument("--backend", help=argparse.SUPPRESS)  # e.g. 'test' for demos
    parser.add_argument("--no-open", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    app = AppState(backend_choice=args.backend)
    server, url = start_server(app, args.port)
    app.add_log(f"AVTool {__version__} ready · everything stays on this Mac")

    webview = None
    if not args.browser:
        try:
            import webview  # pywebview
        except ImportError:
            print("pywebview isn't installed; opening in your browser instead.")

    if webview is None:
        print(f"AVTool is running at {url}\nClose this window (or press Ctrl+C) to quit.")
        if not args.no_open:
            webbrowser.open(url)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
    else:
        _mac_branding()
        window = webview.create_window(
            TITLE, url, width=1320, height=860, min_size=(1100, 720),
            background_color="#040a1c", text_select=True,
        )
        app.dialogs = _webview_dialogs(window)
        webview.start(_bind_drop, (window, app), icon=str(ICON), private_mode=True)

    # Window closed: if a batch is running, stop it cleanly (temp audio removed,
    # no half-written files) before quitting.
    if app.running:
        app.request_stop()
        if app.thread:
            app.thread.join(timeout=60)
    server.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
