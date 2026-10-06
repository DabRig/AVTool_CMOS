# AVTool CMOS — free, offline transcripts & subtitles

Turn video and audio files into accurate, timestamped transcripts and subtitles,
**on your own computer**. No uploads, no credits, no file-size limits.

- **Reads:** `.mov .mp4 .mkv .webm .wmv` video and `.mp3 .wav .flac .aac .m4a` audio
  (upper-case `.MOV` from cameras/iPhones too).
- **Writes, for each file:** a clean transcript, a timestamped transcript, subtitles
  for Premiere / CapCut / DaVinci (`.srt`), web subtitles (`.vtt`), a Word document
  (`.docx`) and a data file (`.json`).
- **Handles big files:** a 3 GB video uses about 50 MB of memory. The tool only
  pulls out the audio (≈115 MB per hour) and deletes it after each file.

---

## The AVTool app (V1.2)

**AVTool.app** is a window you double-click, styled like an audio plugin floating in
space: your logo, a slowly drifting starfield, and glass panels. It does everything
the Terminal commands below do, without typing. (If your Mac has *Reduce motion*
switched on in Accessibility settings, the stars hold still.)

- **Open it:** double-click **AVTool.app** in the AVTool folder. Drag it to your
  Dock to keep it handy. The first time, macOS may ask to let AVTool use files on
  your external drive. Click **Allow**.
- **Queue rack (left):** drag videos or whole folders from Finder onto the window,
  or use **＋ FILES / ＋ FOLDER**. Each row shows its length, a progress bar and
  its status: READY, TRANSCRIBE 42%, DONE, NO AUDIO, FAILED. Hover over a
  status to see why. The row buttons view the transcript, show the file in
  Finder, or remove it from the queue.
- **START / STOP (bottom):** the meter, the stage lights (EXTRACT › TRANSCRIBE ›
  WRITE), the percentage and the time left update live. STOP finishes cleanly:
  no temp files, no half-written transcripts. START picks up where it stopped.
- **SETTINGS tab:**
  - The **QUALITY knob** (Draft / Balanced / Best): click it, drag it up or down,
    or click a label.
  - **Language** and **caption style** (Standard for Premiere/CapCut, Reels for
    vertical video).
  - Switches: **Boost quiet voices**, **Include subfolders**, **Redo finished
    files**, **Keep Mac awake**.
  - Where transcripts are saved, and which files to make.
  - Settings lock while a batch runs.
- **GLOSSARY tab:** edit the names list (Evan, Smooth Scaling, Lightning OS…) and
  click **SAVE GLOSSARY**.
- **VIEWER tab:** read any finished transcript with timestamps. You can search
  it, click a line to copy it, or open the TXT / SRT / DOCX.
- **LOG tab:** the same running commentary the Terminal version prints.
- **? HELP (top right):** the built-in manual: every control explained, guides
  for Premiere, CapCut, DaVinci, Final Cut and Word, tips, an FAQ, troubleshooting
  and keyboard shortcuts, all searchable. A one-minute **guided tour** runs the first
  time you open the app, and you can replay it from the Help Center.
- **Shortcuts:** ⌘O add files · ⌘⇧O add a folder · ⌘↩ START · ⌘. STOP · ? help.

**Updating later:** open Terminal and run
`cd ~/Documents/AVTool && bash update.command`. It downloads the newest version
and keeps your glossary, settings and transcripts.

---

## Step 1 — Install (one time, about 15 minutes)

You need internet for this step only.

1. **Get the folder onto your Mac.** On the GitHub page for this project, click the
   green **Code** button › **Download ZIP**. Double-click the ZIP in Downloads,
   then move the unzipped folder into **Documents**.
2. **Open Terminal.** Press ⌘ Space, type `Terminal`, press Enter.
3. **Point Terminal at the folder.** Type `cd ` (with a space after it), drag the
   project folder from Finder into the Terminal window, then press Enter.
4. **Run the setup.** Type this and press Enter:

   ```
   bash setup_mac.command
   ```

   It installs, in order: Homebrew (the Mac's installer for tools like this),
   **ffmpeg** (reads video files), **Python 3.12**, the **MLX Whisper** engine
   (runs on your M2 Pro's GPU), the **Whisper large-v3-turbo** model (≈1.6 GB), and
   builds **AVTool.app**.
   If it asks for your Mac password, type it and press Enter. Nothing appears
   while you type, and that's normal.

When it finishes you'll see a checklist of ✓ marks. If one shows ✗, the line
under it says how to fix it.

## Step 2 — Test on the sample clips (2 minutes)

Setup made a `samples/clips` folder with one short clip of every format. The
clips use the Mac's built-in voice. It also includes some deliberately broken
files. In the same Terminal window:

```
./Transcribe.command samples/clips
```

You should see **done 14 · skipped 1 · failed 1**:

| Clip | What should happen |
| --- | --- |
| `sample.mov/.mp4/.mkv/.webm/.wmv/.mp3/.wav/.flac/.aac/.m4a`, `CAMERA_CLIP.MOV` | Transcribed: "Hi everyone, I'm Evan. Welcome to the Smooth Scaling workshop…" |
| `Évan’s talk 🎤 (take 2).mp4` | Transcribed (proves odd file names are fine) |
| `two_tracks.mov` | Transcribes track 1, a tone, so expect little or no text. Re-run with `--audio-track 2 --force` to get the speech. |
| `silent.mp4` | Done, and the transcript says "(No speech detected.)" |
| `no_audio.mp4` | **Skipped**: no audio track |
| `corrupt.mov` | **Failed**: damaged file. The batch carries on anyway. |
| `._sample.mov`, `.hidden.mov` | Ignored completely (macOS junk files) |

Open `samples/clips/sample.mov.txt` to see the transcript.

## Step 3 — Test one real video before the big job

> **Golden rule:** never drag a file at Terminal's normal `%` prompt. That tries to
> *run* the video and gives `exec format error`. Type the command first, press
> Enter, and drag only when the tool shows its own `>` prompt.

1. Type `bash Transcribe.command` and press Enter.
2. At the `>` prompt, drag **one** video from Finder into the window and press Enter.
3. When it finishes, open the `.txt` next to the video, and import the `.srt` into
   Premiere to check the captions line up. This video won't be redone in the big
   run, because finished files are skipped.

## Step 4 — The real job

1. Plug in the LaCie drive **and the MacBook's charger**. Keep the lid open. The
   tool stops the Mac going to sleep, but closing the lid on battery still
   puts it to sleep.
2. Double-click **Transcribe.command** in the project folder. (The first time, if
   macOS blocks it, right-click › **Open** › **Open**.)
3. When it asks, drag the folder with your videos into the window and press Enter.

You'll see each file listed with its length. Then, for each file, a progress bar for
pulling out the audio, a progress bar for transcribing, and the overall batch
progress with an estimate of the time left. The transcripts are saved **next to
each video** on the LaCie drive.

**Stopping and resuming:** press **Ctrl+C** at any time (or close the window).
Run it again the same way and it picks up where it left off. Finished files are
skipped and a half-done file is redone from the start. Nothing half-written is
ever left behind.

## What you get

For `IMG_0042.MOV` you get these files (the full name is kept, so `talk.mov` and
`talk.mp4` never overwrite each other):

| File | Use it for |
| --- | --- |
| `IMG_0042.MOV.txt` | Reading: clean paragraphs, no timestamps |
| `IMG_0042.MOV.timestamped.txt` | Finding moments: every line starts with `[HH:MM:SS]` |
| `IMG_0042.MOV.srt` | **Subtitles for Premiere / CapCut / DaVinci**: ≤42 characters per line, ≤2 lines, ≤7 seconds each |
| `IMG_0042.MOV.vtt` | Subtitles for web video players |
| `IMG_0042.MOV.docx` | Word document with a timestamp per paragraph. To get a PDF, open it in Word or Pages and use File › Export to PDF. |
| `IMG_0042.MOV.json` | Full data with word-level timings. This file also marks a video as "finished". |
| `log.txt` | One line per file: length, model, language, time taken, any errors |

### Into Premiere Pro
**File › Import** the `.srt`, then drag it onto the timeline above the clip. It
becomes a captions track you can restyle. The captions start at 00:00:00, so line
the start of the captions up with the start of the clip.

### Into CapCut (desktop)
Drag the `.srt` onto the timeline, or use **Captions › Import captions** (the exact
menu name varies by CapCut version). For vertical reels, use shorter captions:

```
./Transcribe.command "DRAG-FOLDER-HERE" --captions reels --formats srt --out ~/Desktop/reels-captions
```

`--out` keeps the reels captions in a separate folder, so they don't replace
your normal ones. (Running it on the same folder again would skip the finished
files.)

## Options

Add these after the folder name, e.g. `./Transcribe.command "/Volumes/LaCie/Shoot" --boost-quiet`.
Defaults live in `config.toml`, which you can edit in TextEdit.

| Option | What it does |
| --- | --- |
| `--lang en` | Language. Already set to English in `config.toml`. Use `auto` to detect. |
| `--model small` | Faster, rougher draft. `large-v3-turbo` (default) is the best. |
| `--boost-quiet` | Evens out loud and quiet voices. **Try this if audience questions are missing.** |
| `--audio-track 2` | Use a different audio track (see `--list-tracks`). |
| `--list-tracks` | Shows every file's audio tracks, then stops. |
| `--out ~/Documents/Transcripts` | Put transcripts somewhere else instead of next to the videos. |
| `--recursive` | Also look inside subfolders. |
| `--force` | Redo files that are already done (e.g. after changing the glossary). |
| `--captions reels` | Short one-line captions for vertical video. |
| `--formats srt,txt` | Only make some outputs (the `.json` is always made). |
| `--dry-run` | Show what would happen, without transcribing. |
| `--check` | Check the installation. |

## Getting names right: `glossary.txt`

`glossary.txt` lists names and terms Whisper should spell correctly. It already
contains Evan, Smooth Scaling and Lightning OS. Add one per line and keep the
list short (a few dozen at most). If Whisper keeps mishearing something, add a fix:

```
Lightening OS -> Lightning OS
```

Fixes and capitalisation are applied to every output. Whisper can't guarantee
100% accuracy, but most mentions will come out right. After editing the glossary,
re-run with `--force`.

## Tips for your recordings

- **One wireless mic on Evan, through the iPhone:** Evan will transcribe very
  well. Audience questions are farther from the mic and quieter, so Whisper may
  miss some. If so, re-run those files with `--boost-quiet --force`.
- **Who said what:** the transcript doesn't label speakers yet. A new paragraph
  starts after a pause of 2+ seconds, which usually marks a question or an
  answer. Speaker labels are planned (see `STATUS.md`).
- **The LaCie drive:** if the tool says it **can't write to the drive**, the drive
  is probably formatted for Windows (NTFS), which a Mac can only read. Use
  `--out ~/Documents/Transcripts` and the transcripts go there instead.
- **Speed:** the first file shows the real speed (e.g. "12× real time" means
  a 48-minute video takes about 4 minutes). On an M2 Pro, expect several times
  faster than real time.

## Privacy

Nothing is ever uploaded. The internet is used only during setup (to install
tools and download the model once). After that the tool switches the model
library to offline mode and turns off its usage statistics. You can unplug from
Wi-Fi and it still works.

## Troubleshooting

| Message | Fix |
| --- | --- |
| `Setup hasn't been run yet` | Run `bash setup_mac.command` (Step 1). |
| `ffmpeg isn't installed` | Re-run the setup, or `brew install ffmpeg`. |
| `Model … isn't downloaded yet` | Connect to the internet once: `.venv/bin/python transcribe.py --download-model` |
| `Can't write to …` | The drive is read-only to the Mac. Use `--out ~/Documents/Transcripts`. |
| `Not enough free disk space` | Free a few GB on the Mac's internal drive (the temporary audio goes there). |
| A file shows `failed` | The reason is in the summary and in `log.txt`. Other files are unaffected. |
| `audio track uses a codec this ffmpeg can't decode` | `brew upgrade ffmpeg`, then try again. |
| Text repeats or there are made-up lines over silence | Already filtered automatically. If you still see it, tell me which file and where. |
| macOS says Transcribe.command "can't be opened" | Right-click it › **Open** › **Open** (once). |

---

## For developers

```
transcribe.py          entry point (python transcribe.py --help)
avtool/gui/            the app: server.py (local API), app.py (window), make_app.py
                       (builds AVTool.app), static/ (HTML/CSS/JS, logo, fonts)
avtool/cli.py          options, config.toml, --check / --list-tracks / --download-model
avtool/batch.py        the batch loop: probe, disk check, keep-awake, resume, log, summary
avtool/media.py        scan, ffprobe, ffmpeg audio extraction (argument lists, streamed)
avtool/backends.py     engine choice + mlx-whisper / faster-whisper / test engine
avtool/text.py         glossary, phantom-line cleanup, caption building, paragraphs
avtool/writers.py      txt / timestamped / srt / vtt / docx / json, atomic writes
samples/make_samples.py  builds the test clips
tests/                 python -m pytest -q   (uses the stand-in "test" engine; no model needed)
```

Setup on other machines: `setup_windows.ps1` (Windows; NVIDIA GPU detected
automatically), or by hand: `pip install -r requirements-cpu.txt`
(or `-mac` / `-nvidia`) and install ffmpeg.

## Credits

- [OpenAI Whisper](https://github.com/openai/whisper) (MIT): the speech model.
- [mlx-whisper](https://github.com/ml-explore/mlx-examples) (MIT) and
  [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (MIT): the engines.
- [FFmpeg](https://ffmpeg.org): reads every media format.
- [Buzz](https://github.com/chidiwilliams/buzz) by Chidi Williams (MIT):
  inspired the per-machine engine choice (detect hardware, pick the fastest
  engine, allow an override) and the CLI design. No Buzz code was copied.
- [pywebview](https://github.com/r0x0r/pywebview) (BSD): the app's native window.
- [Inter](https://github.com/rsms/inter) typeface (SIL OFL 1.1), bundled for the
  app's lettering.
- The Sebastian Success logo (`avtool/gui/static/img/ss-logo.png`) is Sebastian's own
  mark, used for the app and its icon.
- [Vibe](https://github.com/thewh1teagle/vibe) by thewh1teagle (MIT): inspired
  the reels caption preset and building captions from word timings for steady
  timestamps. Ideas only; no code was copied.
