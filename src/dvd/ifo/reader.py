"""IFO reader: the tables of VIDEO_TS.IFO (the disc) and VTS_nn_0.IFO (each titleset).

Offsets follow the DVD-Video layout as documented by the open-source players (libdvdread):
addresses in the IFO header count 2048-byte sectors from the start of the file, offsets
inside a table count bytes from the start of that table, all numbers are big-endian.
Commands are kept as their 8 raw bytes (`dvd.ifo.vm` turns them into text).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

SECTOR = 2048
MENU_KINDS = {2: "title", 3: "root", 4: "subpicture", 5: "audio", 6: "angle", 7: "ptt"}
AUDIO_CODING = {0: "ac3", 2: "mpeg1", 3: "mpeg2", 4: "lpcm", 6: "dts"}


class IfoError(ValueError):
    pass


def _u8(b: bytes, at: int) -> int:
    return b[at]


def _u16(b: bytes, at: int) -> int:
    return int.from_bytes(b[at : at + 2], "big")


def _u32(b: bytes, at: int) -> int:
    return int.from_bytes(b[at : at + 4], "big")


def _bcd(v: int) -> int:
    return (v >> 4) * 10 + (v & 0xF)


def playback_time(raw: bytes) -> float:
    """hh mm ss ff in BCD; the top two bits of the frame byte give the rate (1: 25, 3: 30)."""
    rate = {1: 25.0, 3: 30000 / 1001}.get(raw[3] >> 6, 25.0)
    return _bcd(raw[0]) * 3600 + _bcd(raw[1]) * 60 + _bcd(raw[2]) + _bcd(raw[3] & 0x3F) / rate


@dataclass
class Cell:
    seconds: float
    first_sector: int
    last_sector: int
    command: int  # cell command number, 0: none
    still: int  # 0: none, 255: forever, else seconds


@dataclass
class Pgc:
    programs: list[int]  # entry cell (1-based) of each program
    cells: list[Cell]
    seconds: float
    uops: int  # prohibited user operations mask
    pre: list[bytes] = field(default_factory=list)
    post: list[bytes] = field(default_factory=list)
    cell_commands: list[bytes] = field(default_factory=list)
    palette: list[tuple[int, int, int]] = field(default_factory=list)  # Y, Cr, Cb
    entry: str | None = None  # menus: "root", "ptt", ...; titles: None
    entry_pgc: bool = False
    still: int = 0


@dataclass
class Stream:
    kind: str  # "audio" | "subpicture"
    coding: str
    language: str | None
    channels: int = 0


@dataclass
class Title:
    number: int  # on the disc
    chapters: int
    angles: int
    titleset: int
    titleset_title: int  # the title's number inside its titleset


@dataclass
class Titleset:
    number: int
    standard: str  # "pal" | "ntsc"
    aspect: str  # "4:3" | "16:9"
    width: int
    audio: list[Stream]
    subpictures: list[Stream]
    titles: list[Pgc]  # the title PGCs, in table order
    title_of_pgc: list[int]  # for each title PGC: its title number in the titleset (0: none)
    chapters: list[list[tuple[int, int]]]  # per titleset title: (pgc, program) per chapter
    menus: list[Pgc]
    # Address tables: VOBU start sectors, and (vob id, cell id, first, last sector) per cell,
    # for the title VOBs and the menu VOB.
    title_vobus: list[int] = field(default_factory=list)
    title_cells: list[tuple[int, int, int, int]] = field(default_factory=list)
    menu_vobus: list[int] = field(default_factory=list)
    menu_cells: list[tuple[int, int, int, int]] = field(default_factory=list)


@dataclass
class Disc:
    titles: list[Title]
    first_play: Pgc | None
    menus: list[Pgc]
    titlesets: list[Titleset]
    provider: str = ""
    menu_vobus: list[int] = field(default_factory=list)
    menu_cells: list[tuple[int, int, int, int]] = field(default_factory=list)


def _video(attr: int) -> tuple[str, str, int]:
    standard = "pal" if (attr >> 12) & 3 == 1 else "ntsc"
    aspect = "16:9" if (attr >> 10) & 3 == 3 else "4:3"
    width = {0: 720, 1: 704, 2: 352, 3: 352}.get((attr >> 3) & 7, 720)
    return standard, aspect, width


def _language(b: bytes, at: int, typed: bool) -> str | None:
    code = b[at : at + 2]
    if not typed or code in (b"\0\0", b"  "):
        return None
    return code.decode("ascii", errors="replace")


def _audio(b: bytes, at: int) -> Stream:
    coding = AUDIO_CODING.get(b[at] >> 5, f"code {b[at] >> 5}")
    return Stream("audio", coding, _language(b, at + 2, (b[at] >> 2) & 3 == 1), (b[at + 1] & 7) + 1)


def _subpicture(b: bytes, at: int) -> Stream:
    return Stream("subpicture", "rle", _language(b, at + 2, b[at] & 3 == 1))


def read_pgc(b: bytes, at: int) -> Pgc:
    programs_n, cells_n = b[at + 2], b[at + 3]
    cmd_at, map_at, cells_at = _u16(b, at + 0xE4), _u16(b, at + 0xE6), _u16(b, at + 0xE8)
    pre = post = cell = []
    if cmd_at:
        c = at + cmd_at
        n_pre, n_post, n_cell = _u16(b, c), _u16(b, c + 2), _u16(b, c + 4)
        raw = [bytes(b[c + 8 + 8 * k : c + 16 + 8 * k]) for k in range(n_pre + n_post + n_cell)]
        pre, post, cell = raw[:n_pre], raw[n_pre : n_pre + n_post], raw[n_pre + n_post :]
    programs = [b[at + map_at + k] for k in range(programs_n)] if map_at else []
    cells = []
    for k in range(cells_n if cells_at else 0):
        e = at + cells_at + 24 * k
        cells.append(Cell(playback_time(b[e + 4 : e + 8]), _u32(b, e + 8), _u32(b, e + 20),
                          b[e + 3], b[e + 2]))  # fmt: skip
    palette = [(b[at + 0xA4 + 4 * k + 1], b[at + 0xA4 + 4 * k + 2], b[at + 0xA4 + 4 * k + 3])
               for k in range(16)]  # fmt: skip
    return Pgc(programs, cells, playback_time(b[at + 4 : at + 8]), _u32(b, at + 8), pre, post,
               cell, palette, still=b[at + 0xA2])  # fmt: skip


def _pgcit(b: bytes, table: int) -> list[tuple[int, Pgc]]:
    """(category byte, PGC) for each entry of a PGC table at byte `table`."""
    out = []
    for k in range(_u16(b, table)):
        e = table + 8 + 8 * k
        out.append((b[e], read_pgc(b, table + _u32(b, e + 4))))
    return out


def _menus(b: bytes, sector: int) -> list[Pgc]:
    """The menu PGCs of the first language unit of a PGCI_UT (all we write is one unit)."""
    if not sector:
        return []
    ut = sector * SECTOR
    if _u16(b, ut) == 0:
        return []
    lu = ut + _u32(b, ut + 8 + 4)
    menus = []
    for category, pgc in _pgcit(b, lu):
        pgc.entry_pgc = bool(category & 0x80)
        pgc.entry = MENU_KINDS.get(category & 0x0F) if pgc.entry_pgc else None
        menus.append(pgc)
    return menus


def _vobu_map(b: bytes, sector: int) -> list[int]:
    if not sector:
        return []
    at = sector * SECTOR
    count = (_u32(b, at) - 3) // 4
    return [_u32(b, at + 4 + 4 * k) for k in range(count)]


def _cell_table(b: bytes, sector: int) -> list[tuple[int, int, int, int]]:
    if not sector:
        return []
    at = sector * SECTOR
    count = (_u32(b, at + 4) + 1 - 8) // 12
    return [(_u16(b, at + 8 + 12 * k), b[at + 10 + 12 * k], _u32(b, at + 12 + 12 * k),
             _u32(b, at + 16 + 12 * k)) for k in range(count)]  # fmt: skip


def read_vmg(path: Path) -> Disc:
    b = Path(path).read_bytes()
    if b[:12] != b"DVDVIDEO-VMG":
        raise IfoError(f"{Path(path).name} is not a VIDEO_TS.IFO")
    fp = _u32(b, 0x84)
    first_play = read_pgc(b, fp) if fp else None
    tt = _u32(b, 0xC4) * SECTOR
    titles = []
    for k in range(_u16(b, tt)):
        e = tt + 8 + 12 * k
        titles.append(Title(k + 1, _u16(b, e + 2), b[e + 1], b[e + 6], b[e + 7]))
    provider = b[0x40:0x60].split(b"\0")[0].decode("ascii", errors="replace").strip()
    return Disc(titles, first_play, _menus(b, _u32(b, 0xC8)), [], provider,
                _vobu_map(b, _u32(b, 0xDC)), _cell_table(b, _u32(b, 0xD8)))  # fmt: skip


def read_vts(path: Path, number: int = 0) -> Titleset:
    b = Path(path).read_bytes()
    if b[:12] != b"DVDVIDEO-VTS":
        raise IfoError(f"{Path(path).name} is not a VTS_nn_0.IFO")
    standard, aspect, width = _video(_u16(b, 0x200))
    audio = [_audio(b, 0x204 + 8 * k) for k in range(min(8, _u16(b, 0x202)))]
    subs = [_subpicture(b, 0x256 + 6 * k) for k in range(min(32, _u16(b, 0x254)))]
    pgcs = _pgcit(b, _u32(b, 0xCC) * SECTOR)
    ptt = _u32(b, 0xC8) * SECTOR
    chapters = []
    count = _u16(b, ptt)
    starts = [_u32(b, ptt + 8 + 4 * k) for k in range(count)]
    end = _u32(b, ptt + 4) + 1
    for k, start in enumerate(starts):
        stop = starts[k + 1] if k + 1 < count else end
        chapters.append([(_u16(b, ptt + o), _u16(b, ptt + o + 2)) for o in range(start, stop, 4)])
    return Titleset(number, standard, aspect, width, audio, subs, [p for _c, p in pgcs],
                    [c & 0x7F for c, _p in pgcs], chapters, _menus(b, _u32(b, 0xD0)),
                    _vobu_map(b, _u32(b, 0xE4)), _cell_table(b, _u32(b, 0xE0)),
                    _vobu_map(b, _u32(b, 0xDC)), _cell_table(b, _u32(b, 0xD8)))  # fmt: skip


def read_disc(video_ts: Path) -> Disc:
    """The whole disc: VIDEO_TS.IFO and every titleset it names."""
    video_ts = Path(video_ts)
    disc = read_vmg(video_ts / "VIDEO_TS.IFO")
    count = max((t.titleset for t in disc.titles), default=0)
    disc.titlesets = [read_vts(video_ts / f"VTS_{n:02}_0.IFO", n) for n in range(1, count + 1)]
    return disc
