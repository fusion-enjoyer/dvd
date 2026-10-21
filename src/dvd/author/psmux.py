"""Our own DVD program stream multiplexer: MPEG-2 video and AC-3 audio into 2048-byte packs,
a NAV pack (empty PCI and DSI, filled in by authoring) in front of every GOP.

Why not FFmpeg's `-f dvd`: it opens a new VOBU on an I-frame only 0.4 s or more after the
last one, so a chapter can land on the VOBU before its first picture, and it starts the
sound one frame before the first picture. Here every GOP (the encoders start one on each
chapter frame) is its own VOBU, and the first sound and the first picture share a time.

Time stamps: pictures are shown in temporal_reference order, each for its fields (2, or 3
with repeat_first_field); a picture is decoded when the one before it in display order is
shown, so B pictures are decoded as they are shown. The first decode time is 0.5 s after
the clock starts, as with FFmpeg. Packs are scheduled at the DVD mux rate: each carries the
stream whose next byte is needed soonest, as long as that stream's decoder buffer (230 KB
video, 4 KB audio) has room; when no buffer has room the clock jumps ahead.
"""

from __future__ import annotations

import mmap
from bisect import bisect_left, bisect_right
from contextlib import ExitStack
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path

PACK = 2048
MUX_RATE = 10_080_000  # bit/s
# The system clock in sevenths of 27 MHz cycles, so that a pack's time is a whole number.
TICK = 7 * 300  # one 90 kHz tick
PACK_TIME = PACK * 8 * 27_000_000 * 7 // MUX_RATE  # 307200: a pack at the mux rate
PRELOAD = 45_000  # first decode time (0.5 s)
VIDEO_BUFFER = 230 * 1024
AUDIO_BUFFER = 4 * 1024
ROOM = PACK - 14  # bytes after the pack header
# System header as FFmpeg's DVD muxer writes it (dvdauthor keeps it): rate bound, one audio
# and one video stream, buffer sizes for video, MPEG audio, private streams 1 and 2.
SYSTEM_HEADER = bytes.fromhex("000001bb001280c4e104e17fb9e0e6b8c020bdc000bfe002")
AC3_KBPS = (32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 384, 448, 512,
            576, 640)  # fmt: skip
FRAME_RATES = {1: Fraction(24000, 1001), 2: Fraction(24), 3: Fraction(25),
               4: Fraction(30000, 1001), 5: Fraction(30), 6: Fraction(50),
               7: Fraction(60000, 1001), 8: Fraction(60)}  # fmt: skip


class MuxError(ValueError):
    pass


@dataclass
class Unit:
    """One access unit: a picture (with the headers in front of it) or an audio frame."""

    start: int  # offset in the elementary stream
    end: int
    dts: int
    pts: int
    stamp: int  # where its time stamp belongs: the picture start code or frame sync
    gop: bool = False  # starts a GOP, so a VOBU


@dataclass
class _Stream:
    data: bytes | mmap.mmap
    units: list[Unit]
    buffer: int
    sid: int  # 0xE0 video, 0x80 + n AC-3
    sent: int = 0
    first: bool = True  # the first packet also gives the decoder buffer size
    removed: int = 0  # units already decoded
    removed_bytes: int = 0
    stamps: list[int] = field(default_factory=list)
    ends: list[int] = field(default_factory=list)
    gops: list[int] = field(default_factory=list)
    navs: int = 0  # GOPs that already have their NAV pack

    def __post_init__(self) -> None:
        self.stamps = [u.stamp for u in self.units]
        self.ends = [u.end for u in self.units]
        self.gops = [u.start for u in self.units if u.gop]

    @property
    def done(self) -> bool:
        return self.sent >= len(self.data)

    def deadline(self) -> int:
        return self.units[bisect_right(self.ends, self.sent)].dts

    def fill(self, now: int) -> int:
        """Bytes in the decoder buffer at `now` (90 kHz); a unit leaves it at its decode
        time."""
        units = self.units
        while self.removed < len(units) and units[self.removed].dts <= now \
                and units[self.removed].end <= self.sent:  # fmt: skip
            self.removed_bytes += units[self.removed].end - units[self.removed].start
            self.removed += 1
        return self.sent - self.removed_bytes

    def next_removal(self) -> int | None:
        return self.units[self.removed].dts if self.removed < len(self.units) else None

    def limit(self) -> int:
        """Where the next packet must stop: the next GOP start (its NAV pack goes first)."""
        i = bisect_right(self.gops, self.sent)
        return self.gops[i] if i < len(self.gops) else len(self.data)

    def first_stamp(self, start: int, end: int) -> int | None:
        """The unit whose stamp offset is the first in [start, end)."""
        i = bisect_left(self.stamps, start)
        return i if i < len(self.stamps) and self.stamps[i] < end else None


def _ts(value: int, prefix: int) -> bytes:
    return bytes([(prefix << 4) | ((value >> 29) & 0x0E) | 1, (value >> 22) & 0xFF,
                  ((value >> 14) & 0xFE) | 1, (value >> 7) & 0xFF,
                  ((value << 1) & 0xFE) | 1])  # fmt: skip


def pack_header(scr: int) -> bytes:
    """`scr` in sevenths of 27 MHz cycles."""
    base, ext = scr // TICK, scr % TICK // 7
    return b"\x00\x00\x01\xba" + bytes([
        0x44 | ((base >> 27) & 0x38) | ((base >> 28) & 0x03),
        (base >> 20) & 0xFF,
        ((base >> 12) & 0xF8) | 0x04 | ((base >> 13) & 0x03),
        (base >> 5) & 0xFF,
        ((base << 3) & 0xF8) | 0x04 | ((ext >> 7) & 0x03),
        ((ext << 1) & 0xFE) | 1,
        0x01, 0x89, 0xC3, 0xF8,  # mux rate 25200 x 50 bytes/s, no stuffing
    ])  # fmt: skip


def nav_pack(scr: int) -> bytes:
    """A NAV pack with an empty PCI and DSI (authoring writes them)."""
    pci = b"\x00\x00\x01\xbf\x03\xd4\x00" + bytes(979)
    dsi = b"\x00\x00\x01\xbf\x03\xfa\x01" + bytes(1017)
    return pack_header(scr) + SYSTEM_HEADER + pci + dsi


def video_units(data) -> list[Unit]:
    """The pictures of an MPEG-2 elementary stream with their decode and display times."""
    pictures: list[list] = []  # [unit start, picture start, temporal ref, fields, gop]
    header_start: int | None = None  # sequence/GOP headers waiting for their picture
    gop = False
    rate = None
    at = data.find(b"\x00\x00\x01")
    while at != -1 and at + 8 <= len(data):
        code = data[at + 3]
        if code == 0x00:
            start = 0 if not pictures else (at if header_start is None else header_start)
            temporal = (data[at + 4] << 2) | (data[at + 5] >> 6)
            pictures.append([start, at, temporal, 2, gop])
            header_start, gop = None, False
        elif code == 0xB5 and pictures and data[at + 4] >> 4 == 8 and pictures[-1][1] < at:
            structure = data[at + 6] & 3  # picture coding extension
            pictures[-1][3] = (3 if data[at + 7] & 0x02 else 2) if structure == 3 else 1
        elif code in (0xB3, 0xB8):
            if header_start is None:
                header_start = at
            if code == 0xB8:
                gop = True
            elif rate is None:
                rate = FRAME_RATES.get(data[at + 7] & 0x0F)
        at = data.find(b"\x00\x00\x01", at + 4)
    if not pictures or rate is None:
        raise MuxError("no MPEG-2 pictures in the video stream")
    field_ticks = Fraction(45_000) / rate
    # Display times, GOP by GOP in temporal_reference order.
    shown: list[Fraction] = [Fraction(0)] * len(pictures)
    clock, group = Fraction(0), []
    for i in range(len(pictures) + 1):
        if i == len(pictures) or (pictures[i][4] and group):
            for k in sorted(group, key=lambda k: pictures[k][2]):
                shown[k] = clock
                clock += pictures[k][3] * field_ticks
            group = []
        if i < len(pictures):
            group.append(i)
    times = sorted(shown)
    base = PRELOAD + 2 * field_ticks  # the first picture shown
    units = []
    for k, p in enumerate(pictures):
        decode = times[k - 1] if k else times[0] - 2 * field_ticks
        end = pictures[k + 1][0] if k + 1 < len(pictures) else len(data)
        units.append(Unit(p[0], end, int(base + decode), int(base + shown[k]), p[1], p[4]))
    return units


def audio_units(data, first_pts: int) -> list[Unit]:
    """The AC-3 frames of an elementary stream, 1536 samples (2880 ticks) each."""
    units, at = [], 0
    while at + 6 <= len(data):
        if data[at] != 0x0B or data[at + 1] != 0x77:
            raise MuxError(f"AC-3 sync lost at byte {at}")
        fscod, code = data[at + 4] >> 6, data[at + 4] & 0x3F
        if fscod != 0 or code // 2 >= len(AC3_KBPS):
            raise MuxError("only 48 kHz AC-3 goes on a DVD")
        size = AC3_KBPS[code // 2] * 4
        pts = first_pts + 2880 * len(units)
        units.append(Unit(at, min(at + size, len(data)), pts, pts, at))
        at += size
    return units


def _packet(s: _Stream) -> bytes:
    """The next PES packet of `s`, exactly ROOM bytes (with stuffing or a padding packet)."""
    start, limit = s.sent, s.limit()
    ext = (b"\x10\x60\xe6" if s.sid == 0xE0 else b"\x10\x60\x04") if s.first else b""
    sub = 4 if s.sid != 0xE0 else 0  # AC-3: substream, frame count, first frame pointer
    room = ROOM - 9 - len(ext) - sub
    unit = s.first_stamp(start, min(limit, start + room))
    stamp = b""
    if unit is not None:
        u = s.units[unit]
        stamp = _ts(u.pts, 3) + _ts(u.dts, 1) if u.dts != u.pts else _ts(u.pts, 2)
        unit = s.first_stamp(start, min(limit, start + room - len(stamp)))
        if unit is None:  # the stamp's room pushed the picture out: send without it
            stamp = b""
    payload = min(room - len(stamp), limit - start)
    body = bytes(s.data[start : start + payload])
    if sub:
        frames = 0
        if unit is not None:
            frames = bisect_left(s.stamps, start + payload) - unit
        pointer = s.stamps[unit] - start + 1 if unit is not None else 0
        body = bytes([s.sid, frames]) + pointer.to_bytes(2, "big") + body
    flags = (0xC0 if len(stamp) == 10 else 0x80 if stamp else 0) | (0x01 if ext else 0)
    short = ROOM - (9 + len(stamp) + len(ext) + len(body))
    stuffing = short if short <= 7 else 0
    header = stamp + ext + b"\xff" * stuffing
    sid = 0xE0 if s.sid == 0xE0 else 0xBD
    packet = b"\x00\x00\x01" + bytes([sid]) + (3 + len(header) + len(body)).to_bytes(2, "big") \
        + bytes([0x80, flags, len(header)]) + header + body  # fmt: skip
    if short > 7:
        packet += b"\x00\x00\x01\xbe" + (short - 6).to_bytes(2, "big") + b"\xff" * (short - 6)
    s.sent += payload
    s.first = False
    return packet


def mux(video: Path, audio: list[Path], out: Path) -> Path:
    """`video`: MPEG-2 elementary stream (.m2v); `audio`: AC-3 streams, in order."""
    with ExitStack() as stack:

        def mapped(path: Path) -> mmap.mmap:
            f = stack.enter_context(Path(path).open("rb"))
            return stack.enter_context(mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ))

        vd = mapped(video)
        units = video_units(vd)
        shown = min(u.pts for u in units)  # the sound starts with the first picture
        streams = [_Stream(vd, units, VIDEO_BUFFER, 0xE0)]
        for n, path in enumerate(audio):
            ad = mapped(path)
            streams.append(_Stream(ad, audio_units(ad, shown), AUDIO_BUFFER, 0x80 + n))
        _write(streams, out)
    return out


def _write(streams: list[_Stream], out: Path) -> None:
    scr = 0
    late = 0
    video = streams[0]
    with Path(out).open("wb") as f:
        while not all(s.done for s in streams):
            if video.navs < len(video.gops) and video.gops[video.navs] == video.sent:
                f.write(nav_pack(scr))  # a VOBU starts with the GOP's first byte
                video.navs += 1
                scr += PACK_TIME
                continue
            best, deadline = None, 0
            for s in streams:
                if s.done or s.fill(scr // TICK) + ROOM > s.buffer:
                    continue
                d = s.deadline()
                if best is None or d < deadline:
                    best, deadline = s, d
            if best is None:
                waits = [w for s in streams if not s.done and (w := s.next_removal()) is not None]
                if not waits or min(waits) * TICK <= scr:
                    raise MuxError("decoder buffers stay full")
                scr = min(waits) * TICK
                continue
            if deadline * TICK < scr + PACK_TIME:
                late += 1
            f.write(pack_header(scr) + _packet(best))
            scr += PACK_TIME
    if late:
        raise MuxError(f"{late} packs arrive after their decode time: the streams need more "
                       "than the DVD mux rate")  # fmt: skip
