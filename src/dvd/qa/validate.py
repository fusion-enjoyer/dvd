"""DVD-Video compliance check of a finished VIDEO_TS folder, whoever authored it.

It reads the IFO tables and the NAV packs and checks what players rely on: the files are
there and their backups match, every title, chapter, program and cell points to something
that exists, the commands fit (128 per program chain) and jump only to titles, menus and
lines that exist, the cell and VOBU address tables agree with the VOBs, every VOBU starts
with a NAV pack that knows its own place and time, units last at most a second and follow
each other without gaps, and menu buttons stay within the limit of 36. From the first packs
of every VOBU: its video starts with a sequence header and an I picture (where players
start decoding after a jump), and its audio and subpicture packets belong to streams the
IFO declares.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from dvd.ifo import IfoError, Pgc, read_disc
from dvd.ifo.vm import decode

SECTOR = 2048
MAX_VOB_BYTES = 1 << 30
MAX_COMMANDS = 128
MAX_BUTTONS = 36
VOBU_MAX_TICKS = 90000 + 3600  # 1 s (a frame of slack for rounding)
STREAM_PACKS = 8  # packs read from the start of each VOBU for the stream checks


@dataclass(frozen=True)
class Finding:
    level: str  # "error" | "warning"
    where: str
    text: str

    def __str__(self) -> str:
        return f"{self.level}: {self.where}: {self.text}"


class _Vobs:
    """Sectors of a VOB set (VTS_nn_1.VOB, _2, ... or a single menu VOB) by number."""

    def __init__(self, files: list[Path]) -> None:
        self.files = [f for f in files if f.exists()]
        self.sizes = [f.stat().st_size // SECTOR for f in self.files]
        self.handles: dict = {}

    @property
    def sectors(self) -> int:
        return sum(self.sizes)

    def read(self, sector: int) -> bytes | None:
        for i, size in enumerate(self.sizes):
            if sector < size:
                if i not in self.handles:  # kept open: a film has thousands of VOBUs
                    self.handles[i] = self.files[i].open("rb")
                self.handles[i].seek(sector * SECTOR)
                return self.handles[i].read(SECTOR)
            sector -= size
        return None

    def close(self) -> None:
        for h in self.handles.values():
            h.close()
        self.handles.clear()


def _u32(b: bytes, at: int) -> int:
    return int.from_bytes(b[at : at + 4], "big")


def _commands(pgc: Pgc) -> list[bytes]:
    return pgc.pre + pgc.post + pgc.cell_commands


def _check_pgc(found: list[Finding], where: str, pgc: Pgc, ctx: dict) -> None:
    def add(level: str, text: str) -> None:
        found.append(Finding(level, where, text))

    total = len(_commands(pgc))
    if total > MAX_COMMANDS:
        add("error", f"{total} commands, at most {MAX_COMMANDS} fit in a program chain")
    if any(p < 1 or p > len(pgc.cells) for p in pgc.programs) or pgc.programs != sorted(
            pgc.programs):  # fmt: skip
        add("error", f"program entry cells {pgc.programs} do not fit {len(pgc.cells)} cells")
    for name, program in (("pre", pgc.pre), ("post", pgc.post), ("cell", pgc.cell_commands)):
        for line, raw in enumerate(program, start=1):
            text = decode(raw)
            problem = _target_problem(text, len(program), ctx)
            if text.startswith(("unknown", "jump op", "special ", "system set")):
                problem = "not a command players know"
            if problem:
                add("error", f"{name} command {line} ({text}): {problem}")
    for k, cell in enumerate(pgc.cells, start=1):
        if cell.first_sector > cell.last_sector:
            add("error", f"cell {k} ends before it starts")
        if cell.last_sector >= ctx["vob_sectors"]:
            add("error", f"cell {k} reaches sector {cell.last_sector}, the VOBs end at "
                         f"{ctx['vob_sectors'] - 1}")  # fmt: skip


def _number(pattern: str, text: str) -> int | None:
    m = re.search(pattern, text)
    return int(m.group(1)) if m else None


def _target_problem(text: str, lines: int, ctx: dict) -> str | None:
    """What is wrong with where a decoded command goes, if anything."""
    goto = _number(r"Goto (\d+)", text)
    if goto is not None and not 1 <= goto <= lines:
        return f"goes to line {goto} of {lines}"
    title = _number(r"JumpTT (\d+)", text)
    if title is not None and not 1 <= title <= ctx["disc_titles"]:
        return f"title {title} is not on the disc"
    title = _number(r"JumpVTS_TT (\d+)", text)
    if title is not None and not 1 <= title <= ctx["vts_titles"]:
        return f"titleset title {title} does not exist"
    m = re.search(r"JumpVTS_PTT (\d+):(\d+)", text)
    if m:
        title, ptt = int(m.group(1)), int(m.group(2))
        if not 1 <= title <= ctx["vts_titles"] or not 1 <= ptt <= ctx["ptts"][title - 1]:
            return f"chapter {ptt} of titleset title {title} does not exist"
    pgc = _number(r"LinkPGCN (\d+)", text)
    if pgc is not None and not 1 <= pgc <= ctx["domain_pgcs"]:
        return f"program chain {pgc} does not exist here"
    m = re.search(r"CallSS VTSM (\w+)", text)
    if m and m.group(1) not in ctx["vtsm_entries"]:
        return f"the titleset has no {m.group(1)} menu"
    m = re.search(r"JumpSS VTSM \(vts (\d+), title \d+\) (\w+)", text)
    if m:
        entries = ctx["entries_of"].get(int(m.group(1)))
        if entries is None:
            return f"titleset {m.group(1)} does not exist"
        if m.group(2) not in entries:
            return f"titleset {m.group(1)} has no {m.group(2)} menu"
    m = re.search(r"(?:JumpSS|CallSS) VMGM (title|root)", text)
    if m and m.group(1) not in ctx["vmgm_entries"]:
        return f"the disc has no {m.group(1)} menu"
    return None


def _stream_problems(vobs: _Vobs, sector: int, end: int | None,
                     streams: tuple[int, int] | None) -> list[str]:  # fmt: skip
    """The first packs of the VOBU at `sector`: how its video starts, and audio/subpicture
    stream numbers beyond what the IFO declares (`streams`: audio, subpicture counts)."""
    problems: list[str] = []
    video_start = None
    last = min(sector + STREAM_PACKS, end if end is not None else sector + STREAM_PACKS)
    for at in range(sector + 1, last + 1):
        pack = vobs.read(at)
        if pack is None or pack[:4] != b"\x00\x00\x01\xba":
            break
        pos = 14 + (pack[13] & 7)
        while pos + 9 <= SECTOR and pack[pos : pos + 3] == b"\x00\x00\x01":
            sid = pack[pos + 3]
            length = int.from_bytes(pack[pos + 4 : pos + 6], "big")
            data = pos + 9 + pack[pos + 8]
            if 0xE0 <= sid <= 0xEF and video_start is None:
                video_start = bytes(pack[data : pos + 6 + length])
            elif sid == 0xBD and streams is not None and data < SECTOR:
                sub = pack[data]
                if 0x80 <= sub <= 0x87 or 0xA0 <= sub <= 0xA7 or 0x88 <= sub <= 0x8F:
                    if sub & 0x07 >= streams[0]:
                        problems.append(f"audio stream {(sub & 0x07) + 1} is not in the IFO")
                elif 0x20 <= sub <= 0x3F and sub - 0x20 >= streams[1]:
                    problems.append(f"subpicture stream {sub - 0x20 + 1} is not in the IFO")
            pos += 6 + length
    if video_start is not None:
        if not video_start.startswith(b"\x00\x00\x01\xb3"):
            problems.append("its video does not start with a sequence header")
        else:
            picture = video_start.find(b"\x00\x00\x01\x00")
            if picture != -1 and picture + 6 <= len(video_start) and \
                    (video_start[picture + 5] >> 3) & 7 != 1:  # fmt: skip
                problems.append("its first picture is not an I picture")
    return sorted(set(problems))


def _check_vobus(found: list[Finding], where: str, vobs: _Vobs, vobus: list[int],
                 cells: list[tuple[int, int, int, int]], menus: bool,
                 streams: tuple[int, int] | None = None) -> None:  # fmt: skip
    """NAV packs against the address tables: place, end, time span, cell; the start of
    each VOBU's streams."""
    if vobus != sorted(vobus) or len(set(vobus)) != len(vobus):
        found.append(Finding("error", where, "the VOBU address map is not in order"))
        return
    cell_at = {}
    for vob_id, cell_id, first, last in cells:
        cell_at.update({s: (vob_id, cell_id) for s in vobus if first <= s <= last})
    previous = None
    for k, sector in enumerate(vobus):
        pack = vobs.read(sector)
        name = f"{where}, VOBU at sector {sector}"
        if pack is None:
            found.append(Finding("error", name, "beyond the end of the VOB files"))
            return
        if pack[:4] != b"\x00\x00\x01\xba" or pack[14:18] != b"\x00\x00\x01\xbb" or \
                pack[0x26:0x2A] != b"\x00\x00\x01\xbf" or pack[0x406] != 1:  # fmt: skip
            found.append(Finding("error", name, "does not start with a NAV pack"))
            continue
        if _u32(pack, 0x40B) != sector or _u32(pack, 0x2D) != sector:
            found.append(Finding("error", name, f"its NAV pack says sector {_u32(pack, 0x40B)}"))
        end = vobus[k + 1] - 1 if k + 1 < len(vobus) else None
        if end is not None and sector + _u32(pack, 0x40F) != end:
            found.append(Finding("warning", name, "its end address is not where the next "
                                                  "VOBU starts"))  # fmt: skip
        start, stop = _u32(pack, 0x39), _u32(pack, 0x3D)
        if stop <= start:
            found.append(Finding("error", name, "ends before it starts"))
        elif stop - start > VOBU_MAX_TICKS and not menus:
            found.append(Finding("warning", name, f"lasts {(stop - start) / 90000:.2f} s, "
                                                  "a VOBU should last at most 1 s"))  # fmt: skip
        cell = (int.from_bytes(pack[0x41F:0x421], "big"), pack[0x422])
        if sector in cell_at and cell != cell_at[sector]:
            found.append(Finding("error", name, f"its NAV pack names cell {cell}, the cell "
                                                f"table says {cell_at[sector]}"))  # fmt: skip
        if previous is not None and previous[0] == cell and previous[1] != start:
            found.append(Finding("warning", name, "a gap or overlap in time with the VOBU "
                                                  "before it"))  # fmt: skip
        previous = (cell, stop)
        for problem in _stream_problems(vobs, sector, end, streams):
            found.append(Finding("error", name, problem))
        buttons = pack[0x9E]
        if menus and buttons > MAX_BUTTONS:
            found.append(Finding("error", name, f"{buttons} buttons, at most {MAX_BUTTONS}"))


def validate(video_ts: Path) -> list[Finding]:
    video_ts = Path(video_ts)
    found: list[Finding] = []
    for name in ("VIDEO_TS.IFO", "VIDEO_TS.BUP"):
        if not (video_ts / name).is_file():
            found.append(Finding("error", name, "missing"))
    if found:
        return found
    try:
        disc = read_disc(video_ts)
    except (IfoError, OSError, IndexError, ValueError) as exc:
        return [Finding("error", "IFO", f"cannot be read: {exc}")]

    def same(stem: str) -> None:
        ifo, bup = video_ts / f"{stem}.IFO", video_ts / f"{stem}.BUP"
        if not bup.is_file():
            found.append(Finding("error", bup.name, "missing"))
        elif ifo.read_bytes() != bup.read_bytes():
            found.append(Finding("warning", bup.name, f"differs from {ifo.name}"))

    same("VIDEO_TS")
    for f in video_ts.glob("*.VOB"):
        if f.stat().st_size > MAX_VOB_BYTES:
            found.append(Finding("error", f.name, "larger than 1 GB"))
    entries_of = {ts.number: {m.entry for m in ts.menus if m.entry} for ts in disc.titlesets}
    vmgm_entries = {m.entry for m in disc.menus if m.entry}
    for t in disc.titles:
        if not 1 <= t.titleset <= len(disc.titlesets):
            found.append(Finding("error", f"title {t.number}", f"titleset {t.titleset} missing"))
            continue
        ts = disc.titlesets[t.titleset - 1]
        if not 1 <= t.titleset_title <= len(ts.chapters):
            found.append(Finding("error", f"title {t.number}", "its titleset title is missing"))
        elif len(ts.chapters[t.titleset_title - 1]) != t.chapters:
            found.append(Finding("error", f"title {t.number}", f"{t.chapters} chapters in the "
                                 f"disc table, {len(ts.chapters[t.titleset_title - 1])} in "
                                 "the titleset"))  # fmt: skip

    vmg_vobs = _Vobs([video_ts / "VIDEO_TS.VOB"])
    base = {"disc_titles": len(disc.titles), "vts_titles": 0, "ptts": [], "vtsm_entries": set(),
            "entries_of": entries_of, "vmgm_entries": vmgm_entries}  # fmt: skip
    if disc.first_play is not None:
        _check_pgc(found, "first play", disc.first_play,
                   {**base, "domain_pgcs": len(disc.menus), "vob_sectors": 1 << 30})  # fmt: skip
    for k, menu in enumerate(disc.menus, start=1):
        _check_pgc(found, f"disc menu {k}", menu,
                   {**base, "domain_pgcs": len(disc.menus),
                    "vob_sectors": vmg_vobs.sectors})  # fmt: skip
    if disc.menus:
        _check_vobus(found, "disc menus", vmg_vobs, disc.menu_vobus, disc.menu_cells, True)
    vmg_vobs.close()

    for ts in disc.titlesets:
        stem = f"VTS_{ts.number:02}_0"
        same(stem)
        ctx = {**base, "vts_titles": len(ts.chapters), "ptts": [len(c) for c in ts.chapters],
               "vtsm_entries": entries_of[ts.number]}  # fmt: skip
        titles = _Vobs([video_ts / f"VTS_{ts.number:02}_{n}.VOB" for n in range(1, 10)])
        menus = _Vobs([video_ts / f"{stem}.VOB"])
        for k, pgc in enumerate(ts.titles, start=1):
            _check_pgc(found, f"titleset {ts.number} title PGC {k}", pgc,
                       {**ctx, "domain_pgcs": len(ts.titles),
                        "vob_sectors": titles.sectors})  # fmt: skip
        for k, menu in enumerate(ts.menus, start=1):
            _check_pgc(
                found,
                f"titleset {ts.number} menu {k}",
                menu,
                {**ctx, "domain_pgcs": len(ts.menus), "vob_sectors": menus.sectors},
            )
        for title, chapters in enumerate(ts.chapters, start=1):
            for pgcn, pgn in chapters:
                if not 1 <= pgcn <= len(ts.titles) or not 1 <= pgn <= len(
                        ts.titles[pgcn - 1].programs):  # fmt: skip
                    found.append(
                        Finding(
                            "error",
                            f"titleset {ts.number} title {title}",
                            f"chapter points to PGC {pgcn} program {pgn}",
                        )
                    )
        _check_vobus(found, f"titleset {ts.number} titles", titles, ts.title_vobus,
                     ts.title_cells, False, (len(ts.audio), len(ts.subpictures)))  # fmt: skip
        if ts.menus:
            _check_vobus(found, f"titleset {ts.number} menus", menus, ts.menu_vobus,
                         ts.menu_cells, True)  # fmt: skip
        titles.close()
        menus.close()
    return found
