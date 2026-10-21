"""Remote-control restrictions (user operation prohibitions, UOPs) written into the IFO files.

dvdauthor cannot set them, so they are patched in after authoring. Each program chain (PGC)
has a 32-bit mask at byte 8 of the PGC; a set bit forbids that operation while the PGC plays.
The titles of a titleset are the PGCs listed in its VTS_PGCITI table (pointer at 0xCC of
VTS_nn_0.IFO, in sectors); the backup .BUP file gets the same change.
"""

from __future__ import annotations

from pathlib import Path

SECTOR = 2048

# Bit numbers of the UOP mask (bit 0 is the lowest bit of the big-endian 32-bit value).
UOP_BITS = {
    "title_or_time_play": 0,
    "chapter_search_or_play": 1,
    "title_play": 2,
    "stop": 3,
    "go_up": 4,
    "time_or_chapter_search": 5,
    "prev_or_top_pg_search": 6,
    "next_pg_search": 7,
    "forward_scan": 8,
    "backward_scan": 9,
    "title_menu_call": 10,
    "root_menu_call": 11,
    "subpic_menu_call": 12,
    "audio_menu_call": 13,
    "angle_menu_call": 14,
    "chapter_menu_call": 15,
    "resume": 16,
    "button_select_or_activate": 17,
    "still_off": 18,
    "pause_on": 19,
    "audio_stream_change": 20,
    "subpic_stream_change": 21,
    "angle_change": 22,
    "karaoke_audio_pres_mode_change": 23,
    "video_pres_mode_change": 24,
}

# An unskippable clip (a warning, a studio logo): no jumping ahead, no fast forward, no
# menus; pause, stop, rewind and the language keys still work.
NO_SKIP = sum(1 << UOP_BITS[name] for name in (
    "title_or_time_play", "chapter_search_or_play", "title_play", "time_or_chapter_search",
    "next_pg_search", "forward_scan", "title_menu_call", "root_menu_call",
    "subpic_menu_call", "audio_menu_call", "angle_menu_call", "chapter_menu_call",
))  # fmt: skip


class UopError(ValueError):
    pass


def title_pgcs(ifo: bytes) -> list[int]:
    """Byte offsets of the title PGCs of a VTS IFO, in table order."""
    if ifo[:12] != b"DVDVIDEO-VTS":
        raise UopError("not a titleset IFO (VTS_nn_0.IFO)")
    table = int.from_bytes(ifo[0xCC:0xD0], "big") * SECTOR
    if not 0 < table < len(ifo):
        raise UopError("the IFO has no title PGC table")
    count = int.from_bytes(ifo[table : table + 2], "big")
    out = []
    for i in range(count):
        entry = table + 8 + 8 * i
        out.append(table + int.from_bytes(ifo[entry + 4 : entry + 8], "big"))
    return out


def read_masks(path: Path) -> list[int]:
    data = path.read_bytes()
    return [int.from_bytes(data[o + 8 : o + 12], "big") for o in title_pgcs(data)]


def restrict(video_ts: Path, vts: int, masks: dict[int, int]) -> None:
    """Add `masks` (PGC number from 1 -> UOP bits) to titleset `vts`, in the IFO and BUP."""
    for suffix in ("IFO", "BUP"):
        path = video_ts / f"VTS_{vts:02}_0.{suffix}"
        data = bytearray(path.read_bytes())
        offsets = title_pgcs(bytes(data))
        for number, mask in masks.items():
            if not 1 <= number <= len(offsets):
                raise UopError(f"{path.name} has no title PGC {number}")
            at = offsets[number - 1] + 8
            old = int.from_bytes(data[at : at + 4], "big")
            data[at : at + 4] = (old | mask).to_bytes(4, "big")
        path.write_bytes(bytes(data))
