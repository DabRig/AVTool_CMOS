#!/bin/bash
# AVTool — update to the latest version, keeping your settings and installation.
# Run it by typing:  bash update.command
#
# Downloads the newest code from GitHub, copies it over this folder, then runs
# the setup again (which only installs what's new). Your glossary.txt,
# config.toml, app settings and transcripts are kept.

set -eo pipefail
cd "$(dirname "$0")"
URL="https://github.com/DabRig/AVTool_CMOS/archive/refs/heads/claude/optimistic-thompson-as38s7.zip"

printf "\n\033[1mUpdating AVTool…\033[0m\n"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
curl -fsSL "$URL" -o "$TMP/avtool.zip" || { echo "  ✗ Download failed. Check the internet connection."; exit 1; }
unzip -q "$TMP/avtool.zip" -d "$TMP"
NEW="$(find "$TMP" -mindepth 1 -maxdepth 1 -type d | head -1)"
[[ -f "$NEW/transcribe.py" ]] || { echo "  ✗ The download looks wrong; nothing was changed."; exit 1; }

# Keep personal files: they are only copied if they don't exist here yet.
rsync -a --ignore-existing "$NEW/glossary.txt" "$NEW/config.toml" ./
rsync -a --exclude ".venv" --exclude "glossary.txt" --exclude "config.toml" \
      --exclude "gui_settings.json" --exclude "samples/clips" --exclude "AVTool.app" "$NEW/" ./
echo "  ✓ Code updated"

bash setup_mac.command
