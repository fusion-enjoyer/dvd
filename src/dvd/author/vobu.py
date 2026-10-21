"""Scan a DVD program stream into its VOBUs (video object units), for the authoring tables.

A VOBU starts with a NAV pack (system header, then the PCI and DSI private stream 2 packets)
and runs to the next one. The IFO tables and the NAV packs themselves need, per VOBU: where
it starts (in 2048-byte sectors), its presentation time span, and the sectors where its first
three reference pictures (I and P frames) end, which players use for fast forward. All of
that is read from pack, PES and MPEG-2 picture headers; nothing is decoded.
"""

from __future__ import annotations

import mmap
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path

PACK = 2048
PICTURE = b"\x00\x00\x01\x00"


@dataclass
class Vobu:
    sector: int  # first sector (the NAV pack), as authored (no padding-only packs)
    scr: int  # system clock of the NAV pack, 90 kHz
    last_sector: int = 0
    start_pts: int | None = None  # first video picture shown (90 kHz)
    end_pts: int | None = None  # the moment after the last picture shown
    ref_ends: list[int] = field(default_factory=list)  # first 3 I/P pictures: end sector, relative
    pictures: int = 0


def _ts(b: bytes) -> int:
    return (((b[0] >> 1) & 7) << 30) | (b[1] << 22) | ((b[2] >> 1) << 15) | (b[3] << 7) \
        | (b[4] >> 1)  # fmt: skip


def _scr(b: bytes) -> int:
    return (
        (((b[0] >> 3) & 7) << 30) | ((b[0] & 3) << 28) | (b[1] << 20)
        | ((b[2] >> 3) << 15) | ((b[2] & 3) << 13) | (b[3] << 5) | (b[4] >> 3)
    )  # fmt: skip


def scan(path: Path, fps: Fraction) -> list[Vobu]:
    """Every VOBU of a program stream. `fps`: the video's frame rate (for the end times)."""
    frame = round(90000 / fps)
    vobus: list[Vobu] = []
    tail = b""  # the last bytes of video payload, for start codes split over packets
    open_ref: tuple[Vobu, int] | None = None  # a reference picture still being read
    pts_seen: list[int] = []
    with Path(path).open("rb") as f, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as data:
        packs = len(data) // PACK
        sector = -1  # counted as the disc will hold them: pure padding packs are dropped
        last = 0
        for index in range(packs):
            pack = data[index * PACK : (index + 1) * PACK]
            if pack[:4] != b"\x00\x00\x01\xba":
                continue
            pos = 14 + (pack[13] & 7)
            if pack[pos : pos + 4] == b"\x00\x00\x01\xbe":
                continue  # only padding: authoring leaves it out (dvdauthor does too)
            sector += 1
            last = sector
            scr = _scr(pack[4:9])
            while pos + 6 <= PACK and pack[pos : pos + 3] == b"\x00\x00\x01":
                sid = pack[pos + 3]
                length = int.from_bytes(pack[pos + 4 : pos + 6], "big")
                body = pack[pos + 6 : pos + 6 + length]
                if sid == 0xBB and (not vobus or vobus[-1].sector != sector):  # NAV pack
                    if vobus:
                        _close(vobus[-1], sector - 1, pts_seen, frame)
                    vobus.append(Vobu(sector, scr))
                    pts_seen = []
                    open_ref = None
                elif 0xE0 <= sid <= 0xEF and vobus:
                    header = 3 + body[2]
                    if body[1] & 0x80 and len(body) >= 8:
                        pts_seen.append(_ts(body[3:8]))
                    payload = body[header:]
                    joined = tail + payload
                    at = joined.find(PICTURE)
                    while at != -1 and at + 6 <= len(joined):
                        kind = (joined[at + 5] >> 3) & 7  # 1 I, 2 P, 3 B
                        vobu = vobus[-1]
                        if open_ref is not None and open_ref[0] is vobu:
                            # Bytes before this start code in this packet still belong to
                            # the reference picture, so it ends in this pack.
                            here = sector - vobu.sector if at > len(tail) else open_ref[1]
                            vobu.ref_ends.append(here)
                            open_ref = None
                        vobu.pictures += 1
                        if kind in (1, 2) and len(vobu.ref_ends) < 3:
                            open_ref = (vobu, 0)
                        at = joined.find(PICTURE, at + 4)
                    tail = joined[-3:]
                    if open_ref is not None:  # the picture runs at least to this pack
                        open_ref = (open_ref[0], sector - open_ref[0].sector)
                pos += 6 + length
        if vobus:
            _close(vobus[-1], last, pts_seen, frame)
            if open_ref is not None and open_ref[0] is vobus[-1]:
                vobus[-1].ref_ends.append(open_ref[1])
    # A unit ends where the next begins (with pulldown a picture lasts 2 or 3 fields, so
    # "last picture + one frame" is only right for the very last unit).
    for a, b in zip(vobus, vobus[1:], strict=False):
        if b.start_pts is not None:
            a.end_pts = b.start_pts
    return vobus


def _close(vobu: Vobu, last: int, pts: list[int], frame: int) -> None:
    vobu.last_sector = last
    if pts:
        vobu.start_pts = min(pts)
        vobu.end_pts = max(pts) + frame


@dataclass
class Dsi:
    """The fields of a NAV pack's DSI we write and check (sectors relative to the pack)."""

    lbn: int  # the NAV pack's own sector in the VOB set
    end: int  # last sector of the VOBU
    refs: tuple[int, int, int]  # end of the 1st, 2nd and 3rd reference picture
    start_ptm: int
    end_ptm: int


def read_dsi(path: Path) -> list[Dsi]:
    """DSI of every NAV pack in a VOB (as written by an authoring tool)."""
    out = []
    data = Path(path).read_bytes()
    for sector in range(len(data) // PACK):
        pack = data[sector * PACK : (sector + 1) * PACK]
        if pack[:4] != b"\x00\x00\x01\xba":
            continue
        pos = 14 + (pack[13] & 7)
        while pos + 6 <= PACK and pack[pos : pos + 3] == b"\x00\x00\x01":
            sid = pack[pos + 3]
            length = int.from_bytes(pack[pos + 4 : pos + 6], "big")
            body = pack[pos + 6 : pos + 6 + length]
            if sid == 0xBF and body[:1] == b"\x01":  # DSI
                v = [int.from_bytes(body[1 + o : 5 + o], "big") for o in range(0, 24, 4)]
                out.append(Dsi(v[1], v[2], (v[3], v[4], v[5]), 0, 0))
            pos += 6 + length
    return out
