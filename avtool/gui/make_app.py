"""Build AVTool.app — a double-clickable Mac app for the AVTool window.

    .venv/bin/python -m avtool.gui.make_app

Creates AVTool.app in the project folder (drag it to the Dock). The app is a
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

from .. import __version__
from ..cli import PROJECT_DIR

APP_NAME = "AVTool"
BUNDLE_ID = "com.sebastiansuccess.avtool"
ICON_PNG = Path(__file__).resolve().parent / "static" / "img" / "icon-1024.png"

LAUNCHER = """#!/bin/bash
# AVTool launcher — opens the AVTool window using this project's Python.
PROJECT={project}
LOG="$HOME/Library/Logs/AVTool.log"
if [[ ! -x "$PROJECT/.venv/bin/python" ]]; then
  /usr/bin/osascript -e 'display alert "AVTool needs setup" message "Open Terminal in the AVTool folder and run:  bash setup_mac.command" as critical'
  exit 1
fi
cd "$PROJECT" || exit 1
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
    app = dest_dir / f"{APP_NAME}.app"
    if app.exists():
        shutil.rmtree(app)
    macos = app / "Contents" / "MacOS"
    resources = app / "Contents" / "Resources"
    macos.mkdir(parents=True)
    resources.mkdir(parents=True)

    launcher = macos / APP_NAME
    launcher.write_text(LAUNCHER.format(project=_shell_quote(str(PROJECT_DIR))))
    launcher.chmod(0o755)

    has_icon = make_icns(ICON_PNG, resources / "AppIcon.icns")
    info = {
        "CFBundleName": APP_NAME,
        "CFBundleDisplayName": APP_NAME,
        "CFBundleIdentifier": BUNDLE_ID,
        "CFBundleExecutable": APP_NAME,
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": "1.0",
        "CFBundleVersion": __version__,
        "LSMinimumSystemVersion": "11.0",
        "LSApplicationCategoryType": "public.app-category.video",
        "NSHighResolutionCapable": True,
        "NSHumanReadableCopyright": "Sebastian Success · personal offline tool",
    }
    if has_icon:
        info["CFBundleIconFile"] = "AppIcon"
    with open(app / "Contents" / "Info.plist", "wb") as f:
        plistlib.dump(info, f)
    os.utime(app, None)  # nudge Finder to pick up the icon
    return app


def main() -> int:
    if sys.platform != "darwin":
        print("AVTool.app is a Mac app; on this computer run:  python -m avtool.gui")
    app = build()
    print(f"✓ Built {app}")
    print("  Double-click it to open AVTool. Drag it to the Dock to keep it handy.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
