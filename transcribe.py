#!/usr/bin/env python3
"""AVTool CMOS — free, offline transcripts and subtitles for video and audio.

    python transcribe.py "/Volumes/LaCie/Shoot"            # a whole folder
    python transcribe.py "/Volumes/LaCie/Shoot/IMG_0042.MOV"  # one file
    python transcribe.py --help                              # every option

See README.md for setup and plain-language instructions.
"""

import sys

from avtool.cli import main

if __name__ == "__main__":
    sys.exit(main())
