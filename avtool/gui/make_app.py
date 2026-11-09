"""Build "AV Transcriber.app" — a double-clickable Mac app for the app window.

    .venv/bin/python -m avtool.gui.make_app

Creates "AV Transcriber.app" in the project folder (drag it to the Dock). The app is a
small launcher that runs this project's private Python (.venv), so it must be
rebuilt if the project folder moves: run setup_mac.command again.

Uses only tools built into macOS (sips, iconutil) to make the icon.
"""

from __future__ import annotations

import os
import plistlib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from .. import APP_NAME, __version__
from ..cli import PROJECT_DIR

OLD_APP_NAMES = ("AVTool",)  # earlier versions' app name: removed when rebuilding
EXECUTABLE = "AVTranscriber"
BUNDLE_ID = "com.sebastiansuccess.avtool"
ICON_PNG = Path(__file__).resolve().parent / "static" / "img" / "icon-1024.png"

LAUNCHER = """#!/bin/bash
# AV Transcriber launcher — opens the app window using this project's Python.
PROJECT={project}
LOG="$HOME/Library/Logs/AV Transcriber.log"
if [[ ! -x "$PROJECT/.venv/bin/python" ]]; then
  /usr/bin/osascript -e 'display alert "AV Transcriber needs setup" message "Open Terminal in the AV Transcriber folder and run:  bash setup_mac.command" as critical'
  exit 1
fi
cd "$PROJECT" || exit 1
# Apps opened from Finder don't see Homebrew's folder; add it so ffmpeg is found.
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
echo "--- $(date) ---" >> "$LOG"
exec "$PROJECT/.venv/bin/python" -m avtool.gui "$@" >> "$LOG" 2>&1
"""


def _shell_quote(text: str) -> str:
    return "'" + text.replace("'", "'\"'\"'") + "'"


def make_icns(png: Path, out: Path) -> bool:
    if not (shutil.which("sips") and shutil.which("iconutil")):
        return False
    with tempfile.TemporaryDirectory() as tmp:
        iconset = Path(tmp) / "AppIcon.iconset"
        iconset.mkdir()
        for size in (16, 32, 128, 256, 512):
            for scale in (1, 2):
                px = size * scale
                name = f"icon_{size}x{size}{'@2x' if scale == 2 else ''}.png"
                subprocess.run(["sips", "-z", str(px), str(px), str(png), "--out", str(iconset / name)],
                               check=True, capture_output=True)
        subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(out)], check=True, capture_output=True)
    return True


def build(dest_dir: Path = PROJECT_DIR) -> Path:
    for old in OLD_APP_NAMES:
        if (dest_dir / f"{old}.app").exists():
            shutil.rmtree(dest_dir / f"{old}.app")
    app = dest_dir / f"{APP_NAME}.app"
    if app.exists():
        shutil.rmtree(app)
    macos = app / "Contents" / "MacOS"
    resources = app / "Contents" / "Resources"
    macos.mkdir(parents=True)
    resources.mkdir(parents=True)

    launcher = macos / EXECUTABLE
    launcher.write_text(LAUNCHER.format(project=_shell_quote(str(PROJECT_DIR))), encoding="utf-8")
    launcher.chmod(0o755)

    has_icon = make_icns(ICON_PNG, resources / "AppIcon.icns")
    info = {
        "CFBundleName": APP_NAME,
        "CFBundleDisplayName": APP_NAME,
        "CFBundleIdentifier": BUNDLE_ID,
        "CFBundleExecutable": EXECUTABLE,
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": "1.0",
        "CFBundleVersion": __version__,
        "LSMinimumSystemVersion": "11.0",
        "LSApplicationCategoryType": "public.app-category.video",
        "NSHighResolutionCapable": True,
        "NSHumanReadableCopyright": "Personal offline tool",
    }
    if has_icon:
        info["CFBundleIconFile"] = "AppIcon"
    with open(app / "Contents" / "Info.plist", "wb") as f:
        plistlib.dump(info, f)
    os.utime(app, None)  # nudge Finder to pick up the icon
    return app


def main() -> int:
    if sys.platform != "darwin":
        print(f"{APP_NAME}.app is a Mac app; on this computer run:  python -m avtool.gui")
    app = build()
    print(f"✓ Built {app}")
    print(f"  Double-click it to open {APP_NAME}. Drag it to the Dock to keep it handy.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
