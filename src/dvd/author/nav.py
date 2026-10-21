"""NAV packs for title VOBs: the PCI and DSI packets at the start of every VOBU.

Players read them to know where they are (sector, presentation times, cell), where the
reference pictures end (fast forward), how far the units 0.5 s ... 120 s away are (scanning),
and where each audio and subpicture stream continues. Field offsets are into the 2048-byte
pack, as on the disc; the rules for each field follow dvdauthor's FixVobus, which players
have accepted for many years, so the result can be compared with it byte for byte.
Menus with buttons (the highlight information in the PCI) are not written here yet.
"""

from __future__ import annotations

from dataclasses import dataclass

from dvd.author.vobu import Scan, Vobu

STEPS = (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 20, 60, 120, 240)  # half seconds
HALF_SECOND = 45000


@dataclass(frozen=True)
class CellMap:
    """Which VOBUs make up which cell: `starts` holds the index of each cell's first VOBU."""

    starts: list[int]
    vob_id: int = 1

    def cell_of(self, index: int) -> int:
        return max(k for k, s in enumerate(self.starts) if s <= index) + 1

    def span(self, index: int) -> tuple[int, int]:
        k = self.cell_of(index) - 1
        last = self.starts[k + 1] - 1 if k + 1 < len(self.starts) else None
        return self.starts[k], last if last is not None else -1


def _w(buf: bytearray, at: int, value: int, size: int = 4) -> None:
    buf[at : at + size] = (value & ((1 << (8 * size)) - 1)).to_bytes(size, "big")


def _bcd(n: int) -> int:
    return (n // 10) << 4 | n % 10


def bcd_time(ticks: int, pal: bool) -> int:
    """hh mm ss ff in BCD with the frame rate code, as cell and PGC times are written."""
    rate, code = (25, 1) if pal else (30, 3)
    ticks += 90000 // (rate * 2) + 1  # round to the nearest frame
    sec = ticks // 90000
    frames = (ticks % 90000) * rate // 90000
    minutes = sec // 60
    return (_bcd(minutes // 60) << 24 | _bcd(minutes % 60) << 16 | _bcd(sec % 60) << 8
            | _bcd(frames) | code << 6)  # fmt: skip


def _find(vobus: list[Vobu], pts: int, low: int, high: int) -> int:
    """Index of the VOBU (between low and high) shown at `pts`; outside: low-1 or high+1."""
    if high < low or pts < vobus[low].start_pts:
        return low - 1
    if pts >= vobus[high].end_pts:
        return high + 1
    while low < high:
        mid = (low + high + 1) // 2
        if pts < vobus[mid].start_pts:
            high = mid - 1
        else:
            low = mid
    return low


def _offset(vobus: list[Vobu], cells: CellMap, here: int, there: int, skip: bool,
            missing: int) -> int:  # fmt: skip
    """Relative sector distance with the flags the DSI uses: bit 31 the target has video,
    bit 30 units with video lie between (only for the long steps)."""
    flag = 0
    if skip:
        low, high = (here + 1, there - 1) if here < there else (there + 1, here - 1)
        if any(vobus[i].pictures for i in range(low, high + 1)):
            flag = 0x40000000
    if not 0 <= there < len(vobus) or cells.cell_of(there) != cells.cell_of(here):
        return missing | flag
    video = 0x80000000 if vobus[there].pictures else 0
    return abs(vobus[there].sector - vobus[here].sector) | video | flag


def _next_video(vobus: list[Vobu], here: int, step: int) -> int:
    i = here + step
    while 0 <= i < len(vobus):
        if vobus[i].pictures:
            return i
        i += step
    return -1


def _audio_offset(packets: list[tuple[int, int]], vobu: Vobu) -> int:
    """Sector offset from the VOBU to the audio packet playing at its start."""
    if not packets:
        return 0x3FFF
    low, high = 0, len(packets) - 1
    while high > low:
        mid = (low + high + 1) // 2
        if vobu.start_pts < packets[mid][1]:
            high = mid - 1
        else:
            low = mid
    sector, pts = packets[low]
    if pts > vobu.end_pts:
        return 0x3FFF
    s = sector - vobu.sector
    if abs(s) > 0x1FFF:
        return 0
    return (-s) | 0x8000 if s < 0 else s


def nav_pack(header: bytes, scan: Scan, cells: CellMap, index: int, pal: bool,
             audio_streams: int, subpicture_streams: int) -> bytes:  # fmt: skip
    """The NAV pack of VOBU `index`. `header`: its first 0x26 bytes as muxed (pack header
    and system header), kept as they are."""
    vobus = scan.vobus
    v = vobus[index]
    buf = bytearray(2048)
    buf[:0x26] = header[:0x26]
    _w(buf, 0x26, 0x1BF)
    _w(buf, 0x2A, 0x3D4, 2)
    buf[0x2C] = 0  # PCI
    _w(buf, 0x400, 0x1BF)
    _w(buf, 0x404, 0x3FA, 2)
    buf[0x406] = 1  # DSI

    first, last = cells.span(index)
    last = len(vobus) - 1 if last < 0 else last
    elapsed = bcd_time(v.start_pts - vobus[first].start_pts, pal)
    # PCI general information
    _w(buf, 0x2D, v.sector)
    _w(buf, 0x39, v.start_pts)
    _w(buf, 0x3D, v.end_pts)
    if v.seq_end:
        _w(buf, 0x41, v.end_pts)
    _w(buf, 0x45, elapsed)
    # DSI general information
    _w(buf, 0x407, v.scr)
    _w(buf, 0x40B, v.sector)
    _w(buf, 0x40F, v.last_sector - v.sector)
    refs = v.ref_ends[:3]
    for k in range(3 if refs else 0):
        _w(buf, 0x413 + 4 * k, refs[min(k, len(refs) - 1)])
    _w(buf, 0x41F, cells.vob_id, 2)
    buf[0x422] = cells.cell_of(index)
    _w(buf, 0x423, elapsed)
    _w(buf, 0x433, vobus[0].start_pts)
    _w(buf, 0x437, vobus[-1].end_pts)
    # Search information: the next and previous units, then those 0.5 s ... 120 s away.
    _w(buf, 0x4F1, _offset(vobus, cells, index, _next_video(vobus, index, 1), False, 0xBFFFFFFF))
    _w(buf, 0x541, _offset(vobus, cells, index, index + 1, False, 0x3FFFFFFF))
    _w(buf, 0x545, _offset(vobus, cells, index, index - 1, False, 0x3FFFFFFF))
    _w(buf, 0x595, _offset(vobus, cells, index, _next_video(vobus, index, -1), False,
                           0xBFFFFFFF))  # fmt: skip
    ahead = behind = index
    for j, step in enumerate(STEPS):
        forward = _find(vobus, v.start_pts + step * HALF_SECOND, first, last)
        backward = _find(vobus, v.start_pts - step * HALF_SECOND, first, last)
        _w(buf, 0x53D - 4 * j, _offset(vobus, cells, index, forward,
                                       j >= 15 and forward > ahead + 1, 0x3FFFFFFF))  # fmt: skip
        _w(buf, 0x549 + 4 * j, _offset(vobus, cells, index, backward,
                                       j >= 15 and backward < behind - 1, 0x3FFFFFFF))  # fmt: skip
        ahead, behind = forward, backward
    # Synchronous information: where each audio stream continues.
    for j in range(audio_streams):
        _w(buf, 0x599 + 2 * j, _audio_offset(scan.audio.get(j, []), v), 2)
    for j in range(subpicture_streams):
        _w(buf, 0x5A9 + 4 * j, _subpicture_offset(scan.subpictures.get(j, []), vobus, index))
    return bytes(buf)


def _subpicture_offset(units: list[tuple[int, int, int]], vobus: list[Vobu], here: int) -> int:
    """Where the subpicture showing during this VOBU (or the next one to show) is stored:
    0x7FFFFFFF for this or a later unit without a fixed place, else the sector distance
    (bit 31: backwards). 0 when the stream has no subpictures."""
    if not units:
        return 0
    v = vobus[here]
    found = [k for k, u in enumerate(units) if u[1] <= v.start_pts]
    k = found[-1] if found else -1

    def unit_of(sector: int) -> int:
        return max(i for i, x in enumerate(vobus) if x.sector <= sector)

    if k >= 0 and units[k][1] < v.end_pts and units[k][2] >= v.start_pts:
        target = unit_of(units[k][0])
    elif (k < 0 or units[k][2] < v.start_pts) and (
            k + 1 == len(units) or units[k + 1][1] >= v.end_pts):  # fmt: skip
        target = here
    else:
        target = unit_of(units[k + 1][0])
    if target == here:
        return 0x7FFFFFFF
    distance = abs(vobus[target].sector - v.sector)
    return distance | (0x80000000 if target < here else 0)
