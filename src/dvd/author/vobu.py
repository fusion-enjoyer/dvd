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
    seq_end: bool = False  # holds the sequence end code (the last unit of a video)
    fields: int = 0  # fields shown: 2 per frame picture, 3 with repeat_first_field (pulldown)


@dataclass
class Scan:
    vobus: list[Vobu]
    # Per audio stream (0-7): (sector, pts) of each packet that starts a frame (has a PTS).
    audio: dict[int, list[tuple[int, int]]] = field(default_factory=dict)
    # Per subpicture stream (0-31): (sector, shown from, shown until) of each subpicture.
    subpictures: dict[int, list[tuple[int, int, int]]] = field(default_factory=dict)


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
    return scan_stream(path, fps).vobus


def _audio_stream(sid: int, body: bytes) -> tuple[str, int] | None:
    if 0xC0 <= sid <= 0xC7:
        return "audio", sid - 0xC0
    if sid == 0xBD and len(body) > 3 + body[2]:
        sub = body[3 + body[2]]
        if 0x80 <= sub <= 0x8F or 0xA0 <= sub <= 0xA7:  # AC-3, DTS, LPCM
            return "audio", sub & 0x07
        if 0x20 <= sub <= 0x3F:
            return "subpicture", sub - 0x20
    return None


def scan_stream(path: Path, fps: Fraction) -> Scan:
    """The VOBUs of a program stream and where its audio and subpicture packets are."""
    frame = round(90000 / fps)
    # Ticks per frame of the displayed rate: film on NTSC is shown at 29.97 with pulldown.
    frame_ticks = 3003 if fps in (Fraction(24000, 1001), Fraction(30000, 1001)) else frame
    vobus: list[Vobu] = []
    result = Scan(vobus)
    video = bytearray()  # the current VOBU's video payload, for its picture extensions
    units: dict[int, list] = {}  # subpicture units being collected: [sector, pts, data]
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
                        _close(vobus[-1], sector - 1, pts_seen, frame, video)
                    video = bytearray()
                    vobus.append(Vobu(sector, scr))
                    pts_seen = []
                    open_ref = None
                elif (kind := _audio_stream(sid, body)) is not None:
                    has_pts = body[1] & 0x80 and len(body) >= 8
                    if kind[0] == "audio":
                        if has_pts:
                            result.audio.setdefault(kind[1], []).append((sector, _ts(body[3:8])))
                    else:
                        _subpicture(result, units, kind[1], sector, body, has_pts)
                elif 0xE0 <= sid <= 0xEF and vobus:
                    header = 3 + body[2]
                    if body[1] & 0x80 and len(body) >= 8:
                        pts_seen.append(_ts(body[3:8]))
                    payload = body[header:]
                    video += payload
                    joined = tail + payload
                    if b"\x00\x00\x01\xb7" in joined:
                        vobus[-1].seq_end = True
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
            _close(vobus[-1], last, pts_seen, frame, video)
            if open_ref is not None and open_ref[0] is vobus[-1]:
                vobus[-1].ref_ends.append(open_ref[1])
    # A unit ends where the next begins (with pulldown a picture lasts 2 or 3 fields, so
    # "last picture + one frame" is only right for the very last unit).
    for a, b in zip(vobus, vobus[1:], strict=False):
        if b.start_pts is not None:
            a.end_pts = b.start_pts
    for v in vobus:  # counted fields give the exact end (also for the last unit)
        if v.start_pts is not None and v.fields:
            v.end_pts = (2 * v.start_pts + v.fields * frame_ticks) // 2
    return result


def _subpicture(result: Scan, units: dict, stream: int, sector: int, body: bytes,
                has_pts: bool) -> None:  # fmt: skip
    """Collect a subpicture unit over its packets; when complete, note when it shows."""
    from dvd.subs.vobsub import parse_spu

    payload = body[3 + body[2] + 1 :]  # after the substream byte
    if has_pts:
        units[stream] = [sector, _ts(body[3:8]), bytearray()]
    unit = units.get(stream)
    if unit is None:
        return
    unit[2] += payload
    if len(unit[2]) >= 2 and len(unit[2]) >= int.from_bytes(unit[2][:2], "big"):
        spu = parse_spu(bytes(unit[2]))
        start = unit[1] + round((spu.start if spu else 0) * 90000)
        end = unit[1] + round(spu.end * 90000) if spu and spu.end is not None else start
        result.subpictures.setdefault(stream, []).append((unit[0], start, end))
        del units[stream]


def _fields(video: bytes) -> int:
    """Fields shown by the pictures in this stretch of MPEG-2 video (picture coding
    extensions: a frame picture shows 2 fields, 3 with repeat_first_field; a field picture 1)."""
    total, at = 0, video.find(b"\x00\x00\x01\xb5")
    while at != -1 and at + 8 <= len(video):
        if video[at + 4] >> 4 == 8:  # picture coding extension
            structure = video[at + 6] & 3
            total += (3 if video[at + 7] & 0x02 else 2) if structure == 3 else 1
        at = video.find(b"\x00\x00\x01\xb5", at + 4)
    return total


def _close(vobu: Vobu, last: int, pts: list[int], frame: int, video: bytes = b"") -> None:
    vobu.last_sector = last
    vobu.fields = _fields(video)
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
