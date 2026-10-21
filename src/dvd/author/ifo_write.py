"""Write titleset IFO files (VTS_nn_0.IFO / .BUP) ourselves.

The tables and the rules for filling them follow dvdauthor's dvdifo.c / dvdpgc.c, so the
result can be compared with dvdauthor byte for byte while we replace it step by step. This
first part writes titlesets without menus: the header with the stream attributes, the
chapter table (PTT), the program chains of the titles with their commands, programs and
cells, the time map, the cell address table and the VOBU address map.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from dvd.author.nav import bcd_time
from dvd.author.vobu import Scan
from dvd.ifo.vmc import compile_program

SECTOR = 2048
EXIT = bytes.fromhex("3001000000000000")
AUDIO_FORMAT = {"ac3": 0, "mpeg1": 2, "mpeg2": 3, "lpcm": 4, "dts": 6}


@dataclass
class AudioAttr:
    coding: str = "ac3"
    language: str | None = None  # two letters
    channels: int = 2
    stream: int = 0  # the stream number in the VOBs (0x80 + n for AC-3)
    surround: bool = False


@dataclass
class SubpictureAttr:
    language: str | None = None
    stream: int = 0  # 0x20 + n in the VOBs


@dataclass
class TitleSpec:
    """One title: one PGC playing one VOB, a cell (and chapter) per entry of `cells`."""

    scan: Scan
    cells: list[int]  # index of the first VOBU of each cell; cells[0] == 0
    pre: str = ""
    post: str = ""
    palette: list[int] = field(default_factory=list)  # 16 x 0xYYCrCb; empty: grey default


@dataclass
class TitlesetSpec:
    standard: str  # "pal" | "ntsc"
    aspect: str  # "16:9" | "4:3"
    titles: list[TitleSpec]
    audio: list[AudioAttr] = field(default_factory=list)
    subpictures: list[SubpictureAttr] = field(default_factory=list)


def _w(buf: bytearray, at: int, value: int, size: int = 4) -> None:
    buf[at : at + size] = (value & ((1 << (8 * size)) - 1)).to_bytes(size, "big")


def _sectors(data: bytes | bytearray) -> bytes:
    """Padded to whole sectors."""
    return bytes(data) + bytes(-len(data) % SECTOR)


def _video_attr(spec: TitlesetSpec) -> int:
    wide = spec.aspect == "16:9"
    return (0x4000  # MPEG-2
            | (0x200 if wide else 0)  # 16:9: no pan-scan (letterbox allowed)
            | (0x1000 if spec.standard == "pal" else 0)
            | (0xC00 if wide else 0x300))  # fmt: skip


def av_info(buf: bytearray, at: int, spec: TitlesetSpec) -> None:
    """Video, audio and subpicture attributes (0x200 onwards for titles)."""
    _w(buf, at, _video_attr(spec), 2)
    buf[at + 3] = len(spec.audio)
    for i, a in enumerate(spec.audio):
        o = at + 4 + 8 * i
        buf[o] = AUDIO_FORMAT[a.coding] << 5
        if a.language:
            buf[o] |= 4
            buf[o + 2 : o + 4] = a.language.encode("ascii")[:2]
        if a.surround:
            buf[o] |= 2
            buf[o + 7] = 8
        # quantization/DRC (AC-3, DTS and MPEG: 11 = dynamic range control), 48 kHz, channels
        drc = 0xC0 if a.coding != "lpcm" else 0
        buf[o + 1] = drc | (a.channels - 1)
    buf[at + 0x55] = len(spec.subpictures)
    for i, s in enumerate(spec.subpictures):
        if s.language:
            buf[at + 0x56 + 6 * i] = 1
            buf[at + 0x58 + 6 * i : at + 0x5A + 6 * i] = s.language.encode("ascii")[:2]


def _cell_vobus(title: TitleSpec) -> list[tuple[int, int]]:
    """(first, last) VOBU index of each cell."""
    starts = title.cells
    ends = [*(s - 1 for s in starts[1:]), len(title.scan.vobus) - 1]
    return list(zip(starts, ends, strict=True))


def _span(title: TitleSpec) -> int:
    v = title.scan.vobus
    return sum(v[last].end_pts - v[first].start_pts for first, last in _cell_vobus(title))


def title_pgc(title: TitleSpec, spec: TitlesetSpec, vob_id: int, sector_base: int) -> bytes:
    """One title PGC. `sector_base`: where this title's VOB starts in the titleset's VOBs."""
    pal = spec.standard == "pal"
    cells = _cell_vobus(title)
    buf = bytearray(0xEC)
    buf[2] = len(cells)  # every cell is a program (and a chapter)
    buf[3] = len(cells)
    _w(buf, 4, bcd_time(_span(title), pal))
    for i, a in enumerate(spec.audio):
        buf[12 + 2 * i] = 0x80 | a.stream
    wide = spec.aspect == "16:9"
    for i, s in enumerate(spec.subpictures):
        # 4:3 stream, wide stream, letterbox stream, pan-scan stream
        modes = [s.stream, s.stream, s.stream, 0] if wide else [s.stream, 0, 0, 0]
        for m, sid in enumerate(modes):
            if m == 0 or (wide and m < 3):
                buf[28 + 4 * i + m] = sid
        buf[28 + 4 * i] |= 0x80
    palette = title.palette or [0x108080] * 16
    for i, c in enumerate(palette):
        _w(buf, 164 + 4 * i, c)
    # Command table
    pre = compile_program(title.pre, "title") if title.pre.strip() else []
    post = compile_program(title.post, "title") if title.post.strip() else [EXIT]
    table = bytearray(8)
    commands = b"".join(pre + post)
    _w(table, 0, len(pre), 2)
    _w(table, 2, len(post), 2)
    _w(table, 4, 0, 2)
    _w(table, 6, 8 + len(commands) - 1, 2)
    _w(buf, 0xE4, 0xEC, 2)
    buf += table + commands
    # Program map: cell k starts program k
    _w(buf, 0xE6, len(buf), 2)
    buf += bytes(range(1, len(cells) + 1))
    if len(buf) & 1:
        buf += b"\0"
    # Cell playback information
    _w(buf, 0xE8, len(buf), 2)
    v = title.scan.vobus
    for k, (first, last) in enumerate(cells):
        entry = bytearray(24)
        entry[0] = 2 if k == 0 else 8  # first cell: time discontinuity; then seamless
        _w(entry, 4, bcd_time(v[last].end_pts - v[first].start_pts, pal))
        _w(entry, 8, sector_base + v[first].sector)
        _w(entry, 16, sector_base + v[last].sector)
        _w(entry, 20, sector_base + v[last].last_sector)
        buf += entry
    # Cell position information
    _w(buf, 0xEA, len(buf), 2)
    for k in range(len(cells)):
        buf += bytes((0, vob_id, 0, k + 1))
    return bytes(buf)


def pgcit(spec: TitlesetSpec, bases: list[int]) -> bytes:
    n = len(spec.titles)
    head = bytearray(8 + 8 * n)
    _w(head, 0, n, 2)
    body = bytearray()
    for i, title in enumerate(spec.titles):
        head[8 + 8 * i] = 0x80 | (i + 1)
        _w(head, 8 + 8 * i + 4, len(head) + len(body))
        body += title_pgc(title, spec, i + 1, bases[i])
    _w(head, 4, len(head) + len(body) - 1)
    return _sectors(head + body)


def ptt_srpt(spec: TitlesetSpec) -> bytes:
    n = len(spec.titles)
    buf = bytearray(8 + 4 * n)
    _w(buf, 0, n, 2)
    for j, title in enumerate(spec.titles):
        _w(buf, 8 + 4 * j, len(buf))
        for k in range(len(title.cells)):
            buf += bytes((0, j + 1, 0, k + 1))
    _w(buf, 4, len(buf) - 1)
    return _sectors(buf)


def _vobu_at(v: list, cells: list[tuple[int, int]], ticks: int) -> int | None:
    """The VOBU shown `ticks` after the start of the title (cells played in order)."""
    for first, last in cells:
        span = v[last].end_pts - v[first].start_pts
        if ticks < span:
            pts = ticks + v[first].start_pts
            i = first
            while i + 1 <= last and v[i + 1].start_pts <= pts:
                i += 1
            return i
        ticks -= span
    return None


def _cell_of(cells: list[tuple[int, int]], i: int) -> int:
    return max(k for k, (first, _last) in enumerate(cells) if first <= i)


def tmapti(spec: TitlesetSpec, bases: list[int]) -> bytes:
    """Time maps: per title the VOBU shown every `unit` seconds (bit 31: the next entry
    lies in another cell)."""
    denom = 90000 if spec.standard == "pal" else 90090
    maps = []
    for title, base in zip(spec.titles, bases, strict=True):
        seconds = (_span(title) - 1) // denom
        unit = 1 if not seconds else (seconds + 2039) // 2040
        count = seconds // unit
        entry = bytearray(4)
        entry[0] = unit
        _w(entry, 2, count, 2)
        v = title.scan.vobus
        cells = _cell_vobus(title)
        one = _vobu_at(v, cells, unit * denom)
        for j in range(count):
            two = _vobu_at(v, cells, (j + 2) * unit * denom)
            value = base + v[one].sector
            if two is None or _cell_of(cells, one) != _cell_of(cells, two):
                value |= 0x80000000
            entry += value.to_bytes(4, "big")
            one = two
        maps.append(bytes(entry))
    head = bytearray(8 + 4 * len(maps))
    _w(head, 0, len(maps), 2)
    offset = len(head)
    for i, m in enumerate(maps):
        _w(head, 8 + 4 * i, offset)
        offset += len(m)
    _w(head, 4, offset - 1)
    return _sectors(head + b"".join(maps))


def c_adt(spec: TitlesetSpec, bases: list[int]) -> bytes:
    buf = bytearray(8)
    _w(buf, 0, len(spec.titles), 2)
    for i, (title, base) in enumerate(zip(spec.titles, bases, strict=True)):
        v = title.scan.vobus
        for k, (first, last) in enumerate(_cell_vobus(title)):
            entry = bytearray(12)
            _w(entry, 0, i + 1, 2)
            entry[2] = k + 1
            _w(entry, 4, base + v[first].sector)
            _w(entry, 8, base + v[last].last_sector)
            buf += entry
    _w(buf, 4, len(buf) - 1)
    return _sectors(buf)


def vobu_admap(spec: TitlesetSpec, bases: list[int]) -> bytes:
    sectors = [base + v.sector for t, base in zip(spec.titles, bases, strict=True)
               for v in t.scan.vobus]  # fmt: skip
    buf = bytearray(4)
    _w(buf, 0, 4 * len(sectors) + 3)
    for s in sectors:
        buf += s.to_bytes(4, "big")
    return _sectors(buf)


def vob_bases(spec: TitlesetSpec) -> list[int]:
    """Where each title's VOB starts in the titleset's VOB set (sectors)."""
    bases, at = [], 0
    for t in spec.titles:
        bases.append(at)
        at += t.scan.vobus[-1].last_sector + 1
    return bases


def write_vts(spec: TitlesetSpec, menus: list | None = None) -> bytes:
    """The whole VTS_nn_0.IFO (the .BUP is the same bytes). `menus`: the titleset's menu
    pages (`menu_write.MenuSpec`), whose VOB is VTS_nn_0.VOB."""
    from dvd.author import menu_write

    bases = vob_bases(spec)
    pal, wide = spec.standard == "pal", spec.aspect == "16:9"
    tables = [(0xC8, ptt_srpt(spec)), (0xCC, pgcit(spec, bases))]
    if menus:
        tables.append((0xD0, _sectors(menu_write.pgci_ut(menus, pal, wide, 1, 1))))
    tables.append((0xD4, tmapti(spec, bases)))
    if menus:
        tables.append((0xD8, _sectors(menu_write.c_adt(menus))))
        tables.append((0xDC, _sectors(menu_write.vobu_admap(menus))))
    tables += [(0xE0, c_adt(spec, bases)), (0xE4, vobu_admap(spec, bases))]
    head = bytearray(SECTOR)
    head[:12] = b"DVDVIDEO-VTS"
    head[33] = 0x11  # version 1.1
    _w(head, 128, 0x7FF)  # end of VTSI_MAT
    at = 1
    for offset, part in tables:
        _w(head, offset, at)
        at += len(part) // SECTOR
    ifo_last = at - 1
    _w(head, 28, ifo_last)
    menu_sectors = menu_write.layout(menus)[2] if menus else 0
    if menus:
        _w(head, 0xC0, at)  # the menu VOB follows the IFO, then the title VOBs
    _w(head, 0xC4, at + menu_sectors)
    vobs = bases[-1] + spec.titles[-1].scan.vobus[-1].last_sector + 1
    _w(head, 12, at + menu_sectors + vobs + ifo_last)  # last sector (end of the BUP)
    if menus:  # menu streams: the page's silent stereo AC-3 and its button subpicture
        av_info(head, 0x100, TitlesetSpec(spec.standard, spec.aspect, [], [AudioAttr()],
                                          [SubpictureAttr()]))  # fmt: skip
    av_info(head, 0x200, spec)
    return bytes(head) + b"".join(part for _o, part in tables)


MIN_IFO_SECTORS = 16
PROVIDER = "DVD Studyo"


def write_vmg(titlesets: list[tuple[TitlesetSpec, bytes]], first_play: str = "",
              provider: str = PROVIDER) -> bytes:  # fmt: skip
    """VIDEO_TS.IFO for a disc without disc-level menus. `titlesets`: each spec with its
    written VTS IFO (for the titleset size and its attribute copy). `first_play`: commands
    run when the disc starts; empty: play title 1."""
    head = bytearray(SECTOR)
    head[:12] = b"DVDVIDEO-VMG"
    head[0x21] = 0x11
    head[0x27] = 1  # number of volumes
    head[0x29] = 1  # volume number
    head[0x2A] = 1  # side
    _w(head, 0x3E, len(titlesets), 2)
    head[0x40 : 0x40 + len(provider[:31])] = provider[:31].encode("ascii", "replace")
    head[0x86] = 4  # first play PGC at 0x400
    # Title search pointers (written below, once the titleset positions are known)
    tt_sectors = (8 + 12 * sum(len(s.titles) for s, _i in titlesets) + SECTOR - 1) // SECTOR
    _w(head, 0xC4, 1)
    atrt_at = 1 + tt_sectors
    _w(head, 0xD0, atrt_at)
    atrt_len = 8 + len(titlesets) * 0x30C
    ifo_sectors = atrt_at + (atrt_len + SECTOR - 1) // SECTOR
    _w(head, 0x1C, ifo_sectors - 1)
    vts_start = max(ifo_sectors * 2, 2 * MIN_IFO_SECTORS)
    _w(head, 0x0C, vts_start - 1)
    # First play PGC
    pal = titlesets[0][0].standard == "pal" if titlesets else True
    head[0x407] = (1 if pal else 3) << 6
    head[0x4E5] = 0xEC
    commands = compile_program(first_play, "vmg") if first_play.strip() \
        else [bytes.fromhex("3002000000010000")]  # jump title 1  # fmt: skip
    _w(head, 0x4EC, len(commands), 2)
    head[0x4F4 : 0x4F4 + 8 * len(commands)] = b"".join(commands)
    _w(head, 0x4F2, 7 + 8 * len(commands), 2)
    _w(head, 0x82, 0x4EC + 7 + 8 * len(commands), 2)

    tt = bytearray(8)
    start = vts_start
    count = 0
    for n, (spec, ifo) in enumerate(titlesets, start=1):
        for k, title in enumerate(spec.titles, start=1):
            entry = bytearray(12)
            entry[0] = 0x3C  # one sequential PGC; jumps allowed everywhere
            entry[1] = 1  # angles
            _w(entry, 2, len(title.cells), 2)
            entry[6], entry[7] = n, k
            _w(entry, 8, start)
            tt += entry
            count += 1
        start += int.from_bytes(ifo[12:16], "big") + 1
    _w(tt, 0, count, 2)
    _w(tt, 4, len(tt) - 1)

    atrt = bytearray(8 + 4 * len(titlesets))
    _w(atrt, 0, len(titlesets), 2)
    _w(atrt, 4, atrt_len - 1)
    for i in range(len(titlesets)):
        _w(atrt, 8 + 4 * i, len(atrt) + i * 0x308)
    for _spec, ifo in titlesets:
        entry = bytearray(0x308)
        _w(entry, 0, 0x307)
        entry[4:8] = ifo[0x22:0x26]
        entry[8:] = ifo[0x100:0x400]
        atrt += entry
    return bytes(head) + _sectors(tt) + _sectors(atrt)
