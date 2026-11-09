"""Open the AV Transcriber window.

    python -m avtool.gui            # the app (what "AV Transcriber.app" runs)
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

from .. import APP_NAME, __version__
from .server import STATIC, AppState, start_server

TITLE = APP_NAME
ICON = STATIC / "img" / "icon-1024.png"
ICON_ICO = STATIC / "img" / "icon.ico"  # Windows wants .ico for window/taskbar icons


def _windows_identity() -> None:
    """Give the app its own taskbar identity (its icon, not Python's)."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("SebastianSuccess.AVTranscriber")
    except Exception:
        pass  # purely cosmetic


def _mac_branding() -> None:
    """Show the app name in the menu bar instead of 'Python'. (The Dock icon is set
    by webview.start(icon=...).) Must run before the window starts."""
    if sys.platform != "darwin":
        return
    try:
        from Foundation import NSBundle
        info = NSBundle.mainBundle().infoDictionary()
        if info is not None:
            info["CFBundleName"] = APP_NAME
    except Exception:
        pass  # purely cosmetic


def _window_size(webview) -> tuple[int, int]:
    """A comfortable window that still fits a laptop screen (and Windows' taskbar)."""
    width, height = 1440, 920
    try:
        screen = webview.screens[0]
        width = min(width, int(screen.width * 0.94))
        height = min(height, int(screen.height * 0.88))
    except Exception:
        pass
    return max(width, 1000), max(height, 660)


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
    app.add_log(f"{APP_NAME} {__version__} ready · everything stays on this computer")

    webview = None
    if not args.browser:
        try:
            import webview  # pywebview
        except ImportError:
            print("pywebview isn't installed; opening in your browser instead.")

    if webview is None:
        print(f"{APP_NAME} is running at {url}\nClose this window (or press Ctrl+C) to quit.")
        if not args.no_open:
            webbrowser.open(url)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
    else:
        _mac_branding()
        _windows_identity()
        width, height = _window_size(webview)
        window = webview.create_window(
            TITLE, url, width=width, height=height, min_size=(1000, 660),
            background_color="#040a1c", text_select=True,
        )
        app.dialogs = _webview_dialogs(window)
        webview.start(_bind_drop, (window, app), icon=str(ICON_ICO if sys.platform == "win32" else ICON),
                      private_mode=True)

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
