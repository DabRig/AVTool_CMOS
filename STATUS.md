# Status against SPEC.md

Written Oct 6, 2026. Updated for **V1.0** (the AVTool app) on top of Rendition 3.

## 1. Review of the starting point

The repository had **no `transcribe.py`**, only a one-line README, so there was
no earlier rendition to review. The gaps were therefore everything in
SPEC.md. Renditions 1–3 and the project setup (phase 4) were built together
here, on a structure small enough to own and extend.

## 2. Build phases

| Phase | Status |
| --- | --- |
| R1: one file in, `.txt` out | ✅ (single-file input still works: `transcribe.py file.mov`) |
| R2: folder input, ffprobe check, every format, five outputs, temp cleanup, log | ✅ plus `.docx` and `.m4a` |
| R3: resume/skip, per-file errors, progress bars, disk-space check, glossary, setup script | ✅ |
| Phase 4: README, `requirements*.txt`, `config.toml`, `samples/` | ✅ |
| R4: GUI, speaker labels, reels preset, watch folder, summaries/chapters | ◐ **GUI (AVTool.app, V1.0)** and **reels preset** done; the rest is still to do (see section 5) |

## 3. Spec requirements: how each is met

| Requirement | Where / how |
| --- | --- |
| Case-insensitive extensions; skip hidden and `._` files | `media.scan` |
| `--recursive` | `media.scan`; with `--out`, subfolders are mirrored so names can't collide |
| Probe every file; "no audio" is skipped, not a crash | `media.probe` / `choose_track` (runs before any extraction) |
| 16 kHz mono 16-bit WAV in a temp folder, not next to the source | `media.extract_audio`, into `<system temp>/avtool_cmos/run-<pid>/` |
| `-map 0:a:N`, never a blind mix; `--audio-track N` | 1-based (track 1 = first). Per-file overrides go in `config.toml [audio_tracks]`. Automatic mode skips audio tracks this ffmpeg can't decode. |
| ffmpeg called with argument lists, never a shell string | Everywhere. Paths are absolute, so a name starting with `-` can't be mistaken for an option. |
| Never load whole media files into memory | ffmpeg streams. Measured: a 1.3 GB video peaked at **56 MB** RAM. |
| mlx-whisper on Apple Silicon, faster-whisper on CUDA float16 or CPU int8 | `backends.resolve_backend`, override with `--backend` |
| VAD and `condition_on_previous_text=False` | faster-whisper: `vad_filter=True`. mlx-whisper has no VAD, so it uses `hallucination_silence_threshold=2s` plus word timestamps instead. Both engines also get a cleanup pass that drops phantom phrases, silence and loops. |
| `small` / `medium` for drafts | `--model small` |
| Delete temp WAV after each file; clear crashed-run leftovers at startup | `batch._process` `finally:`; `batch.make_temp_dir` removes folders of dead runs |
| Five outputs with full source name | `writers` (+ `.docx`) |
| SRT ≤42 chars, ≤2 lines, ≤7 s | `text.CAPTION_PRESETS["standard"]`, enforced by tests |
| Atomic writes, `.json` last as the "done" marker, `--force` | `writers._atomic`, `write_all` |
| Batch progress, per-file bars, time-left estimate | `batch.run` / `Progress` (mlx shows its own bar in "frames") |
| `log.txt`: name, duration, model, language, time, errors | `batch.Log` (failures include the full error details) |
| One bad file never stops the batch; summary at the end | `batch._process` catches everything except Ctrl+C |
| Keep the computer awake | `caffeinate -i -s -w <pid>` (Mac), `SetThreadExecutionState` (Windows) |
| Disk-space check | 2 × largest temp WAV + margin on the temp drive; output space checked too |
| Glossary as `hotwords` / `initial_prompt`, kept short | ✅ plus two extras below |
| `--lang auto/en/es` | ✅. Set to `en` in `config.toml` because your recordings are English. |

**Extras not in the spec:**
- **The glossary works for the whole file on Mac.** mlx-whisper normally forgets
  `initial_prompt` after the first 30 seconds when `condition_on_previous_text`
  is off. A small, self-restoring wrapper re-applies it to every 30-second window,
  the same way faster-whisper's `hotwords` work.
- **"wrong -> right" fixes and capitalisation** are applied to all outputs.
- `--boost-quiet` evens out quiet audience questions (ffmpeg `dynaudnorm`, still streamed).
- `--list-tracks`, `--dry-run`, `--check`, `--download-model`; drag-a-folder prompt.
- An error appears up front if the output drive is read-only (e.g. NTFS LaCie on a Mac).
- Model files are used offline once downloaded (`HF_HUB_OFFLINE`), and usage statistics are turned off.

## 4. "Done when" checklist

| Item | Status |
| --- | --- |
| All 6 .mov files in one unattended run, offline | ⏳ **needs your Mac and the LaCie** (README Step 4) |
| One sample of each format transcribes without errors | ✅ All 9 formats + `.m4a` go through probe, extract and outputs (automated tests). ⏳ Real speech recognition needs your Mac (README Step 2). |
| No-audio / corrupt file is logged and skipped; batch continues | ✅ tested |
| Extra disk use under ~2 GB | ✅ one WAV at a time; a 48-min file ≈ 92 MB |
| `.srt` imports cleanly; within ~0.5 s of speech | ✅ format and limits tested. ⏳ timing check in Premiere/CapCut (README Step 3) |
| Glossary names mostly right | ⏳ needs real speech (Step 2 clips say "Evan", "Smooth Scaling", "Lightning OS") |
| Kill mid-way, restart resumes, no half-finished files | ✅ tested (simulated Ctrl+C mid-file, then re-run) |
| Non-coder installs in under 15 minutes | ⏳ your call: README Step 1 |

**How it was tested:** `python -m pytest -q` runs 16 automated checks on the
sample clips with a stand-in engine. Real Whisper models couldn't be downloaded
on the build machine. The Mac (mlx-whisper) code path was also run end to end
there, using a tiny randomly-initialised model on MLX's Linux CPU build. That
confirmed the settings, the glossary-every-window wrapper and the result
parsing. Real transcription quality and speed can only be judged on the Mac.

## 5. Still to do (Rendition 4 and beyond)

1. **Speaker labels** ("Evan:" / "Question:"), via pyannote or WhisperX. Needs a free
   Hugging Face token, adds setup, and will be optional.
2. **Watch folder:** auto-transcribe new files dropped into a folder (Buzz-style).
3. **Summary and chapter markers** per file.
4. **Noisy-audio cleanup** (speech separation, as in Buzz), if `--boost-quiet` isn't enough.
5. Windows setup script is written but **untested on real Windows hardware**.

## 6. V1.0: the AVTool app

| Piece | Status |
| --- | --- |
| Native Mac window (pywebview/WebKit) opened from **AVTool.app** with the SS icon | ✅ built by `setup_mac.command`. ⏳ first real launch is on your Mac |
| Batch queue, drag-and-drop, ＋FILES/＋FOLDER (native Finder pickers), live progress, STOP/resume | ✅ tested in a browser with the test engine. ⏳ drag-and-drop from Finder only works in the Mac window |
| Settings panel: quality knob, language, captions, switches, output folder, formats | ✅ tested |
| Transcript viewer (search, click-to-copy, open TXT/SRT/DOCX, show in Finder) | ✅ tested |
| Glossary editor | ✅ tested |
| Security: listens on 127.0.0.1 only, random per-launch key, Host check, page allowed to load only its own files, only the app's own media and outputs can be opened | ✅ automated tests |
| Live progress from the Mac engine (mlx-whisper) | ✅ its internal progress bar is rerouted to the app (checked with a tiny test model) |
| `update.command`: one-command updates that keep glossary, settings and transcripts | ✅ written. ⏳ first real use on your Mac |

## 7. V1.1: brand and space theme

- Sebastian's own logo (`ss-logo.png`) replaces the placeholder monogram. It's used
  in the header (brand blue #0066FF with an icy highlight and an orbit ring), in the
  drop zone (as a planet with two orbiting moons), and in the app icon (a deep-space
  rounded square with stars, nebula and a ring).
- Animated starfield (`static/stars.js`): three depths of stars, twinkle, slow drift,
  and a rare shooting star. It runs at about 30 fps, pauses when the window is
  hidden, and holds still when Reduce motion is on.
- Glass panels let the stars show through.
