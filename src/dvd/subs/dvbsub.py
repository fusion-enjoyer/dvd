"""DVB bitmap subtitles (ETSI EN 300 743), as TV recordings carry them, decoded by us.

A display set is a run of segments (sync byte 0x0F, type, page id, length): the page
composition places regions on the screen, a region composition gives a region's size,
colour depth, CLUT and the objects drawn into it, CLUT definitions give colours (Y, Cr, Cb
and transparency), object data holds run-length coded pixels in two fields (2, 4 or 8 bits
a pixel, with map tables between depths), and the display definition gives the frame size
the positions refer to (720x576 without it). A set shows until the next one or until the
page time-out runs out. Regions and CLUTs carry over from set to set within an epoch.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field

import numpy as np

from dvd import toolchain
from dvd.subs.pgs import BitmapCue
from dvd.subs.srt import SubtitleError
from dvd.subs.vobsub import _hexdump

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

PAGE, REGION, CLUT, OBJECT, DISPLAY, END = 0x10, 0x11, 0x12, 0x13, 0x14, 0x80
MAP_2_TO_4 = (0x0, 0x7, 0x8, 0xF)
MAP_2_TO_8 = (0x00, 0x77, 0x88, 0xFF)
MAP_4_TO_8 = tuple(range(0x00, 0x100, 0x11))


def _ycrcb(y: int, cr: int, cb: int, t: int) -> tuple[int, int, int, int]:
    """BT.601 limited range (SD broadcast) to RGBA; T is transparency (0 opaque)."""
    if y == 0:  # Y 0 means fully transparent, whatever T says
        return (0, 0, 0, 0)
    yy, pb, pr = (y - 16) * 255 / 219, (cb - 128) * 255 / 224, (cr - 128) * 255 / 224
    rgb = (yy + 1.402 * pr, yy - 0.344136 * pb - 0.714136 * pr, yy + 1.772 * pb)
    r, g, b = (int(min(255, max(0, round(v)))) for v in rgb)
    return (r, g, b, 255 - t)


def _default_clut(depth: int) -> np.ndarray:
    """The standard's default colours: index 0 transparent, then white, black, greys and
    a spread of half-transparent and full colours."""
    if depth == 2:
        rows = [(0, 0, 0, 0), (255, 255, 255, 255), (0, 0, 0, 255), (127, 127, 127, 255)]
        return np.array(rows, np.uint8)
    out = np.zeros((1 << depth, 4), np.uint8)
    for i in range(1 << depth):
        if i == 0:
            continue
        level = 255 if (i & 0x0F) < 8 else 127  # 8 bits: the low nibble picks the colour
        out[i] = ((i & 1) * level, (i >> 1 & 1) * level, (i >> 2 & 1) * level, 255)
    return out


class _Bits:
    def __init__(self, data: bytes, at: int) -> None:
        self.data, self.bit = data, at * 8

    def read(self, n: int) -> int:
        v = 0
        for _ in range(n):
            byte = self.data[self.bit >> 3] if (self.bit >> 3) < len(self.data) else 0
            v = (v << 1) | ((byte >> (7 - (self.bit & 7))) & 1)
            self.bit += 1
        return v

    def align(self) -> int:
        self.bit = (self.bit + 7) & ~7
        return self.bit >> 3


def _string(bits: _Bits, depth: int) -> tuple[list[tuple[int, int]], bool]:
    """One pixel code string: (run length, code) pairs; False when the data ran out."""
    runs: list[tuple[int, int]] = []
    end = len(bits.data) * 8
    while bits.bit < end:
        if depth == 2:
            code = bits.read(2)
            if code:
                runs.append((1, code))
            elif bits.read(1):
                n = bits.read(3) + 3
                runs.append((n, bits.read(2)))
            elif bits.read(1):
                runs.append((1, 0))
            else:
                s = bits.read(2)
                if s == 0:
                    return runs, True
                if s == 1:
                    runs.append((2, 0))
                elif s == 2:
                    n = bits.read(4) + 12
                    runs.append((n, bits.read(2)))
                else:
                    n = bits.read(8) + 29
                    runs.append((n, bits.read(2)))
        elif depth == 4:
            code = bits.read(4)
            if code:
                runs.append((1, code))
            elif bits.read(1) == 0:
                n = bits.read(3)
                if n == 0:
                    return runs, True
                runs.append((n + 2, 0))
            elif bits.read(1) == 0:
                n = bits.read(2) + 4
                runs.append((n, bits.read(4)))
            else:
                s = bits.read(2)
                if s == 0:
                    runs.append((1, 0))
                elif s == 1:
                    runs.append((2, 0))
                elif s == 2:
                    n = bits.read(4) + 9
                    runs.append((n, bits.read(4)))
                else:
                    n = bits.read(8) + 25
                    runs.append((n, bits.read(4)))
        else:
            code = bits.read(8)
            if code:
                runs.append((1, code))
            elif bits.read(1) == 0:
                n = bits.read(7)
                if n == 0:
                    return runs, True
                runs.append((n, 0))
            else:
                n = bits.read(7)
                runs.append((n, bits.read(8)))
    return runs, False


def decode_field(data: bytes, rows: list[np.ndarray], depth: int, x0: int) -> None:
    """Pixel data of one field into `rows` (that field's lines of the object, codes at the
    region's `depth`)."""
    maps = {(2, 4): list(MAP_2_TO_4), (2, 8): list(MAP_2_TO_8), (4, 8): list(MAP_4_TO_8)}
    i, line, x = 0, 0, x0
    while i < len(data) and line < len(rows):
        kind = data[i]
        i += 1
        if kind in (0x10, 0x11, 0x12):
            bits = {0x10: 2, 0x11: 4, 0x12: 8}[kind]
            b = _Bits(data, i)
            runs, _ok = _string(b, bits)
            i = b.align()
            table = maps.get((bits, depth))
            row = rows[line]
            for n, code in runs:
                value = table[code] if table is not None and code < len(table) else code
                if x < row.shape[0]:
                    row[x : min(row.shape[0], x + n)] = value
                x += n
        elif kind == 0x20:
            maps[(2, 4)] = [data[i] >> 4, data[i] & 15, data[i + 1] >> 4, data[i + 1] & 15]
            i += 2
        elif kind == 0x21:
            maps[(2, 8)] = list(data[i : i + 4])
            i += 4
        elif kind == 0x22:
            maps[(4, 8)] = list(data[i : i + 16])
            i += 16
        elif kind == 0xF0:  # end of object line
            line += 1
            x = x0
        else:
            break


@dataclass
class _Region:
    width: int
    height: int
    depth: int
    clut: int
    pixels: np.ndarray
    background: int = 0
    objects: dict[int, tuple[int, int]] = field(default_factory=dict)  # object id -> x, y


class DvbDecoder:
    """Display sets in, finished pictures out; keeps regions and CLUTs between sets."""

    def __init__(self) -> None:
        self.regions: dict[int, _Region] = {}
        self.cluts: dict[int, dict[int, dict[int, tuple[int, int, int, int]]]] = {}
        self.page: list[tuple[int, int, int]] = []  # region id, x, y
        self.timeout = 0
        self.frame = (720, 576)

    def feed(self, data: bytes) -> bool:
        """Read one display set; True when it changed the page (a new picture or none)."""
        at = 2 if data[:2] == b"\x20\x00" else 0  # TS PES data field header
        changed = False
        while at + 6 <= len(data) and data[at] == 0x0F:
            kind = data[at + 1]
            length = int.from_bytes(data[at + 4 : at + 6], "big")
            body = data[at + 6 : at + 6 + length]
            at += 6 + length
            if kind == PAGE and len(body) >= 2:
                self.timeout = body[0]
                state = (body[1] >> 2) & 3
                if state in (1, 2):  # acquisition point, mode change: a fresh epoch
                    self.regions.clear()
                    self.cluts.clear()
                self.page = [(body[k], int.from_bytes(body[k + 2 : k + 4], "big"),
                              int.from_bytes(body[k + 4 : k + 6], "big"))
                             for k in range(2, len(body) - 5, 6)]  # fmt: skip
                changed = True
            elif kind == REGION and len(body) >= 10:
                self._region(body)
            elif kind == CLUT and len(body) >= 2:
                self._clut(body)
            elif kind == OBJECT and len(body) >= 3:
                self._object(body)
            elif kind == DISPLAY and len(body) >= 5:
                self.frame = (int.from_bytes(body[1:3], "big") + 1,
                              int.from_bytes(body[3:5], "big") + 1)  # fmt: skip
            elif kind == END:
                break
        return changed

    def _region(self, b: bytes) -> None:
        rid, fill = b[0], bool(b[1] & 0x08)
        width, height = int.from_bytes(b[2:4], "big"), int.from_bytes(b[4:6], "big")
        depth = {1: 2, 2: 4, 3: 8}.get((b[6] >> 2) & 7, 8)
        clut = b[7]
        background = {2: (b[9] >> 2) & 3, 4: b[9] >> 4, 8: b[8]}[depth]
        r = self.regions.get(rid)
        if r is None or (r.width, r.height, r.depth) != (width, height, depth):
            r = _Region(width, height, depth, clut, np.full((height, width), background, np.uint8))
            self.regions[rid] = r
        r.clut, r.background = clut, background
        if fill:
            r.pixels[:] = background
        r.objects = {}
        k = 10
        while k + 6 <= len(b):
            oid = int.from_bytes(b[k : k + 2], "big")
            otype = b[k + 2] >> 6
            x = int.from_bytes(b[k + 2 : k + 4], "big") & 0x0FFF
            y = int.from_bytes(b[k + 4 : k + 6], "big") & 0x0FFF
            r.objects[oid] = (x, y)
            k += 8 if otype in (1, 2) else 6

    def _clut(self, b: bytes) -> None:
        table = self.cluts.setdefault(b[0], {2: {}, 4: {}, 8: {}})
        k = 2
        while k + 2 <= len(b):
            entry, flags = b[k], b[k + 1]
            if flags & 1:  # full range
                if k + 6 > len(b):
                    break
                colour = _ycrcb(b[k + 2], b[k + 3], b[k + 4], b[k + 5])
                k += 6
            else:
                if k + 4 > len(b):
                    break
                v = int.from_bytes(b[k + 2 : k + 4], "big")
                y, cr, cb, t = v >> 10, (v >> 6) & 15, (v >> 2) & 15, v & 3
                colour = _ycrcb(y << 2, cr << 4, cb << 4, t * 85 if t < 3 else 255)
                k += 4
            for bit, depth in ((0x80, 2), (0x40, 4), (0x20, 8)):
                if flags & bit:
                    table[depth][entry] = colour

    def _object(self, b: bytes) -> None:
        oid = int.from_bytes(b[0:2], "big")
        if (b[2] >> 2) & 3 != 0 or len(b) < 7:  # only pixel objects (not character strings)
            return
        top_len = int.from_bytes(b[3:5], "big")
        bottom_len = int.from_bytes(b[5:7], "big")
        top = b[7 : 7 + top_len]
        bottom = b[7 + top_len : 7 + top_len + bottom_len] if bottom_len else top
        for r in self.regions.values():
            if oid not in r.objects:
                continue
            x, y = r.objects[oid]
            for parity, data in ((0, top), (1, bottom)):
                rows = [r.pixels[line] for line in range(y + parity, r.height, 2)]
                decode_field(data, rows, r.depth, x)

    def picture(self) -> tuple[np.ndarray, int, int] | None:
        """The page as one RGBA picture and its place on the frame; None when empty."""
        shown = [(self.regions[rid], x, y) for rid, x, y in self.page if rid in self.regions]
        if not shown:
            return None
        x0 = min(x for _r, x, _y in shown)
        y0 = min(y for _r, _x, y in shown)
        x1 = max(x + r.width for r, x, _y in shown)
        y1 = max(y + r.height for r, _x, y in shown)
        out = np.zeros((y1 - y0, x1 - x0, 4), np.uint8)
        for r, x, y in shown:
            colours = _default_clut(r.depth).copy()
            for entry, c in self.cluts.get(r.clut, {}).get(r.depth, {}).items():
                if entry < len(colours):
                    colours[entry] = c
            out[y - y0 : y - y0 + r.height, x - x0 : x - x0 + r.width] = colours[r.pixels]
        alpha = out[..., 3] > 0
        if not alpha.any():
            return None
        ys, xs = np.nonzero(alpha)
        crop = out[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1]
        return crop, x0 + int(xs.min()), y0 + int(ys.min())


def cues_from_packets(packets: list[tuple[float, bytes]], origin: float = 0.0) -> list[BitmapCue]:
    """Display sets (time, data) in time order to cues: each picture shows until the next
    set changes the page or its time-out runs out."""
    decoder = DvbDecoder()
    cues: list[BitmapCue] = []
    current: tuple[float, tuple[np.ndarray, int, int], int] | None = None

    def close(at: float) -> None:
        nonlocal current
        if current is not None:
            start, (picture, x, y), timeout = current
            end = min(at, start + timeout) if timeout else at
            if end > start:
                cues.append(BitmapCue(max(0.0, start - origin), end - origin, picture, x, y,
                                      *decoder.frame))  # fmt: skip
        current = None

    for t, data in packets:
        if not decoder.feed(data):
            continue
        close(t)
        shown = decoder.picture()
        if shown is not None:
            current = (t, shown, decoder.timeout)
    if current is not None:
        close(current[0] + (current[2] or 5))
    return cues


def to_video(cues: list[BitmapCue], video: tuple[int, int]) -> list[BitmapCue]:
    """Cues whose positions refer to the DVB display (720x576 unless the stream says
    otherwise) moved onto a `video`-sized frame, as the rest of the build expects."""
    out = []
    for c in cues:
        if (c.frame_width, c.frame_height) == video:
            out.append(c)
            continue
        sx, sy = video[0] / c.frame_width, video[1] / c.frame_height
        h, w = c.rgba.shape[:2]
        nw, nh = max(1, round(w * sx)), max(1, round(h * sy))
        rows = np.minimum((np.arange(nh) / sy).astype(int), h - 1)
        cols = np.minimum((np.arange(nw) / sx).astype(int), w - 1)
        out.append(BitmapCue(c.start, c.end, c.rgba[rows][:, cols], round(c.x * sx),
                             round(c.y * sy), *video, c.forced))  # fmt: skip
    return out


def extract_dvbsub(source, stream_index: int, origin: float = 0.0) -> list[BitmapCue]:
    """The cues of one dvb_subtitle stream of a TS or MKV file."""
    ffprobe = toolchain.find_executable(["ffprobe.exe", "ffprobe"], toolchain.tool_dirs())
    if ffprobe is None:
        raise SubtitleError("ffprobe not found")
    proc = subprocess.run(
        [str(ffprobe), "-v", "error", "-select_streams", str(stream_index), "-show_data",
         "-show_packets", "-show_entries", "packet=pts_time,data", "-of", "json", str(source)],
        capture_output=True, creationflags=_NO_WINDOW,
    )  # fmt: skip
    if proc.returncode != 0:
        message = proc.stderr.decode("utf-8", errors="replace").strip()
        raise SubtitleError(f"cannot read DVB subtitle stream {stream_index}: {message}")
    info = json.loads(proc.stdout.decode("utf-8", errors="replace"))
    packets = [(float(p["pts_time"]), _hexdump(p.get("data", "")))
               for p in info.get("packets") or [] if "pts_time" in p]  # fmt: skip
    packets.sort(key=lambda p: p[0])
    return cues_from_packets(packets, origin)
