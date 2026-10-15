"""DVD subtitles (VobSub, `dvd_subtitle`): decode subpicture units into timed RGBA pictures.

They come from MKV (S_VOBSUB), .idx/.sub pairs and VOB/MPEG program streams. ffprobe hands
over the packets with their times, and the stream's extradata, which for MKV and .idx is the
.idx header with the 16-colour palette and the frame size. Each packet is one subpicture unit
(SPU): two interlaced fields of 2-bit run-length coded pixels, then control sequences that
start and stop the display, pick 4 of the 16 palette colours and their transparency, and give
the picture's area on the frame.

A program stream has no palette (it lives in the DVD's IFO files). Then the colours are told
apart by shape: of the opaque colours, the one least often next to transparent pixels is the
letters' fill, the others are their outline.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass

import numpy as np

from dvd import toolchain
from dvd.subs.pgs import BitmapCue
from dvd.subs.srt import SubtitleError

TICK = 1024 / 90000  # control sequence delays count in these units (seconds)
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


@dataclass(frozen=True)
class IdxHeader:
    palette: np.ndarray | None  # (16, 3) uint8 RGB
    size: tuple[int, int] | None  # frame the positions refer to


def parse_idx(text: str) -> IdxHeader:
    """Palette and frame size from an .idx header (also MKV's S_VOBSUB codec private)."""
    palette = size = None
    m = re.search(r"^\s*palette:\s*(.+)$", text, re.M | re.I)
    if m:
        colours = [c.strip() for c in m.group(1).split(",") if c.strip()]
        if len(colours) == 16 and all(re.fullmatch(r"[0-9a-fA-F]{6}", c) for c in colours):
            palette = np.array([[int(c[i : i + 2], 16) for i in (0, 2, 4)] for c in colours],
                               np.uint8)  # fmt: skip
    m = re.search(r"^\s*size:\s*(\d+)\s*x\s*(\d+)", text, re.M | re.I)
    if m:
        size = (int(m.group(1)), int(m.group(2)))
    return IdxHeader(palette, size)


def _field(data: bytes, start: int, width: int, rows: int) -> np.ndarray:
    """One field: `rows` lines of 2-bit colour slots. Codes are 1-4 nibbles long; a run of 0
    fills the rest of the line, and every line starts on a byte boundary."""
    out = np.zeros((rows, width), np.uint8)
    pos = start * 2  # in nibbles
    end = len(data) * 2

    def nibble() -> int:
        nonlocal pos
        if pos >= end:
            return 0
        b = data[pos >> 1]
        pos += 1
        return (b >> 4) if pos & 1 else (b & 0xF)

    for y in range(rows):
        x = 0
        while x < width and pos < end:
            v = nibble()
            for limit in (0x4, 0x10, 0x40):  # each longer code starts with more zero bits
                if v >= limit:
                    break
                v = (v << 4) | nibble()
            run, slot = v >> 2, v & 3
            if run == 0 or x + run > width:
                run = width - x
            out[y, x : x + run] = slot
            x += run
        pos += pos & 1  # byte align
    return out


@dataclass
class Spu:
    start: float  # seconds after the packet time
    end: float | None
    forced: bool
    slots: np.ndarray  # (h, w) colour slot 0-3
    colours: tuple[int, int, int, int]  # palette index for slot 0-3
    alpha: tuple[int, int, int, int]  # 0 (clear) - 15 (opaque) for slot 0-3
    x: int
    y: int


def parse_spu(data: bytes) -> Spu | None:
    """One subpicture unit; None when it shows nothing."""
    if len(data) < 4:
        return None
    size, at = int.from_bytes(data[0:2], "big"), int.from_bytes(data[2:4], "big")
    data = data[:size] if 4 <= size <= len(data) else data
    start = end = None
    forced = False
    colours, alpha = (0, 1, 2, 3), (0, 15, 15, 15)
    area = offsets = None
    seen = set()
    while at + 4 <= len(data) and at not in seen:
        seen.add(at)
        delay = int.from_bytes(data[at : at + 2], "big") * TICK
        following = int.from_bytes(data[at + 2 : at + 4], "big")
        p = at + 4
        while p < len(data):
            cmd = data[p]
            p += 1
            if cmd == 0x00:
                forced, start = True, delay if start is None else start
            elif cmd == 0x01:
                start = delay if start is None else start
            elif cmd == 0x02:
                end = delay
            elif cmd in (0x03, 0x04):
                b0, b1 = data[p], data[p + 1]
                values = (b1 & 0xF, b1 >> 4, b0 & 0xF, b0 >> 4)  # slots 0 (b), 1 (p), 2, 3
                colours, alpha = (values, alpha) if cmd == 0x03 else (colours, values)
                p += 2
            elif cmd == 0x05:
                b = data[p : p + 6]
                x1, x2 = (b[0] << 4) | (b[1] >> 4), ((b[1] & 0xF) << 8) | b[2]
                y1, y2 = (b[3] << 4) | (b[4] >> 4), ((b[4] & 0xF) << 8) | b[5]
                area = (x1, y1, x2 - x1 + 1, y2 - y1 + 1)
                p += 6
            elif cmd == 0x06:
                offsets = (int.from_bytes(data[p : p + 2], "big"),
                           int.from_bytes(data[p + 2 : p + 4], "big"))  # fmt: skip
                p += 4
            elif cmd == 0x07:  # colour/contrast changes inside the area: skipped
                p += int.from_bytes(data[p : p + 2], "big")
            else:  # 0xFF ends the sequence
                break
        if following == at:
            break
        at = following
    if start is None or area is None or offsets is None or area[2] <= 0 or area[3] <= 0:
        return None
    x, y, w, h = area
    slots = np.zeros((h, w), np.uint8)
    slots[0::2] = _field(data, offsets[0], w, (h + 1) // 2)
    slots[1::2] = _field(data, offsets[1], w, h // 2)
    return Spu(start, end, forced, slots, colours, alpha, x, y)


def _guess_rgb(spu: Spu) -> np.ndarray:
    """Slot colours without a palette: fill white, outline black (see the module notes)."""
    rgb = np.zeros((4, 3), np.uint8)
    opaque = [s for s in range(4) if spu.alpha[s] >= 8]
    clear = np.isin(spu.slots, [s for s in range(4) if s not in opaque])
    padded = np.pad(clear, 1, constant_values=True)
    near_clear = padded[:-2, 1:-1] | padded[2:, 1:-1] | padded[1:-1, :-2] | padded[1:-1, 2:]
    edge = {}
    for s in opaque:
        mask = spu.slots == s
        if mask.any():
            edge[s] = (mask & near_clear).sum() / mask.sum()
    if edge:
        rgb[min(edge, key=edge.get)] = 255
    return rgb


def rgba(spu: Spu, palette: np.ndarray | None) -> np.ndarray:
    rgb = palette[list(spu.colours)] if palette is not None else _guess_rgb(spu)
    table = np.zeros((4, 4), np.uint8)
    table[:, :3] = rgb
    table[:, 3] = [a * 17 for a in spu.alpha]
    return np.ascontiguousarray(table[spu.slots])


def cues_from_packets(
    packets: list[tuple[float, float | None, bytes]],
    header: IdxHeader,
    frame: tuple[int, int],
    origin: float = 0.0,
) -> list[BitmapCue]:
    """Packets (time, duration, data) to cues; times move back by `origin` (the video's
    start). A unit without a stop time lasts until the next one, or its packet duration, or
    5 seconds."""
    width, height = header.size or frame
    units = [(t, d, parse_spu(data)) for t, d, data in packets]
    units = [(t, d, u) for t, d, u in units if u is not None]
    cues = []
    for i, (t, duration, u) in enumerate(units):
        start = t + u.start - origin
        if u.end is not None and u.end > u.start:
            end = t + u.end - origin
        elif i + 1 < len(units):
            end = units[i + 1][0] - origin
        else:
            end = start + (duration or 5.0)
        picture = rgba(u, header.palette)
        if end <= start or not picture[:, :, 3].any():
            continue
        cues.append(BitmapCue(max(0.0, start), end, picture, u.x, u.y, width, height, u.forced))
    return cues


def _hexdump(text: str) -> bytes:
    """ffprobe's -show_data dump ("00000000: 041a 03fb ...  ascii") back to bytes."""
    out = bytearray()
    for line in text.splitlines():
        if len(line) > 10 and line[8:10] == ": ":
            out += bytes.fromhex(line[10:49].replace(" ", ""))
    return bytes(out)


def extract_vobsub(
    source, stream_index: int, frame: tuple[int, int], origin: float = 0.0
) -> list[BitmapCue]:
    """The cues of one dvd_subtitle stream (an .idx file is opened with its .sub)."""
    ffprobe = toolchain.find_executable(["ffprobe.exe", "ffprobe"], toolchain.tool_dirs())
    if ffprobe is None:
        raise SubtitleError("ffprobe not found")
    proc = subprocess.run(
        [str(ffprobe), "-v", "error", "-select_streams", str(stream_index), "-show_data",
         "-show_streams", "-show_packets", "-show_entries",
         "stream=extradata:packet=pts_time,duration_time,data", "-of", "json", str(source)],
        capture_output=True, creationflags=_NO_WINDOW,
    )  # fmt: skip
    if proc.returncode != 0:
        message = proc.stderr.decode("utf-8", errors="replace").strip()
        raise SubtitleError(f"cannot read DVD subtitle stream {stream_index}: {message}")
    info = json.loads(proc.stdout.decode("utf-8", errors="replace"))
    streams = info.get("streams") or []
    extradata = _hexdump(streams[0].get("extradata", "")) if streams else b""
    header = parse_idx(extradata.decode("latin-1"))
    packets = []
    for p in info.get("packets") or []:
        if "pts_time" not in p:
            continue
        duration = float(p["duration_time"]) if p.get("duration_time") else None
        packets.append((float(p["pts_time"]), duration, _hexdump(p.get("data", ""))))
    packets.sort(key=lambda p: p[0])
    return cues_from_packets(packets, header, frame, origin)
