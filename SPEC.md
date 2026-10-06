# MOV Transcriber — Build Spec

Oct 6, 2026 · @Sebastian

## Goal

Build a free, local tool that turns any video or audio file into accurate, timestamped transcripts. It must handle the first job: 6 .mov files, 18.07 GB total. It needs no uploads, no credits and has no file-size caps.

- **Supported formats:** video — .mov, .mp4, .mkv, .webm, .wmv; audio — .mp3, .wav, .flac, .aac (plus .m4a as a freebie). Extensions match case-insensitively, so cameras' `.MOV` / `.MP4` count.
- **Why local:** online tools choke on multi-GB files. Running on my own machine removes bandwidth, credit and size limits.
- **Key insight:** video is \~99% of the file size. The tool keeps only a 16 kHz mono audio copy, about 115 MB per hour of runtime, whatever the source size.
- **Cost:** $0. Uses open-source tools only (ffmpeg + OpenAI's Whisper model run locally). One-time internet is needed for setup and the \~1.5 GB model download; after that it runs offline.

## Reference projects

Both repos are free, offline Whisper apps under the MIT license. They already cover most of this spec, so they serve as working references, not something to copy wholesale. Either can also run the 18 GB job today while this tool is being built.

| Project | Built with | What it already does | What to borrow |
| --- | --- | --- | --- |
| [Buzz](https://github.com/chidiwilliams/buzz) — 21.7k stars | Python 3.12, desktop app + CLI; whisper.cpp, faster-whisper and Hugging Face backends | Audio/video files, TXT/SRT/VTT export, CUDA on NVIDIA, Apple Silicon support, speaker ID, speech separation for noisy audio, watch folder, CLI | **Closest match to this tool's stack.** Study how it picks a backend per machine, its CLI flags, the watch-folder feature, and its noisy-audio cleanup step. Note: Buzz now requires Apple Silicon on Mac (last Intel version 1.4.5). |
| [Vibe](https://github.com/thewh1teagle/vibe) — 6.7k stars, v3.0.20 (Jul 2026) | Rust + TypeScript desktop app (Tauri) on whisper.cpp | Batch files; SRT/VTT/TXT/HTML/PDF/JSON/DOCX; GPU on Mac, NVIDIA, AMD and Intel; CLI; local HTTP API; speaker diarization; VAD-backed stable-timestamps mode; caption length tuned for reels | Ideas, not code — it's a different language. Copy the **reels caption-length preset**, the **stable timestamps** mode for editor-grade subtitles, and the output-format list. |

What this tool adds over both: resume-safe batching, per-file audio-track choice for multi-track camera files, collision-proof output names, a glossary for brand names, and a codebase I own and can extend in Claude Code. If none of that matters for a job, use Buzz or Vibe directly.

## Approach

The tool runs a five-step pipeline on each file, one file at a time. Video and audio files take the same path, since ffmpeg reads all the listed formats.

1. **Scan** a folder for supported files. Subfolders are optional (`--recursive`). Skip hidden files and macOS `._` sidecar files, which external drives are full of and which look like real .mov files but aren't.
2. **Probe** each file with `ffprobe`. Record its duration and audio streams. If it has **no audio stream**, log "no audio" and skip it rather than crash.
3. **Normalize audio** to a temp WAV (16 kHz, mono, 16-bit) in a temp folder, not next to the source:
   - Command shape: `ffmpeg -y -nostdin -i INPUT -map 0:a:0 -vn -ac 1 -ar 16000 -c:a pcm_s16le TEMP.wav`
   - `-map 0:a:0` picks the first audio track on purpose. Camera files often carry 2–4 tracks (e.g. lav on track 1, camera mic on track 2), and mixing them blindly hurts accuracy. Add an `--audio-track N` option.
   - Run ffmpeg with an argument list, never a shell string, so paths with spaces, emoji or accents work.
   - Applies to audio files too. Even a .wav gets normalized, so the transcriber always sees one consistent format.
4. **Transcribe** the WAV locally with Whisper:
   - Mac with Apple Silicon: `mlx-whisper`, model `mlx-community/whisper-large-v3-turbo`.
   - NVIDIA GPU (Windows/Linux): `faster-whisper`, model `large-v3-turbo`, `compute_type="float16"`.
   - Any other machine: `faster-whisper` on CPU, `compute_type="int8"` — slower but works.
   - Turn on voice-activity filtering (`vad_filter=True` in faster-whisper) and `condition_on_previous_text=False`. Without these, Whisper tends to invent text over long silences or loop the same line.
   - Allow `small` / `medium` models for quick drafts.
5. **Write outputs**, then delete the temp WAV. Also clear leftover temp files from a crashed run at startup.

Optional later: **speaker labels** (who said what) via `pyannote` or WhisperX. This needs a free Hugging Face token and adds setup, so it stays out of v1.

## Requirements

**Inputs**

- A folder or a single file (drag-and-drop or typed). Streams files of 3+ GB each and never loads them into memory.
- Language: auto-detect by default, which only listens to the first 30 seconds. Also offer `--lang en` / `--lang es` per run, since a Spanish intro can mislabel an English video.

**Outputs (per file)**

Outputs keep the full source name, extension included (`interview.mov` → `interview.mov.txt`), so `interview.mov` and `interview.mp4` in one folder don't overwrite each other.

| File | What it's for |
| --- | --- |
| `name.ext.txt` | Clean readable transcript, paragraphs, no timestamps |
| `name.ext.timestamped.txt` | Each line prefixed `[HH:MM:SS]` — for finding moments in the edit |
| `name.ext.srt` | Subtitles for Premiere / DaVinci / CapCut — lines ≤ 42 characters, ≤ 2 lines, ≤ \~7 seconds each |
| `name.ext.vtt` | Subtitles for web players |
| `name.ext.json` | Full segment data (start, end, text, model, language) for later tools |

**Behavior**

- Batch: process all files in one run, with a progress bar per file and overall, plus a time-remaining estimate.
- Resume: write each output to a temp name and rename it when done. Write the .json last, as the "finished" marker. A file counts as done only if its .json exists, so a half-written transcript never gets skipped. `--force` redoes everything.
- Logging: a `log.txt` with file name, duration, model, language detected, time taken, and any errors.
- One bad file never stops the batch — log it and move on. Print a summary at the end: done / skipped / failed.
- Keep the computer awake during long runs (`caffeinate` on Mac).
- Check free disk space before starting: at least 2× the largest temp WAV plus room for outputs.
- Custom vocabulary: an optional `glossary.txt` of names/terms (e.g. Lightning OS, Smooth Scaling). Pass it as `hotwords` in faster-whisper, or as `initial_prompt` in mlx-whisper. Keep it short — Whisper only reads \~200 tokens of prompt, and a long one can cause repeated or invented lines.

**Interface**

- v1: command line — `python transcribe.py PATH --model large-v3-turbo --lang auto`.
- v2: a simple local web page or desktop window: pick folder, pick options, click Start, watch progress.

## Build phases

Each rendition is small enough to test on one short clip before running all 18 GB.

1. **Rendition 1 — proof of concept:** one script, one file in, one `.txt` out. Test on a 1–2 minute clip cut from one of the real .mov files.
2. **Rendition 2 — batch + all formats:** folder input, ffprobe check, every input format, all five outputs, temp-file cleanup, log. Test against a `samples/` folder with one short clip per format (.mov .mp4 .mkv .webm .wmv .mp3 .wav .flac .aac), plus one silent clip and one video with no audio track.
3. **Rendition 3 — reliability:** resume/skip, per-file error handling, progress bars, disk-space check, glossary support, setup script that installs ffmpeg + Python packages.
4. **Move to Claude Code:** hand over this doc + the R3 script; set up a proper project (README, `requirements.txt`, config file, the `samples/` test folder).
5. **Rendition 4 — interface + extras:** simple GUI, optional speaker labels, a reels caption-length preset (from Vibe), a watch folder that auto-transcribes new files (from Buzz), optional summary/chapter markers per file.

## Done when

- [ ] All 6 .mov files transcribed in one unattended run, offline after setup
- [ ] One sample of each format (.mov .mp4 .mkv .webm .wmv .mp3 .wav .flac .aac) transcribes without errors
- [ ] A file with no audio, or a corrupt file, is logged and skipped — the batch keeps going
- [ ] Extra disk use during the run stays under \~2 GB (temp audio deleted as it goes)
- [ ] The .srt imports cleanly into my editor, with captions within \~0.5 s of the speech
- [ ] Glossary names are spelled right in most places (Whisper can't guarantee 100%)
- [ ] Killing the run mid-way and restarting picks up where it left off, with no half-finished files left behind
- [ ] A non-coder can install and run it from the README in under 15 minutes

## Open questions

Answer these before Rendition 1 — they change which install path the tool uses.

- [ ] Computer: Mac (which chip — M1/M2/M3/M4 or Intel) or Windows? Does it have an NVIDIA GPU?
- [ ] Roughly how long is each video in runtime? Processing speed varies a lot by machine (approximate: a few minutes to \~20 minutes per hour of audio), so R1 will time a real clip instead of guessing.
- [ ] Language(s) spoken: English only, or English + Spanish mixed? Whisper handles one language per file well and mid-sentence switching poorly.
- [ ] Do the camera files have more than one audio track (e.g. separate lav and camera mic)? Which one should be transcribed?
- [ ] Do I need speaker labels (interviews, multiple people) or is one continuous transcript fine?
- [ ] Which editor will the .srt go into (Premiere, DaVinci, CapCut, Final Cut)?
- [ ] Are the files on the internal drive or an external drive? Is Python installed? Is Homebrew (Mac) installed?

## Prompt for Claude Code

Paste this as the first message in Claude Code, with this doc saved as `SPEC.md` in the project folder (export it as Markdown).

```markdown
Read SPEC.md in this folder. It describes a free, local batch transcription tool for video and audio files: .mov .mp4 .mkv .webm .wmv .mp3 .wav .flac .aac (.m4a too). The first job is 6 .mov files, 18 GB total.

Reference projects (both MIT-licensed, see the Reference projects section of SPEC.md):
- https://github.com/chidiwilliams/buzz — Python, same stack as this tool. Read how it chooses a Whisper backend per machine and how its CLI and watch folder work.
- https://github.com/thewh1teagle/vibe — Rust/Tauri. Use for ideas only (caption-length presets, stable timestamps), not code.
Borrow patterns, keep our own simpler structure, and credit either project in the README if you adapt its code.

My setup: [Mac M_ / Windows + GPU], Python [installed / not installed], files on [internal / external drive].

Current state: I have a working Rendition [X] script (transcribe.py). Please:
1. Review it against SPEC.md and list gaps.
2. Set up the project: README, requirements.txt, setup script that installs ffmpeg and the right Whisper backend for my machine.
3. Build the next rendition from the Build phases section.
4. Test on the samples/ folder (one short clip per format) before touching the full files.

Rules: never load whole media files into memory; never upload anything; run ffmpeg with argument lists, not shell strings; probe every file before extracting; delete temp audio after each file; one failed file must not stop the batch. Explain each step in plain language — I'm not a developer.
```
