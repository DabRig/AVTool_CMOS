#!/bin/bash
# AVTool CMOS — one-time setup for a Mac.
# Run it by typing:  bash setup_mac.command   (or double-click it in Finder)
# Safe to run again: it skips anything already installed.

set -eo pipefail
cd "$(dirname "$0")"

bold() { printf "\n\033[1m%s\033[0m\n" "$1"; }
ok()   { printf "  ✓ %s\n" "$1"; }
fail() {
  printf "\n  ✗ %s\n\n" "$1"
  read -r -p "Press Enter to close." _ || true
  exit 1
}
trap 'fail "Something went wrong (see the messages above). Re-running the setup usually fixes network hiccups."' ERR

bold "AVTool CMOS setup — about 10–15 minutes, mostly downloading."
echo "  Needs internet this one time. After this, transcription works fully offline."

# --- Which kind of Mac? -------------------------------------------------------
ARCH="$(uname -m)"
if [[ "$ARCH" == "arm64" ]]; then
  REQS="requirements-mac.txt"
  ok "Apple Silicon Mac — using the fast MLX engine (runs on the Mac's GPU)"
elif [[ "$(sysctl -n sysctl.proc_translated 2>/dev/null)" == "1" ]]; then
  fail "This Terminal is running in Intel (Rosetta) mode. In Finder go to Applications › Utilities, select Terminal, press ⌘I and untick 'Open using Rosetta'. Then run setup again."
else
  REQS="requirements-cpu.txt"
  ok "Intel Mac — using faster-whisper on the CPU (works, but slower)"
fi

# --- 1. Homebrew --------------------------------------------------------------
bold "Step 1/5 · Homebrew (installs developer tools on the Mac)"
load_brew() {
  for b in /opt/homebrew/bin/brew /usr/local/bin/brew; do
    if [[ -x "$b" ]]; then eval "$("$b" shellenv)"; return 0; fi
  done
  return 1
}
command -v brew >/dev/null 2>&1 || load_brew || true
if ! command -v brew >/dev/null 2>&1; then
  echo "  Installing Homebrew. It will ask for your Mac login password."
  echo "  (Nothing appears while you type the password — that's normal. Press Enter after.)"
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  load_brew || fail "Homebrew didn't install. Visit https://brew.sh and try again."
fi
if [[ "$ARCH" == "arm64" && "$(brew --prefix)" != "/opt/homebrew" ]]; then
  fail "Found an Intel copy of Homebrew ($(brew --prefix)). Install the Apple Silicon one from https://brew.sh, then re-run."
fi
ok "Homebrew $(brew --version | head -1 | awk '{print $2}')"

# --- 2. ffmpeg + Python ------------------------------------------------------
bold "Step 2/5 · ffmpeg (reads video files) and Python 3.12"
brew list ffmpeg >/dev/null 2>&1 || brew install ffmpeg
brew list python@3.12 >/dev/null 2>&1 || brew install python@3.12
PY="$(brew --prefix python@3.12)/bin/python3.12"
[[ -x "$PY" ]] || fail "Python 3.12 wasn't found after installing it."
ok "$(ffmpeg -version | head -1 | awk '{print $1, $2, $3}')"
ok "$("$PY" --version)"

# --- 3. Private Python environment -----------------------------------------
bold "Step 3/5 · Whisper and friends (into a private folder called .venv)"
if [[ -x .venv/bin/python ]]; then
  VENV_ARCH="$(.venv/bin/python -c 'import platform; print(platform.machine())' 2>/dev/null || echo broken)"
  if [[ "$VENV_ARCH" != "$ARCH" ]]; then
    echo "  Rebuilding .venv (it was made for a different setup)"
    rm -rf .venv
  fi
fi
[[ -x .venv/bin/python ]] || "$PY" -m venv .venv
.venv/bin/python -m pip install --upgrade pip --quiet
.venv/bin/python -m pip install -r "$REQS" --quiet
ok "Python packages installed ($REQS)"

# --- 4. The model -------------------------------------------------------------
bold "Step 4/5 · Downloading the Whisper model (one time, about 1.6 GB)"
.venv/bin/python transcribe.py --download-model

# --- 5. Check -----------------------------------------------------------------
bold "Step 5/5 · Making test clips and checking everything"
.venv/bin/python samples/make_samples.py >/dev/null && ok "Test clips made in samples/clips"
chmod +x Transcribe.command setup_mac.command 2>/dev/null || true
trap - ERR
.venv/bin/python transcribe.py --check || true

bold "Setup complete!"
echo "  Next: test it on the sample clips — see 'Step 2' in README.md."
read -r -p "Press Enter to close." _ || true
