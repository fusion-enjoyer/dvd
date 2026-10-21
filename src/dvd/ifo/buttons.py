"""A menu's buttons, read from the NAV pack that starts the menu (the PCI's highlight
information): where each button sits, where the arrow keys lead and what it does."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from dvd.ifo.reader import Pgc

PACK = 2048
TABLE = 0xBB  # first button entry in the pack, 18 bytes each


@dataclass
class Button:
    number: int  # from 1
    rect: tuple[int, int, int, int]  # x1, y1, x2, y2 on the menu picture
    up: int
    down: int
    left: int
    right: int
    auto: bool  # acts as soon as it is selected
    command: bytes


def menu_vob(video_ts: Path, titleset: int) -> Path:
    """The VOB holding a titleset's menus (0: the disc's own menus)."""
    return video_ts / ("VIDEO_TS.VOB" if titleset == 0 else f"VTS_{titleset:02}_0.VOB")


def menu_buttons(video_ts: Path, titleset: int, menu: Pgc) -> list[Button]:
    """The buttons of `menu` (a menu PGC of titleset `titleset`, 0: the disc's menus), as
    the first NAV pack of its first cell gives them; empty if it has none."""
    path = menu_vob(video_ts, titleset)
    if not menu.cells or not path.is_file():
        return []
    with path.open("rb") as f:
        f.seek(menu.cells[0].first_sector * PACK)
        pack = f.read(PACK)
    if len(pack) < PACK or pack[0x26:0x2A] != b"\x00\x00\x01\xbf" or pack[0x2C] != 0:
        return []
    count = min(pack[0x9E], 36)
    out = []
    for k in range(count):
        e = pack[TABLE + 18 * k : TABLE + 18 * (k + 1)]
        x1 = ((e[0] & 0x3F) << 4) | (e[1] >> 4)
        x2 = ((e[1] & 0x03) << 8) | e[2]
        y1 = ((e[3] & 0x3F) << 4) | (e[4] >> 4)
        y2 = ((e[4] & 0x03) << 8) | e[5]
        out.append(Button(k + 1, (x1, y1, x2, y2), e[6] & 0x3F, e[7] & 0x3F, e[8] & 0x3F,
                          e[9] & 0x3F, bool(e[3] & 0x40), bytes(e[10:18])))  # fmt: skip
    return out
