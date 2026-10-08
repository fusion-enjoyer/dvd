"""SRT reading with Turkish-aware encoding detection."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


class SubtitleError(Exception):
    pass


@dataclass(frozen=True)
class Cue:
    start: float  # seconds
    end: float
    lines: tuple[str, ...]
    italic: bool = False


_TIME = r"(\d+):(\d{1,2}):(\d{1,2})[,.](\d{1,3})"
_TIMING = re.compile(rf"^\s*{_TIME}\s*-->\s*{_TIME}")
_TAG = re.compile(r"</?\s*[ibus]\s*>|</?font[^>]*>|\{\\[^}]*\}", re.IGNORECASE)


def decode(data: bytes) -> str:
    """UTF-8/UTF-16 by BOM or validity; otherwise Windows-1254.

    Windows-1254 and ISO-8859-9 agree on all Turkish letters (ğ ş ı İ Ğ Ş); 1254 only adds
    typographic quotes and dashes in 0x80-0x9F, so it reads both correctly.
    """
    if data.startswith(b"\xef\xbb\xbf"):
        return data[3:].decode("utf-8")
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("cp1254", errors="replace")


def _seconds(h: str, m: str, s: str, ms: str) -> float:
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms.ljust(3, "0")) / 1000


def parse(text: str) -> list[Cue]:
    cues = []
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n").replace("\r", "\n").strip()):
        lines = block.split("\n")
        timing_at = next((i for i, line in enumerate(lines[:2]) if _TIMING.match(line)), None)
        if timing_at is None:
            continue
        m = _TIMING.match(lines[timing_at])
        start, end = _seconds(*m.groups()[:4]), _seconds(*m.groups()[4:])
        raw = [line.strip() for line in lines[timing_at + 1 :] if line.strip()]
        if not raw or end <= start:
            continue
        joined = "\n".join(raw)
        italic = bool(re.fullmatch(r"\s*<i>.*</i>\s*", joined, re.IGNORECASE | re.DOTALL))
        clean = tuple(line for line in (_TAG.sub("", r).strip() for r in raw) if line)
        if clean:
            cues.append(Cue(start, end, clean, italic))
    return sorted(cues, key=lambda c: c.start)


def read_srt(path: Path) -> list[Cue]:
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise SubtitleError(f"cannot read {path}: {exc}") from None
    cues = parse(decode(data))
    if not cues:
        raise SubtitleError(f"{path.name} contains no subtitles")
    return cues


def retime(cues: list[Cue], speedup: float) -> list[Cue]:
    """PAL speedup shortens the film; subtitle times shrink by the same factor."""
    if speedup == 1:
        return cues
    return [Cue(c.start / speedup, c.end / speedup, c.lines, c.italic) for c in cues]
