"""Turning raw Whisper output into clean text and well-timed captions.

- Glossary: names/terms to steer Whisper, plus "wrong -> right" spelling fixes.
- Cleanup: drop the phantom lines Whisper sometimes invents over silence, and
  collapse a line repeated over and over (a "loop").
- Captions: built word by word from word-level timestamps, so each caption
  starts when its first word is spoken (idea from Vibe's stable-timestamps mode).
- Paragraphs: for the readable .txt / .docx.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Optional

from .backends import Segment, Word

# ---------------------------------------------------------------- glossary

PROMPT_MAX_CHARS = 600  # roughly 150 tokens; Whisper only reads ~200 tokens of prompt


@dataclass
class Glossary:
    terms: list[str]
    fixes: list[tuple[re.Pattern, str]]
    truncated: bool = False

    @property
    def prompt(self) -> Optional[str]:
        if not self.terms:
            return None
        text = ", ".join(self.terms)
        if len(text) > PROMPT_MAX_CHARS:
            text = text[:PROMPT_MAX_CHARS].rsplit(",", 1)[0]
            self.truncated = True
        return text + "."

    def apply(self, text: str) -> str:
        for pattern, right in self.fixes:
            text = pattern.sub(right, text)
        return text


def _term_pattern(term: str) -> re.Pattern:
    words = [re.escape(w) for w in term.split()]
    # "Lightning OS" also matches "lightning os", "Lightning-OS", "Lightning  OS"
    body = r"[\s\-]+".join(words)
    return re.compile(rf"(?<![\w]){body}(?![\w])", re.IGNORECASE)


def load_glossary(path: Optional[Path]) -> Glossary:
    """Read glossary.txt. One term per line; '# ...' is a comment;
    'wrong spelling -> Right Spelling' adds a find-and-replace fix."""
    if not path or not Path(path).is_file():
        return Glossary([], [])
    terms: list[str] = []
    fixes: list[tuple[re.Pattern, str]] = []
    for raw in Path(path).read_text(encoding="utf-8-sig").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if "->" in line:
            wrong, right = (part.strip() for part in line.split("->", 1))
            if wrong and right:
                fixes.append((_term_pattern(wrong), right))
                if right not in terms:
                    terms.append(right)
            continue
        if line not in terms:
            terms.append(line)
    # Exact terms also fix capitalisation: "smooth scaling" -> "Smooth Scaling".
    for term in terms:
        fixes.append((_term_pattern(term), term))
    return Glossary(terms, fixes)


# ---------------------------------------------------------------- cleanup

# Phrases Whisper is known to "hear" in silence (learned from YouTube subtitles).
PHANTOM_PHRASES = re.compile(
    r"thanks? (you )?for watching|subtitles? by|amara\.org|please subscribe|"
    r"like and subscribe|transcribed by|captions? by",
    re.IGNORECASE,
)


def _norm(text: str) -> str:
    return re.sub(r"[^\w]+", " ", text.lower()).strip()


def clean_segments(segments: list[Segment], glossary_prompt: Optional[str] = None) -> list[Segment]:
    cleaned: list[Segment] = []
    prompt_norm = _norm(glossary_prompt or "")
    repeat_count = 0
    for seg in segments:
        text = seg.text.strip()
        if not text:
            continue
        norm = _norm(text)
        if not norm:  # only punctuation, e.g. "..."
            continue
        # Whisper's own "this was silence" signal: quiet AND unsure of itself.
        if seg.no_speech_prob > 0.6 and seg.avg_logprob < -1.0:
            continue
        # Known phantom phrases, when Whisper isn't confident they were spoken.
        if PHANTOM_PHRASES.search(text) and (seg.no_speech_prob > 0.2 or seg.avg_logprob < -0.7):
            continue
        # The glossary list read back as if spoken ("Evan, Smooth Scaling, ...").
        # A single term said on its own ("Lightning OS.") is kept.
        if prompt_norm and "," in text and norm in prompt_norm and len(norm) >= len(prompt_norm) / 2:
            continue
        # The same line again and again: keep the first two, drop the rest.
        if cleaned and _norm(cleaned[-1].text) == norm:
            repeat_count += 1
            if repeat_count >= 2:
                continue
        else:
            repeat_count = 0
        words = _clean_words(seg.words)
        start = words[0].start if words else seg.start
        end = max(words[-1].end if words else seg.end, start + 0.05)
        cleaned.append(replace(seg, text=text, words=words, start=start, end=end))
    return cleaned


MAX_WORD_SECONDS = 1.6


def _clean_words(words: list[Word]) -> list[Word]:
    """Tidy word timings: no empty words, nothing running backwards, and no
    single word stretched across a long pause (that makes captions linger)."""
    out: list[Word] = []
    for w in words:
        text = w.text.strip()
        if not text:
            continue
        start = max(w.start, out[-1].start if out else 0.0)
        end = max(w.end, start + 0.02)
        if end - start > MAX_WORD_SECONDS:
            end = start + MAX_WORD_SECONDS
        out.append(Word(start, end, text, w.probability))
    return out


def words_of(seg: Segment) -> list[Word]:
    """Word timings for a segment, estimated from its length if Whisper gave none."""
    if seg.words:
        return seg.words
    tokens = seg.text.split()
    if not tokens:
        return []
    total_chars = sum(len(t) + 1 for t in tokens)
    span = max(seg.end - seg.start, 0.05)
    words, t = [], seg.start
    for token in tokens:
        length = span * (len(token) + 1) / total_chars
        words.append(Word(t, t + length, token))
        t += length
    return words


# ---------------------------------------------------------------- captions

@dataclass(frozen=True)
class CaptionStyle:
    max_chars: int        # per line
    max_lines: int
    max_seconds: float    # longest a single caption stays up
    min_seconds: float    # shortest (stretched into the following gap when possible)
    pause_split: float    # a silence this long always starts a new caption


CAPTION_PRESETS = {
    # Broadcast-style: Premiere, DaVinci, CapCut, web players.
    "standard": CaptionStyle(max_chars=42, max_lines=2, max_seconds=7.0, min_seconds=1.0, pause_split=0.8),
    # Short punchy captions for vertical reels/shorts (idea from Vibe).
    "reels": CaptionStyle(max_chars=18, max_lines=1, max_seconds=2.5, min_seconds=0.5, pause_split=0.4),
}


@dataclass
class Cue:
    start: float
    end: float
    lines: list[str]


SENTENCE_END = re.compile(r"[.!?…][\"')\]]*$")
CLAUSE_END = re.compile(r"[,;:—–][\"')\]]*$")


def wrap(text: str, style: CaptionStyle) -> Optional[list[str]]:
    """Split text into balanced lines that fit the style, or None if it can't fit."""
    if len(text) <= style.max_chars:
        return [text]
    if style.max_lines < 2:
        return None
    words = text.split(" ")
    best: Optional[list[str]] = None
    best_score = None
    for i in range(1, len(words)):
        top, bottom = " ".join(words[:i]), " ".join(words[i:])
        if len(top) > style.max_chars or len(bottom) > style.max_chars:
            continue
        score = abs(len(top) - len(bottom))
        if CLAUSE_END.search(top) or SENTENCE_END.search(top):
            score -= 6  # prefer breaking the line after punctuation
        if best_score is None or score < best_score:
            best, best_score = [top, bottom], score
    return best


def _force_wrap(text: str, style: CaptionStyle) -> list[str]:
    """Last resort for text that can't fit (e.g. a very long URL): greedy fill."""
    lines: list[str] = []
    for word in text.split(" "):
        if lines and len(lines[-1]) + 1 + len(word) <= style.max_chars:
            lines[-1] += " " + word
        elif len(lines) < style.max_lines:
            lines.append(word)
        else:
            lines[-1] += " " + word
    return lines


def build_cues(segments: list[Segment], style: CaptionStyle, glossary: Optional[Glossary] = None) -> list[Cue]:
    words: list[tuple[Word, bool]] = []  # (word, is_last_word_of_segment)
    for seg in segments:
        seg_words = [replace(w, text=w.text.strip()) for w in words_of(seg) if w.text.strip()]
        for i, w in enumerate(seg_words):
            words.append((w, i == len(seg_words) - 1))

    capacity = style.max_chars * style.max_lines
    groups: list[list[Word]] = []
    current: list[Word] = []

    def text_of(ws: list[Word]) -> str:
        return " ".join(w.text for w in ws)

    for word, ends_segment in words:
        if current:
            too_long = (word.end - current[0].start) > style.max_seconds
            paused = (word.start - current[-1].end) >= style.pause_split
            no_room = wrap(text_of(current + [word]), style) is None
            if too_long or paused or no_room:
                groups.append(current)
                current = []
        current.append(word)
        filled = len(text_of(current)) / capacity
        if (SENTENCE_END.search(word.text) or ends_segment) and filled >= 0.3:
            groups.append(current)
            current = []
        elif CLAUSE_END.search(word.text) and filled >= 0.65:
            groups.append(current)
            current = []
    if current:
        groups.append(current)

    cues: list[Cue] = []
    for group in groups:
        text = text_of(group)
        if glossary:
            text = glossary.apply(text)
        lines = wrap(text, style) or _force_wrap(text, style)
        cues.append(Cue(group[0].start, group[-1].end, lines))
    return _fix_timing(cues, style)


def _fix_timing(cues: list[Cue], style: CaptionStyle) -> list[Cue]:
    """No overlaps, nothing too short to read, no flicker between close captions."""
    for i in range(1, len(cues)):  # every caption starts after the previous one
        cues[i].start = max(cues[i].start, cues[i - 1].start + 0.1)
    for i, cue in enumerate(cues):
        next_start = cues[i + 1].start if i + 1 < len(cues) else None
        end = max(cue.end, cue.start + style.min_seconds)
        end = min(end, cue.start + style.max_seconds)
        if next_start is not None:
            if next_start - end < 0.25:  # tiny gap: hold until the next one
                end = next_start
            end = min(end, next_start)
        cue.end = end
    return cues


# ---------------------------------------------------------------- paragraphs

def paragraphs(segments: list[Segment], glossary: Optional[Glossary] = None) -> list[tuple[float, str]]:
    """Group segments into readable paragraphs: a new one after a pause of 2+
    seconds (often a new speaker or topic), or when one grows past ~700 chars."""
    result: list[tuple[float, str]] = []
    current: list[str] = []
    start = 0.0
    last_end = None
    for seg in segments:
        gap = seg.start - last_end if last_end is not None else 0.0
        size = sum(len(t) for t in current)
        if current and (gap >= 2.0 or (size > 700 and SENTENCE_END.search(current[-1]))):
            result.append((start, " ".join(current)))
            current = []
        if not current:
            start = seg.start
        current.append(seg.text.strip())
        last_end = seg.end
    if current:
        result.append((start, " ".join(current)))
    if glossary:
        result = [(t, glossary.apply(p)) for t, p in result]
    return result
