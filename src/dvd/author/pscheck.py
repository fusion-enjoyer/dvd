"""DVD-Video check of a multiplexed MPEG program stream (the .mpg that goes into dvdauthor).

The video check (video/compliance.py) sees only the video. This one sees the whole stream as a
player reads it: 2048-byte packs, the declared mux rate, the rate over any one second of the
system clock (all streams together, limit 10.08 Mbit/s), and packets that arrive after their
own decode time, which is what happens when video and audio together do not fit and the
muxer falls behind, and the video decoder buffer (232 KB on DVD) overflowing because
pictures arrive too early. Only pack and PES headers are read: a picture's bytes are
counted from the packet that carries its time stamp to the next one, and leave the
buffer at its decode time. Where the clock starts again (titles muxed one by one and put
in one VOB, a cell with a time discontinuity), rate and buffer start again too.
"""

from __future__ import annotations

import mmap
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

PACK = 2048
MUX_RATE = 10_080_000  # bit/s
CLOCK = 90_000  # SCR base and PTS/DTS units
VIDEO_BUFFER = 232 * 1024  # DVD-Video's video decoder buffer


@dataclass
class StreamStats:
    bytes: int = 0
    late: int = 0
    worst_late: float = 0.0  # seconds
    peak_fill: int = 0  # video: most bytes in the decoder buffer at once


@dataclass
class MuxReport:
    packs: int
    duration: float  # seconds of system clock
    peak_bps: int  # all packs over one second of SCR
    max_mux_rate: int  # largest program_mux_rate field, bit/s
    streams: dict[str, StreamStats] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _ts(b: bytes) -> int:
    return (
        (((b[0] >> 1) & 7) << 30) | (b[1] << 22) | ((b[2] >> 1) << 15) | (b[3] << 7) | (b[4] >> 1)
    )


def _scr(b: bytes) -> int:
    return (
        (((b[0] >> 3) & 7) << 30) | ((b[0] & 3) << 28) | (b[1] << 20)
        | ((b[2] >> 3) << 15) | ((b[2] & 3) << 13) | (b[3] << 5) | (b[4] >> 3)
    )  # fmt: skip


def _stream_name(sid: int, payload: bytes) -> str | None:
    if 0xE0 <= sid <= 0xEF:
        return "video"
    if 0xC0 <= sid <= 0xDF:
        return f"mpa{sid - 0xC0}"
    if sid == 0xBD and payload:
        sub = payload[0]
        if 0x20 <= sub <= 0x3F:
            return f"sub{sub - 0x20}"
        if 0x80 <= sub <= 0x87:
            return f"ac3-{sub - 0x80}"
        if 0x88 <= sub <= 0x8F:
            return f"dts{sub - 0x88}"
        if 0xA0 <= sub <= 0xA7:
            return f"lpcm{sub - 0xA0}"
    return None


def check(path: Path) -> MuxReport:
    errors: list[str] = []
    streams: dict[str, StreamStats] = {}
    scrs: list[int] = []
    max_rate = 0
    misaligned = 0
    pictures: deque[list[int]] = deque()  # video in the decoder buffer: [decode time, bytes]
    filled = 0
    segments = [0]  # where the clock starts (again)
    with path.open("rb") as f, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as data:
        size = len(data)
        if size % PACK:
            errors.append(f"file size is not a multiple of {PACK} bytes")
        for start in range(0, size - size % PACK, PACK):
            if data[start : start + 4] != b"\x00\x00\x01\xba" or not data[start + 4] & 0x40:
                misaligned += 1
                continue
            scr = _scr(data[start + 4 : start + 9])
            if scrs and scr < scrs[-1]:  # the clock starts again: a new stream follows
                pictures.clear()
                filled = 0
                segments.append(len(scrs))
            scrs.append(scr)
            rate = (data[start + 10] << 14) | (data[start + 11] << 6) | (data[start + 12] >> 2)
            max_rate = max(max_rate, rate * 400)
            pos, end = start + 14 + (data[start + 13] & 7), start + PACK
            while pos + 6 <= end and data[pos : pos + 3] == b"\x00\x00\x01":
                sid = data[pos + 3]
                length = int.from_bytes(data[pos + 4 : pos + 6], "big")
                body = pos + 6
                nxt = body + length
                if sid in (0xBB, 0xBE, 0xBF):  # system header, padding, NAV data
                    pos = nxt
                    continue
                header_len = data[body + 2]
                flags = data[body + 1] >> 6
                payload = data[body + 3 + header_len : nxt]
                name = _stream_name(sid, payload[:1])
                if name is not None:
                    st = streams.setdefault(name, StreamStats())
                    st.bytes += len(payload)
                    due = None
                    if flags:
                        at = body + 3 + (5 if flags == 3 else 0)  # DTS when present, else PTS
                        due = _ts(data[at : at + 5])
                        if scr > due:
                            st.late += 1
                            st.worst_late = max(st.worst_late, (scr - due) / CLOCK)
                    if name == "video":
                        while pictures and pictures[0][0] <= scr:
                            filled -= pictures.popleft()[1]
                        if due is not None or not pictures:
                            pictures.append([due if due is not None else scr, 0])
                        pictures[-1][1] += len(payload)
                        filled += len(payload)
                        st.peak_fill = max(st.peak_fill, filled)
                pos = nxt
    if misaligned:
        errors.append(f"{misaligned} {PACK}-byte block(s) do not start with a pack header")
    if max_rate > MUX_RATE:
        errors.append(f"declared mux rate {max_rate / 1e6:.2f} Mbps exceeds 10.08")
    peak = 0
    for first, last in zip(segments, [*segments[1:], len(scrs)], strict=True):
        lo = first
        for hi in range(first, last):
            while scrs[hi] - scrs[lo] >= CLOCK:
                lo += 1
            peak = max(peak, (hi - lo + 1) * PACK * 8)
    # One pack of slack: a window can hold a pack at each edge.
    if peak > MUX_RATE + PACK * 8:
        errors.append(f"stream peaks at {peak / 1e6:.2f} Mbps over one second (limit 10.08)")
    video = streams.get("video")
    if video is not None and video.peak_fill > VIDEO_BUFFER + PACK:  # a pack of slack
        errors.append(f"video: the decoder buffer holds up to {video.peak_fill // 1024} KB "
                      f"(limit {VIDEO_BUFFER // 1024} KB); pictures arrive too early")  # fmt: skip
    for name, st in sorted(streams.items()):
        if st.late:
            errors.append(f"{name}: {st.late} packet(s) arrive after their decode time (up to "
                          f"{st.worst_late:.2f} s late); total bit rate is too high")  # fmt: skip
    spans = zip(segments, [*segments[1:], len(scrs)], strict=True)
    duration = sum((scrs[last - 1] - scrs[first]) / CLOCK for first, last in spans if last > first)
    return MuxReport(len(scrs), duration, peak, max_rate, streams, errors)
