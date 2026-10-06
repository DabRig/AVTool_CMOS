#!/bin/bash
# Double-click to transcribe. It asks you to drag in a folder or file.
# Or from Terminal:  ./Transcribe.command "/Volumes/LaCie/Shoot" --lang en
cd "$(dirname "$0")"
if [[ ! -x .venv/bin/python ]]; then
  echo "Setup hasn't been run yet. In Terminal, run:  bash setup_mac.command"
  read -r -p "Press Enter to close." _
  exit 1
fi
.venv/bin/python transcribe.py "$@"
echo
read -r -p "Finished. Press Enter to close this window." _
