"""Blu-ray PGS subtitles (.sup): parse display sets into timed RGBA pictures.

A .sup file is a list of segments ("PG", PTS, DTS, type, size): palettes (PDS), run-length
coded objects (ODS, may span several segments), windows (WDS) and a composition (PCS) that
places objects on screen; END closes a display set. A composition with objects shows them
until the next composition; one without objects clears the screen. The forced flag of a
composition object marks captions shown even with subtitles off (foreign dialogue).
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from dvd import toolchain
from dvd.subs.srt import SubtitleError

PDS, ODS, PCS, WDS, END = 0x14, 0x15, 0x16, 0x17, 0x80


@dataclass(frozen=True)
class BitmapCue:
    start: float
    end: float
    rgba: np.ndarray  # (h, w, 4) uint8
    x: int  # position on the source video frame
    y: int
    frame_width: int  # size of the source video frame the positions refer to
    frame_height: int
    forced: bool = False


def _u16(b: bytes, at: int) -> int:
    return int.from_bytes(b[at : at + 2], "big")


def _rgb(y: int, cr: int, cb: int) -> tuple[int, int, int]:
    """BT.709 limited-range YCbCr (Blu-ray) to RGB."""
    yy, pb, pr = (y - 16) * 255 / 219, (cb - 128) * 255 / 224, (cr - 128) * 255 / 224
    r = yy + 1.5748 * pr
    g = yy - 0.1873 * pb - 0.4681 * pr
    b = yy + 1.8556 * pb
    return tuple(int(min(255, max(0, round(v)))) for v in (r, g, b))  # type: ignore[return-value]


def decode_rle(data: bytes, width: int, height: int) -> np.ndarray:
    """PGS run-length data to palette indices (height, width)."""
    out = np.zeros((height, width), np.uint8)
    x = y = i = 0
    n = len(data)
    while i < n and y < height:
        b = data[i]
        i += 1
        if b:
            if x < width:
                out[y, x] = b
            x += 1
            continue
        b2 = data[i] if i < n else 0
        i += 1
        if b2 == 0:  # end of line
            x, y = 0, y + 1
            continue
        count = b2 & 0x3F
        if b2 & 0x40:
            count = (count << 8) | data[i]
            i += 1
        color = 0
        if b2 & 0x80:
            color = data[i]
            i += 1
        out[y, x : x + count] = color
        x += count
    return out


def parse_sup(data: bytes) -> list[BitmapCue]:
    palette = np.zeros((256, 4), np.uint8)  # RGBA; index 0xFF and unset entries transparent
    objects: dict[int, tuple[int, int, bytearray]] = {}  # id -> (width, height, rle data)
    cues: list[BitmapCue] = []
    shown: dict | None = None  # the composition on screen: start, frame size, placements
    pos = 0

    def close(at: float) -> None:
        nonlocal shown
        if shown is not None and shown["pictures"] and at > shown["start"]:
            for rgba, x, y, forced in shown["pictures"]:
                cues.append(BitmapCue(shown["start"], at, rgba, x, y, shown["w"], shown["h"],
                                      forced))  # fmt: skip
        shown = None

    pending: dict | None = None
    while pos + 13 <= len(data):
        if data[pos : pos + 2] != b"PG":
            raise SubtitleError(f"not a PGS stream (bad segment header at byte {pos})")
        pts = int.from_bytes(data[pos + 2 : pos + 6], "big") / 90000
        kind, size = data[pos + 10], int.from_bytes(data[pos + 11 : pos + 13], "big")
        body = data[pos + 13 : pos + 13 + size]
        pos += 13 + size
        if kind == PCS:
            w, h = _u16(body, 0), _u16(body, 2)
            count, placements, p = body[10], [], 11
            for _ in range(count):
                oid, flags = _u16(body, p), body[p + 3]
                x, y, crop = _u16(body, p + 4), _u16(body, p + 6), None
                p += 8
                if flags & 0x80:  # cropped: only part of the object is shown
                    crop = tuple(_u16(body, p + k) for k in (0, 2, 4, 6))
                    p += 8
                placements.append((oid, x, y, bool(flags & 0x40), crop))
            pending = {"start": pts, "w": w, "h": h, "placements": placements}
        elif kind == PDS:
            for p in range(2, len(body) - 4, 5):
                idx, y, cr, cb, a = body[p : p + 5]
                palette[idx] = (*_rgb(y, cr, cb), a)
        elif kind == ODS:
            oid, flags = _u16(body, 0), body[3]
            if flags & 0x80:  # first fragment: length, width, height, data
                w, h = _u16(body, 7), _u16(body, 9)
                objects[oid] = (w, h, bytearray(body[11:]))
            elif oid in objects:
                objects[oid][2].extend(body[4:])
        elif kind == END and pending is not None:
            close(pending["start"])
            pictures = []
            for oid, x, y, forced, crop in pending["placements"]:
                if oid not in objects:
                    continue
                w, h, rle = objects[oid]
                rgba = palette[decode_rle(bytes(rle), w, h)]
                if crop is not None:
                    cx, cy, cw, ch = crop
                    rgba = rgba[cy : cy + ch, cx : cx + cw]
                pictures.append((np.ascontiguousarray(rgba), x, y, forced))
            shown = {**pending, "pictures": pictures}
            pending = None
    if shown is not None and shown["pictures"]:
        close(shown["start"] + 5.0)  # a last caption without a clear: show it for 5 s
    return cues


def extract_pgs(source: Path, stream_index: int, out: Path) -> list[BitmapCue]:
    ffmpeg = toolchain.find_executable(["ffmpeg.exe", "ffmpeg"], toolchain.tool_dirs())
    if ffmpeg is None:
        raise SubtitleError("ffmpeg not found")
    proc = subprocess.run(
        [str(ffmpeg), "-v", "error", "-y", "-i", str(source), "-map", f"0:{stream_index}",
         "-c:s", "copy", "-f", "sup", str(out)],
        capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )  # fmt: skip
    if proc.returncode != 0:
        message = proc.stderr.decode("utf-8", errors="replace").strip()
        raise SubtitleError(f"cannot extract PGS stream {stream_index}: {message}")
    return parse_sup(out.read_bytes())
