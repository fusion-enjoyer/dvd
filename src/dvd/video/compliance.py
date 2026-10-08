"""DVD-Video compliance check of an MPEG-2 elementary stream (.m2v).

Parses only header start codes (sequence, extensions, GOP, picture), so a feature-length file
is scanned in seconds. Checks the limits in docs/dvd-spec.md: MP@ML, resolutions and frame
rates, progressive_sequence = 0, GOP length, consecutive B-pictures, peak bitrate over one
second, and a VBV buffer simulation (MPEG-2 Annex C, VBR mode) for underflows.
"""

from __future__ import annotations

import mmap
import re
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path

VBV_BITS = 1_835_008  # 224 KiB
VIDEO_PEAK = 9_800_000  # bit/s
FRAME_RATES = {1: Fraction(24000, 1001), 2: Fraction(24), 3: Fraction(25),
               4: Fraction(30000, 1001), 5: Fraction(30)}  # fmt: skip
SIZES = {
    "pal": {(720, 576), (704, 576), (352, 576), (352, 288)},
    "ntsc": {(720, 480), (704, 480), (352, 480), (352, 240)},
}
MAX_GOP = {"pal": 15, "ntsc": 18}
_HEADER = re.compile(rb"\x00\x00\x01[\x00\xb3\xb5\xb8\xb7]")


class _Bits:
    def __init__(self, data: bytes) -> None:
        self.value, self.left = int.from_bytes(data, "big"), len(data) * 8

    def read(self, n: int) -> int:
        self.left -= n
        return (self.value >> self.left) & ((1 << n) - 1)


@dataclass
class Picture:
    kind: str  # I, P, B
    bits: int
    fields: int  # display duration in fields: 2, or 3 with repeat_first_field


@dataclass
class StreamInfo:
    width: int = 0
    height: int = 0
    aspect_code: int = 0
    frame_rate: Fraction = Fraction(0)
    bit_rate: int = 0  # from the sequence header, bit/s
    vbv_bits: int = 0
    profile_level: int = 0
    progressive_sequence: int = 0
    pictures: list[Picture] = field(default_factory=list)
    gops: list[int] = field(default_factory=list)  # pictures per GOP
    first_gop_closed: bool = False


@dataclass
class Report:
    info: StreamInfo
    errors: list[str]
    warnings: list[str]
    peak_bps: int
    average_bps: int
    vbv_lowest: float  # lowest buffer fullness before a picture is removed, 0..1

    @property
    def ok(self) -> bool:
        return not self.errors


def parse(path: Path) -> StreamInfo:
    info = StreamInfo()
    with path.open("rb") as f, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as data:
        size = len(data)
        unit_start = 0
        unit_has_picture = False
        current: Picture | None = None
        gop_count = -1
        seen_sequence = False

        def close_unit(end: int) -> None:
            if current is not None:
                current.bits = (end - unit_start) * 8

        for m in _HEADER.finditer(data):
            pos, code = m.start(), data[m.start() + 3]
            # A new access unit starts at the first header after a picture's slices.
            if code in (0x00, 0xB3, 0xB8, 0xB7) and unit_has_picture:
                close_unit(pos)
                unit_start, unit_has_picture, current = pos, False, None
            body = data[pos + 4 : pos + 16]
            if code == 0xB3:
                b = _Bits(body[:8])
                info.width, info.height = b.read(12), b.read(12)
                info.aspect_code, rate_code = b.read(4), b.read(4)
                info.frame_rate = FRAME_RATES.get(rate_code, Fraction(0))
                info.bit_rate = b.read(18) * 400
                b.read(1)
                info.vbv_bits = b.read(10) * 16 * 1024
                seen_sequence = True
            elif code == 0xB5:
                b = _Bits(body[:6])
                ext = b.read(4)
                if ext == 1:  # sequence extension
                    info.profile_level = b.read(8)
                    info.progressive_sequence = b.read(1)
                elif ext == 8 and current is not None:  # picture coding extension
                    b.read(16 + 2)  # f_codes, intra_dc_precision
                    structure = b.read(2)
                    b.read(1 + 1 + 1 + 1 + 1 + 1)  # tff .. alternate_scan
                    rff = b.read(1)
                    current.fields = (3 if rff else 2) if structure == 3 else 1
            elif code == 0xB8:
                closed = bool((int.from_bytes(body[:4], "big") >> 6) & 1)
                if gop_count < 0:
                    info.first_gop_closed = closed
                else:
                    info.gops.append(gop_count)
                gop_count = 0
            elif code == 0x00:
                b = _Bits(body[:2])
                b.read(10)
                kind = {1: "I", 2: "P", 3: "B"}.get(b.read(3), "?")
                current = Picture(kind, 0, 2)
                info.pictures.append(current)
                unit_has_picture = True
                if gop_count >= 0:
                    gop_count += 1
        close_unit(size)
        if gop_count > 0:
            info.gops.append(gop_count)
        if not seen_sequence:
            raise ValueError(f"{path.name} has no MPEG video sequence header")
    return info


def _bitrates(info: StreamInfo) -> tuple[int, int]:
    """Peak bit rate over any one-second window, and the average."""
    field_time = 1 / (2 * float(info.frame_rate))
    times, t = [], 0.0
    for p in info.pictures:
        times.append(t)
        t += p.fields * field_time
    total = sum(p.bits for p in info.pictures)
    peak, window, lo = 0, 0, 0
    for hi, p in enumerate(info.pictures):
        window += p.bits
        while times[hi] - times[lo] >= 1.0:
            window -= info.pictures[lo].bits
            lo += 1
        peak = max(peak, window)
    return peak, int(total / t) if t else 0


def _vbv(info: StreamInfo) -> tuple[float, int]:
    """VBR-mode VBV: the buffer fills at the header bit rate until full; each picture is removed
    when it is decoded. Returns the lowest fullness (fraction) and the number of underflows."""
    size = info.vbv_bits or VBV_BITS
    rate = info.bit_rate or VIDEO_PEAK
    field_time = 1 / (2 * float(info.frame_rate))
    fullness, lowest, underflows = float(size), 1.0, 0  # decoding starts with a full buffer
    for p in info.pictures:
        lowest = min(lowest, fullness / size)
        if p.bits > fullness:
            underflows += 1
            fullness = 0.0
        else:
            fullness -= p.bits
        fullness = min(size, fullness + rate * p.fields * field_time)
    return lowest, underflows


def check(path: Path, standard: str) -> Report:
    info = parse(path)
    errors, warnings = [], []
    if not info.pictures:
        errors.append("no pictures in the stream")
        return Report(info, errors, warnings, 0, 0, 0.0)
    if (info.width, info.height) not in SIZES[standard]:
        errors.append(f"{info.width}x{info.height} is not a DVD {standard.upper()} size")
    if info.profile_level != 0x48:
        errors.append(f"profile/level 0x{info.profile_level:02X} is not Main Profile @ Main Level")
    if info.progressive_sequence:
        errors.append("progressive_sequence is 1; DVD-Video requires 0")
    expected = Fraction(25) if standard == "pal" else Fraction(30000, 1001)
    if info.frame_rate != expected:
        errors.append(f"frame rate {float(info.frame_rate):.3f} is not {float(expected):.3f}")
    if info.aspect_code not in (2, 3):
        errors.append(f"aspect ratio code {info.aspect_code} is not 4:3 (2) or 16:9 (3)")
    if info.bit_rate > VIDEO_PEAK:
        errors.append(f"sequence header bit rate {info.bit_rate / 1e6:.2f} Mbps exceeds 9.8")
    if info.vbv_bits > VBV_BITS:
        errors.append(f"VBV buffer {info.vbv_bits} bits exceeds the DVD maximum {VBV_BITS}")
    if not info.first_gop_closed:
        warnings.append("first GOP is not closed")
    long_gops = [g for g in info.gops if g > MAX_GOP[standard]]
    if long_gops:
        errors.append(f"{len(long_gops)} GOP(s) longer than {MAX_GOP[standard]} pictures "
                      f"(longest {max(long_gops)})")  # fmt: skip
    run = longest_b = 0
    for p in info.pictures:
        run = run + 1 if p.kind == "B" else 0
        longest_b = max(longest_b, run)
    if longest_b > 2:
        errors.append(f"{longest_b} consecutive B-pictures; DVD allows at most 2")
    peak, average = _bitrates(info)
    if peak > VIDEO_PEAK:
        errors.append(f"video peaks at {peak / 1e6:.2f} Mbps over one second (limit 9.8)")
    lowest, underflows = _vbv(info)
    if underflows:
        errors.append(f"VBV buffer underflows {underflows} time(s): players may stutter")
    elif lowest < 0.05:
        warnings.append(f"VBV buffer drops to {lowest:.0%}")
    return Report(info, errors, warnings, peak, average, lowest)
