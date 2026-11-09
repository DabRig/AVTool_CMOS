import os
import sys
from pathlib import Path

# Started from a Windows shortcut (pythonw.exe) there is no console: Python's
# output streams are None, and anything printing (progress bars, logs) would
# crash. Send that output to a log file instead.
if sys.stdout is None or sys.stderr is None:
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "AV Transcriber"
    base.mkdir(parents=True, exist_ok=True)
    log = open(base / "app.log", "a", encoding="utf-8", buffering=1)
    sys.stdout = sys.stdout or log
    sys.stderr = sys.stderr or log

from .app import main  # noqa: E402

sys.exit(main())
