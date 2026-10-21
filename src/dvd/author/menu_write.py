"""Titleset menus for our own authoring: the menu PGCs (VTSM_PGCI_UT), their VOBs' address
tables and the button information of their NAV packs.

Each menu page is a PGC playing one or more VOBs (an intro then a loop, or a still) made by
spumux: still video, silent audio and the button subpicture. spumux describes the buttons
(rectangles, neighbours) and their highlight colours in an information packet that is read
with the subpicture colours (`spu_colors.py`). A button command that compiles to a single
VM instruction goes into the NAV pack; a longer one is reached the way dvdauthor does it: the
button sets g15 to its number and links to the PGC's post commands, which start with a
table that jumps to that button's program.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from dvd.author.nav import bcd_time
from dvd.author.vobu import Scan
from dvd.ifo.vmc import compile_program

EXIT = bytes.fromhex("3001000000000000")
MENU_CODE = {"title": 2, "root": 3, "subtitle": 4, "audio": 5, "angle": 6, "ptt": 7}
MAX_BUTTONS = 36


@dataclass
class Button:
    """A button as spumux placed it, with what it does."""

    name: str
    x1: int
    y1: int
    x2: int
    y2: int
    up: str = ""
    down: str = ""
    left: str = ""
    right: str = ""
    group: int = 1
    auto: bool = False
    command: str = ""


@dataclass
class MenuSource:
    scan: Scan
    still: int = 0  # seconds the last frame is held; 255: until a button is pressed


@dataclass
class MenuSpec:
    sources: list[MenuSource]
    entry: str | None = None  # "root", "ptt", "audio", "subtitle" (the remote's keys)
    pre: str = ""
    post: str = ""
    buttons: list[Button] = field(default_factory=list)
    button_colors: bytes = bytes(24)  # select/action colour and contrast, 3 groups (spumux)
    palette: list[int] = field(default_factory=list)


def _w(buf: bytearray, at: int, value: int, size: int = 4) -> None:
    buf[at : at + size] = (value & ((1 << (8 * size)) - 1)).to_bytes(size, "big")


def _relocate(commands: list[bytes], by: int) -> list[bytes]:
    """Goto line numbers moved by `by` (a program placed after other commands)."""
    out = []
    for c in commands:
        if c[0] == 0 and c[1] & 0x0F == 1:  # Goto
            c = c[:7] + bytes([c[7] + by])
        out.append(c)
    return out


def button_commands(menu: MenuSpec) -> tuple[list[bytes], list[bytes]]:
    """(the instruction each button holds in the NAV pack, the PGC's post commands)."""
    single: list[bytes] = []
    programs: list[tuple[int, list[bytes]]] = []
    for k, b in enumerate(menu.buttons, start=1):
        program = compile_program(b.command, "vtsm") if b.command.strip() else []
        if len(program) == 1:
            single.append(program[0])
        else:  # g15 = k, then on to the post commands
            single.append(bytes((0x71, 0x01, 0x00, 0x0F, 0x00, k, 0x00, 0x0D)))
            programs.append((k, program))
    post = compile_program(menu.post, "vtsm") if menu.post.strip() else [EXIT]
    if not programs:
        return single, post
    head = [bytes.fromhex("6100000e000f0000"), bytes.fromhex("7100000f00000000")]  # g14=g15; g15=0
    line = len(head) + len(programs) + len(post) + 1  # where the first button program starts
    table, bodies = [], []
    for k, program in programs:
        table.append(bytes((0x00, 0xA1, 0x00, 0x0E, 0x00, k, 0x00, line)))  # if g14 == k
        bodies += _relocate(program, line - 1)
        line += len(program)
    return single, head + table + post + bodies


def menu_pgc(menu: MenuSpec, vob_ids: list[int], bases: list[int], pal: bool, wide: bool,
             audio_streams: int, subpicture_streams: int) -> bytes:  # fmt: skip
    """One menu PGC; each source VOB is one cell (and program)."""
    buf = bytearray(0xEC)
    n = len(menu.sources)
    buf[2] = n
    buf[3] = n
    spans = [s.scan.vobus[-1].end_pts - s.scan.vobus[0].start_pts for s in menu.sources]
    _w(buf, 4, bcd_time(sum(spans), pal))
    for i in range(audio_streams):
        buf[12 + 2 * i] = 0x80 | i
    for i in range(subpicture_streams):
        for m in range(3 if wide else 1):
            buf[28 + 4 * i + m] = i
        buf[28 + 4 * i] |= 0x80
    for i, c in enumerate(menu.palette or [0x108080] * 16):
        _w(buf, 164 + 4 * i, c)
    pre = compile_program(menu.pre, "vtsm") if menu.pre.strip() else []
    if not pre and menu.buttons:
        pre = [bytes.fromhex("5600000004000000")]  # start on button 1
    _single, post = button_commands(menu)
    table = bytearray(8)
    commands = b"".join(pre + post)
    _w(table, 0, len(pre), 2)
    _w(table, 2, len(post), 2)
    _w(table, 6, 8 + len(commands) - 1, 2)
    _w(buf, 0xE4, 0xEC, 2)
    buf += table + commands
    _w(buf, 0xE6, len(buf), 2)
    buf += bytes(range(1, n + 1))
    if len(buf) & 1:
        buf += b"\0"
    _w(buf, 0xE8, len(buf), 2)
    for k, (source, base) in enumerate(zip(menu.sources, bases, strict=True)):
        v = source.scan.vobus
        entry = bytearray(24)
        entry[0] = 2  # each VOB starts its own clock
        entry[2] = source.still
        _w(entry, 4, bcd_time(spans[k], pal))
        _w(entry, 8, base + v[0].sector)
        _w(entry, 16, base + v[-1].sector)
        _w(entry, 20, base + v[-1].last_sector)
        buf += entry
    _w(buf, 0xEA, len(buf), 2)
    for vob_id in vob_ids:
        buf += bytes((0, vob_id, 0, 1))
    return bytes(buf)


def layout(menus: list[MenuSpec]) -> tuple[list[list[int]], list[list[int]], int]:
    """VOB ids and start sectors of every menu's sources in the menu VOB, and its length."""
    ids, bases, vob, sector = [], [], 0, 0
    for m in menus:
        ids.append([])
        bases.append([])
        for s in m.sources:
            vob += 1
            ids[-1].append(vob)
            bases[-1].append(sector)
            sector += s.scan.vobus[-1].last_sector + 1
    return ids, bases, sector


def pgci_ut(menus: list[MenuSpec], pal: bool, wide: bool, audio: int, subs: int) -> bytes:
    """VTSM_PGCI_UT: one language unit holding every menu PGC."""
    ids, bases, _length = layout(menus)
    lu_head = bytearray(8 + 8 * len(menus))
    _w(lu_head, 0, len(menus), 2)
    body = bytearray()
    entries = 0
    for i, m in enumerate(menus):
        if m.entry:
            lu_head[8 + 8 * i] = 0x80 | MENU_CODE[m.entry]
            entries |= 1 << MENU_CODE[m.entry]
        _w(lu_head, 8 + 8 * i + 4, len(lu_head) + len(body))
        body += menu_pgc(m, ids[i], bases[i], pal, wide, audio, subs)
    lu = lu_head + body
    _w(lu, 4, len(lu) - 1)
    ut = bytearray(16)
    _w(ut, 0, 1, 2)
    ut[8:10] = b"en"
    ut[11] = entries & 0xFF
    _w(ut, 12, len(ut))
    ut += lu
    _w(ut, 4, len(ut) - 1)
    return bytes(ut)


def c_adt(menus: list[MenuSpec]) -> bytes:
    ids, bases, _length = layout(menus)
    buf = bytearray(8)
    _w(buf, 0, sum(len(m.sources) for m in menus), 2)
    for m, vob_ids, starts in zip(menus, ids, bases, strict=True):
        for s, vob_id, base in zip(m.sources, vob_ids, starts, strict=True):
            entry = bytearray(12)
            _w(entry, 0, vob_id, 2)
            entry[2] = 1
            _w(entry, 4, base + s.scan.vobus[0].sector)
            _w(entry, 8, base + s.scan.vobus[-1].last_sector)
            buf += entry
    _w(buf, 4, len(buf) - 1)
    return bytes(buf)


def vobu_admap(menus: list[MenuSpec]) -> bytes:
    _ids, bases, _length = layout(menus)
    sectors = []
    for m, starts in zip(menus, bases, strict=True):
        for s, base in zip(m.sources, starts, strict=True):
            sectors += [base + v.sector for v in s.scan.vobus]
    buf = bytearray(4)
    _w(buf, 0, 4 * len(sectors) + 3)
    for s in sectors:
        buf += s.to_bytes(4, "big")
    return bytes(buf)


def _index(buttons: list[Button], name: str, fallback: int) -> int:
    return next((k for k, b in enumerate(buttons, start=1) if b.name == name), fallback)


def button_info(buf: bytearray, menu: MenuSpec, start_pts: int, wide: bool) -> None:
    """Highlight information and the button table in a NAV pack's PCI (buf: the pack)."""
    buttons = menu.buttons
    if not buttons:
        return
    single, _post = button_commands(menu)
    groups = [1, 2] if wide else [0]  # display modes with their own button table
    _w(buf, 0x8D, 1, 2)  # all new highlight information for this VOBU
    _w(buf, 0x8F, start_pts)
    _w(buf, 0x93, 0xFFFFFFFF)
    _w(buf, 0x97, 0xFFFFFFFF)
    mode = 0
    for n, j in enumerate(groups):
        mode += 0x1000 + (((1 << j) >> 1) << ((2 - n) * 4))
    _w(buf, 0x9B, mode, 2)
    buf[0x9E] = len(buttons)
    buf[0x9F] = len(buttons)
    buf[0xA3 : 0xA3 + 24] = menu.button_colors[:24]
    count = len(buttons)
    for n in range(len(groups)):
        at = 0xBB + 18 * (n * MAX_BUTTONS // len(groups))
        for k, b in enumerate(buttons):
            e = bytearray(18)
            e[0] = (b.group << 6) | (b.x1 >> 4)
            e[1] = ((b.x1 << 4) & 0xF0) | (b.x2 >> 8)
            e[2] = b.x2 & 0xFF
            e[3] = (0x40 if b.auto else 0) | (b.y1 >> 4)
            e[4] = ((b.y1 << 4) & 0xF0) | (b.y2 >> 8)
            e[5] = b.y2 & 0xFF
            e[6] = _index(buttons, b.up, count if k == 0 else k)
            e[7] = _index(buttons, b.down, 1 if k + 1 == count else k + 2)
            e[8] = _index(buttons, b.left, count if k == 0 else k)
            e[9] = _index(buttons, b.right, 1 if k + 1 == count else k + 2)
            e[10:18] = single[k]
            buf[at : at + 18] = e
            at += 18
