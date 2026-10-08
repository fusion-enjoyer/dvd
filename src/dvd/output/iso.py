"""DVD-Video disc image writer: UDF 1.02 + ISO 9660 bridge (decision K10).

DVD players read the UDF file system; some older ones read ISO 9660, so both describe the same
files. The IFO files store sector offsets of their VOBs relative to themselves, so files are laid
out exactly where the IFOs say: VIDEO_TS.IFO, VIDEO_TS.VOB, VIDEO_TS.BUP, then for each title set
VTS_nn_0.IFO, VTS_nn_0.VOB, VTS_nn_1..9.VOB, VTS_nn_0.BUP, contiguously.

References: ECMA-167 (UDF base), OSTA UDF 1.02, ECMA-119 (ISO 9660), DVD-Video IFO layout.
"""

from __future__ import annotations

import re
import struct
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

SECTOR = 2048
AVDP_SECTOR = 256
MAIN_VDS, RESERVE_VDS, LVID_SECTOR = 32, 48, 64
ISO_META_START = 66  # path tables and ISO directories, below the AVDP at 256
PARTITION_START = 257
MAX_EXTENT = 0x3FFFF800  # largest whole-sector length a 30-bit extent field holds
UDF_REVISION = 0x0102
IMPLEMENTATION = b"*dvd authoring tool"

Progress = Callable[[float], None]


class IsoError(Exception):
    pass


# ---------------------------------------------------------------- DVD-Video file layout


@dataclass
class DiscFile:
    name: str
    path: Path | None  # None for empty files
    size: int
    offset: int = 0  # sector relative to VIDEO_TS.IFO

    @property
    def sectors(self) -> int:
        return (self.size + SECTOR - 1) // SECTOR


def _u32(data: bytes, offset: int) -> int:
    return struct.unpack_from(">I", data, offset)[0]


def _read_ifo(path: Path) -> bytes:
    data = path.read_bytes()
    if len(data) < SECTOR or data[:12] not in (b"DVDVIDEO-VMG", b"DVDVIDEO-VTS"):
        raise IsoError(f"{path.name} is not a DVD-Video IFO file")
    return data


def _place_set(
    folder: Path, prefix: str, start: int, menu: str, titles: list[str]
) -> tuple[list[DiscFile], int]:
    """Place one IFO set (VMG or a VTS) starting at `start`; return files and set length."""
    ifo_path = folder / f"{prefix}.IFO"
    ifo = _read_ifo(ifo_path)
    set_last, ifo_last = _u32(ifo, 0x0C), _u32(ifo, 0x1C)
    menu_start = _u32(ifo, 0xC0)
    files = [DiscFile(ifo_path.name, ifo_path, ifo_path.stat().st_size, start)]
    menu_path = folder / menu
    if menu_start:
        if not menu_path.is_file():
            raise IsoError(f"{ifo_path.name} refers to {menu}, which is missing")
        files.append(DiscFile(menu, menu_path, menu_path.stat().st_size, start + menu_start))
    if titles:
        sector = start + _u32(ifo, 0xC4)
        for name in titles:
            p = folder / name
            files.append(DiscFile(name, p, p.stat().st_size, sector))
            sector += files[-1].sectors
    bup = folder / f"{prefix}.BUP"
    if not bup.is_file():
        raise IsoError(f"{bup.name} is missing")
    files.append(DiscFile(bup.name, bup, bup.stat().st_size, start + set_last - ifo_last))
    for a, b in zip(files, files[1:], strict=False):
        if a.offset + a.sectors > b.offset:
            raise IsoError(f"{a.name} overlaps {b.name}; the IFO does not match the files")
    if files[-1].offset + files[-1].sectors != start + set_last + 1:
        raise IsoError(f"{bup.name} does not end where {ifo_path.name} says the set ends")
    return files, set_last + 1


def dvd_layout(video_ts: Path) -> list[DiscFile]:
    """All VIDEO_TS files with their sector offsets relative to VIDEO_TS.IFO."""
    files, length = _place_set(video_ts, "VIDEO_TS", 0, "VIDEO_TS.VOB", [])
    vmg = _read_ifo(video_ts / "VIDEO_TS.IFO")
    srpt = vmg[_u32(vmg, 0xC4) * SECTOR :]
    titles = struct.unpack_from(">H", srpt, 0)[0]
    starts = {srpt[8 + 12 * i + 6]: _u32(srpt, 8 + 12 * i + 8) for i in range(titles)}

    vts_numbers = sorted(
        int(m.group(1))
        for p in video_ts.iterdir()
        if (m := re.fullmatch(r"VTS_(\d\d)_0\.IFO", p.name.upper()))
    )
    offset = length
    for n in vts_numbers:
        if starts.get(n, offset) != offset:
            raise IsoError(
                f"title set {n} should start at sector {starts[n]}, layout gives {offset}"
            )
        prefix = f"VTS_{n:02}_0"
        vobs = sorted(
            p.name for p in video_ts.iterdir() if re.fullmatch(rf"VTS_{n:02}_[1-9]\.VOB", p.name)
        )
        set_files, length = _place_set(video_ts, prefix, offset, f"VTS_{n:02}_0.VOB", vobs)
        files += set_files
        offset += length
    known = {f.name for f in files}
    stray = [p.name for p in video_ts.iterdir() if p.is_file() and p.name not in known]
    if stray:
        raise IsoError(f"unexpected files in VIDEO_TS: {', '.join(sorted(stray))}")
    return files


# ---------------------------------------------------------------- UDF primitives

_CRC_TABLE = []
for _i in range(256):
    _c = _i << 8
    for _ in range(8):
        _c = ((_c << 1) ^ 0x1021) if _c & 0x8000 else _c << 1
    _CRC_TABLE.append(_c & 0xFFFF)


def crc_ccitt(data: bytes) -> int:
    crc = 0
    for b in data:
        crc = ((crc << 8) & 0xFFFF) ^ _CRC_TABLE[((crc >> 8) ^ b) & 0xFF]
    return crc


def tag(identifier: int, location: int, body: bytes, serial: int = 1) -> bytes:
    """Descriptor tag (16 bytes) followed by the body; CRC covers the whole body."""
    head = struct.pack(
        "<HHBBHHHI", identifier, 2, 0, 0, serial, crc_ccitt(body), len(body), location
    )
    checksum = (sum(head[0:4]) + sum(head[5:16])) & 0xFF
    return head[:4] + bytes([checksum]) + head[5:] + body


def charspec() -> bytes:
    return b"\x00" + b"OSTA Compressed Unicode".ljust(63, b"\x00")


def regid(identifier: bytes, suffix: bytes = b"") -> bytes:
    return b"\x00" + identifier.ljust(23, b"\x00") + suffix.ljust(8, b"\x00")


def domain_id() -> bytes:
    return regid(b"*OSTA UDF Compliant", struct.pack("<HB", UDF_REVISION, 0))


def impl_id() -> bytes:
    return regid(IMPLEMENTATION)


def dstring(text: str, length: int) -> bytes:
    if not text:
        return bytes(length)
    data = b"\x08" + text.encode("latin-1")[: length - 2]
    return data.ljust(length - 1, b"\x00") + bytes([len(data)])


def timestamp(t: datetime) -> bytes:
    offset = int(t.utcoffset().total_seconds() // 60) if t.utcoffset() else 0
    return struct.pack(
        "<HhBBBBBBBB",
        (1 << 12) | (offset & 0xFFF),
        t.year, t.month, t.day, t.hour, t.minute, t.second,
        t.microsecond // 10000, t.microsecond // 100 % 100, t.microsecond % 100,
    )  # fmt: skip


def extent_ad(length: int, location: int) -> bytes:
    return struct.pack("<II", length, location)


def long_ad(length: int, block: int) -> bytes:
    return struct.pack("<IIH", length, block, 0) + bytes(6)


def short_ads(length: int, block: int) -> bytes:
    out = b""
    while length > 0:
        part = min(length, MAX_EXTENT)
        out += struct.pack("<II", part, block)
        length -= part
        block += part // SECTOR
    return out


def pad_sector(data: bytes) -> bytes:
    return data + bytes(-len(data) % SECTOR)


# ---------------------------------------------------------------- ISO 9660 primitives


def both16(v: int) -> bytes:
    return struct.pack("<H", v) + struct.pack(">H", v)


def both32(v: int) -> bytes:
    return struct.pack("<I", v) + struct.pack(">I", v)


def iso_date7(t: datetime) -> bytes:
    offset = int(t.utcoffset().total_seconds() // 900) if t.utcoffset() else 0
    return bytes([t.year - 1900, t.month, t.day, t.hour, t.minute, t.second, offset & 0xFF])


def iso_date17(t: datetime) -> bytes:
    offset = int(t.utcoffset().total_seconds() // 900) if t.utcoffset() else 0
    return t.strftime("%Y%m%d%H%M%S00").encode() + bytes([offset & 0xFF])


def dir_record(name: bytes, sector: int, size: int, is_dir: bool, t: datetime) -> bytes:
    body = (
        b"\x00" + both32(sector) + both32(size) + iso_date7(t)
        + bytes([0x02 if is_dir else 0, 0, 0]) + both16(1) + bytes([len(name)]) + name
    )  # fmt: skip
    pad = b"\x00" if (len(body) + 1) % 2 else b""
    return bytes([len(body) + 1 + len(pad)]) + body + pad


def volume_label(name: str) -> str:
    """ISO 9660 d-characters: A-Z, 0-9 and _; Turkish letters lose their marks."""
    text = name.translate(str.maketrans("ıİ", "iI"))
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().upper()
    text = re.sub(r"[^A-Z0-9]+", "_", text).strip("_")
    return text[:32] or "DVD_VIDEO"


# ---------------------------------------------------------------- image builder


@dataclass
class _Dir:
    name: str
    files: list[DiscFile] = field(default_factory=list)
    fe_block: int = 0
    data_block: int = 0
    fids: bytes = b""
    iso_sector: int = 0
    iso_size: int = 0


class _Image:
    def __init__(self, video_ts: Path, label: str, when: datetime) -> None:
        self.when = when
        self.label = volume_label(label)
        self.files = dvd_layout(video_ts)
        self.root = _Dir("")
        self.audio_ts = _Dir("AUDIO_TS")
        self.video_ts = _Dir("VIDEO_TS", sorted(self.files, key=lambda f: f.offset))
        self.dirs = [self.root, self.audio_ts, self.video_ts]
        self.sectors: dict[int, bytes] = {}
        self._layout()

    # Partition: 0 FSD, 1 TD, then directory FEs and FID data, then file FEs, then data.
    def _layout(self) -> None:
        # FID sizes do not depend on block numbers: build once to measure, again to place.
        self.file_fe: dict[str, int] = {}
        for d in self.dirs:
            d.fids = self._fids(d)
        block = 2
        for d in self.dirs:
            d.fe_block = block
            d.data_block = block + 1
            block += 1 + max(1, (len(d.fids) + SECTOR - 1) // SECTOR)
        for f in self.video_ts.files:
            self.file_fe[f.name] = block
            block += 1
        for d in self.dirs:
            d.fids = self._fids(d)
        self.data_block = block
        self.data_sector = PARTITION_START + block
        last = self.video_ts.files[-1]
        data_end = self.data_sector + last.offset + last.sectors
        self.partition_length = data_end - PARTITION_START
        self.total_sectors = data_end + 1  # last sector holds the second anchor
        sector = ISO_META_START + 2  # after the two path tables
        for d in (self.root, self.audio_ts, self.video_ts):
            d.iso_sector = sector
            d.iso_size = self._iso_dir_size(d)
            sector += d.iso_size // SECTOR
        if sector > AVDP_SECTOR:
            raise IsoError("too many files for the ISO 9660 directory area")

    def _fid(self, block: int, name: str, fe_block: int, is_dir: bool, parent: bool) -> bytes:
        ident = b"" if parent else b"\x08" + name.encode("ascii")
        chars = (0x02 if is_dir else 0) | (0x08 if parent else 0)
        body = struct.pack("<HBB", 1, chars, len(ident)) + long_ad(SECTOR, fe_block)
        body += struct.pack("<H", 0) + ident
        body += bytes(-(16 + len(body)) % 4)
        return tag(257, block, body)

    def _fids(self, d: _Dir) -> bytes:
        parent = self.root
        entries = [(parent.fe_block, "", True, True)]
        if d is self.root:
            entries += [(self.audio_ts.fe_block, "AUDIO_TS", True, False),
                        (self.video_ts.fe_block, "VIDEO_TS", True, False)]  # fmt: skip
        for f in d.files:
            entries.append((self.file_fe.get(f.name, 0), f.name, False, False))
        out = b""
        for fe, name, is_dir, is_parent in entries:
            # The tag location is the block holding the start of the descriptor.
            out += self._fid(d.data_block + len(out) // SECTOR, name, fe, is_dir, is_parent)
        return out

    def _file_entry(self, block: int, is_dir: bool, size: int, data_block: int, uid: int,
                    links: int) -> bytes:  # fmt: skip
        ads = short_ads(size, data_block) if size else b""
        icb = struct.pack("<IHHHBB", 0, 4, 0, 1, 0, 4 if is_dir else 5) + bytes(6)
        icb += struct.pack("<H", 0)  # short allocation descriptors
        permissions = 0x2529 if is_dir else 0x2108  # r-x / r-- for everyone
        t = timestamp(self.when)
        body = (
            icb + struct.pack("<IIIHBBI", 0xFFFFFFFF, 0xFFFFFFFF, permissions, links, 0, 0, 0)
            + struct.pack("<QQ", size, (size + SECTOR - 1) // SECTOR)
            + t + t + t + struct.pack("<I", 1) + long_ad(0, 0) + impl_id()
            + struct.pack("<QII", uid, 0, len(ads)) + ads
        )  # fmt: skip
        return tag(261, block, body)

    def _iso_dir_size(self, d: _Dir) -> int:
        size, used = SECTOR, 0
        for rec in self._iso_records(d):
            if used + len(rec) > SECTOR:
                size, used = size + SECTOR, 0
            used += len(rec)
        return size

    def _iso_records(self, d: _Dir) -> list[bytes]:
        t = self.when
        recs = [
            dir_record(b"\x00", d.iso_sector, d.iso_size, True, t),
            dir_record(b"\x01", self.root.iso_sector, self.root.iso_size, True, t),
        ]
        if d is self.root:
            for sub in (self.audio_ts, self.video_ts):  # already in name order
                recs.append(dir_record(sub.name.encode(), sub.iso_sector, sub.iso_size, True, t))
        for f in sorted(d.files, key=lambda f: f.name):
            sector = self.data_sector + f.offset if f.size else 0
            recs.append(dir_record(f"{f.name};1".encode(), sector, f.size, False, t))
        return recs

    def _iso_dir_data(self, d: _Dir) -> bytes:
        out, block = b"", b""
        for rec in self._iso_records(d):
            if len(block) + len(rec) > SECTOR:
                out += pad_sector(block)
                block = b""
            block += rec
        return out + pad_sector(block)

    def _put(self, sector: int, data: bytes) -> None:
        for i in range(0, len(pad_sector(data)), SECTOR):
            self.sectors[sector + i // SECTOR] = pad_sector(data)[i : i + SECTOR]

    def _volume_descriptors(self) -> list[tuple[int, bytes]]:
        """Bodies of the UDF volume descriptors, in sequence order (ECMA-167 part 3)."""
        t, label = self.when, self.label
        volset = f"{int(t.timestamp()):08X}{label}"[:30]  # first 16 chars must be unique
        primary = (
            struct.pack("<II", 0, 0) + dstring(label, 32)
            + struct.pack("<HHHHII", 1, 1, 2, 2, 1, 1) + dstring(volset, 128)
            + charspec() + charspec() + extent_ad(0, 0) + extent_ad(0, 0)
            + regid(b"") + timestamp(t) + impl_id() + bytes(64)
            + struct.pack("<IH", 0, 0) + bytes(22)
        )  # fmt: skip
        implementation_use = (
            struct.pack("<I", 1) + regid(b"*UDF LV Info", struct.pack("<H", UDF_REVISION))
            + charspec() + dstring(label, 128) + bytes(36 * 3) + impl_id() + bytes(128)
        )  # fmt: skip
        partition = (
            struct.pack("<IHH", 2, 1, 0) + regid(b"+NSR02") + bytes(128)
            + struct.pack("<III", 1, PARTITION_START, self.partition_length)  # read-only
            + impl_id() + bytes(128) + bytes(156)
        )  # fmt: skip
        logical_volume = (
            struct.pack("<I", 3) + charspec() + dstring(label, 128)
            + struct.pack("<I", SECTOR) + domain_id() + long_ad(SECTOR, 0)  # file set at block 0
            + struct.pack("<II", 6, 1) + impl_id() + bytes(128)
            + extent_ad(2 * SECTOR, LVID_SECTOR)
            + struct.pack("<BBHH", 1, 6, 1, 0)  # type 1 partition map
        )  # fmt: skip
        unallocated = struct.pack("<II", 4, 0)
        return [
            (1, primary),
            (4, implementation_use),
            (5, partition),
            (6, logical_volume),
            (7, unallocated),
            (8, bytes(496)),
        ]

    def build_metadata(self) -> None:
        t = self.when
        # ISO 9660 path tables
        path_entries = [(b"\x00", self.root.iso_sector)] + [
            (d.name.encode(), d.iso_sector) for d in (self.audio_ts, self.video_ts)
        ]
        l_table = m_table = b""
        for name, sector in path_entries:
            pad = b"\x00" if len(name) % 2 else b""
            l_table += bytes([len(name), 0]) + struct.pack("<IH", sector, 1) + name + pad
            m_table += bytes([len(name), 0]) + struct.pack(">IH", sector, 1) + name + pad
        self._put(ISO_META_START, l_table)
        self._put(ISO_META_START + 1, m_table)
        for d in self.dirs:
            self._put(d.iso_sector, self._iso_dir_data(d))

        label = self.label.encode()
        root_rec = dir_record(b"\x00", self.root.iso_sector, self.root.iso_size, True, t)
        pvd = (
            b"\x01CD001\x01\x00" + b" " * 32 + label.ljust(32, b" ") + bytes(8)
            + both32(self.total_sectors) + bytes(32) + both16(1) + both16(1) + both16(SECTOR)
            + both32(len(l_table)) + struct.pack("<II", ISO_META_START, 0)
            + struct.pack(">II", ISO_META_START + 1, 0) + root_rec
            + b" " * 128 + b" " * 128 + b" " * 128 + IMPLEMENTATION[1:].upper().ljust(128, b" ")
            + b" " * 37 * 3 + iso_date17(t) + iso_date17(t) + b"0" * 16 + b"\x00"
            + iso_date17(t) + b"\x01\x00"
        )  # fmt: skip
        self._put(16, pvd)
        self._put(17, b"\xffCD001\x01")
        for i, ident in enumerate((b"BEA01", b"NSR02", b"TEA01")):
            self._put(18 + i, b"\x00" + ident + b"\x01")

        # UDF volume descriptor sequences (main and reserve copy)
        for base in (MAIN_VDS, RESERVE_VDS):
            for i, (ident, body) in enumerate(self._volume_descriptors()):
                self._put(base + i, tag(ident, base + i, body))

        files = len(self.video_ts.files)
        lvid = (
            timestamp(t) + struct.pack("<I", 1) + extent_ad(0, 0)
            + struct.pack("<Q", 16 + files + 3) + bytes(24)
            + struct.pack("<IIII", 1, 46, 0, self.partition_length)
            + impl_id() + struct.pack("<IIHHH", files, 3, UDF_REVISION, UDF_REVISION, UDF_REVISION)
        )  # fmt: skip
        self._put(LVID_SECTOR, tag(9, LVID_SECTOR, lvid))
        self._put(LVID_SECTOR + 1, tag(8, LVID_SECTOR + 1, bytes(496)))

        avdp = extent_ad(16 * SECTOR, MAIN_VDS) + extent_ad(16 * SECTOR, RESERVE_VDS) + bytes(480)
        self._put(AVDP_SECTOR, tag(2, AVDP_SECTOR, avdp))
        self._put(self.total_sectors - 1, tag(2, self.total_sectors - 1, avdp))

        # Partition contents
        fsd = (
            timestamp(t) + struct.pack("<HHIIII", 3, 3, 1, 1, 0, 0) + charspec()
            + dstring(self.label, 128) + charspec() + dstring(self.label, 32)
            + bytes(32) + bytes(32) + long_ad(SECTOR, self.root.fe_block) + domain_id()
            + long_ad(0, 0) + bytes(48)
        )  # fmt: skip
        self._put(PARTITION_START, tag(256, 0, fsd))
        self._put(PARTITION_START + 1, tag(8, 1, bytes(496)))
        links = {"": 3, "AUDIO_TS": 1, "VIDEO_TS": 1}  # root: own "." plus two child parents
        for uid, d in enumerate(self.dirs):
            fe = self._file_entry(d.fe_block, True, len(d.fids), d.data_block,
                                  0 if d is self.root else 16 + uid, links[d.name])  # fmt: skip
            self._put(PARTITION_START + d.fe_block, fe)
            self._put(PARTITION_START + d.data_block, d.fids)
        for uid, f in enumerate(self.video_ts.files, start=19):
            block = self.file_fe[f.name]
            fe = self._file_entry(block, False, f.size, self.data_block + f.offset, uid, 1)
            self._put(PARTITION_START + block, fe)

    def write(self, out: Path, progress: Progress | None = None) -> None:
        self.build_metadata()
        if any(self.data_sector <= s < self.total_sectors - 1 for s in self.sectors):
            raise IsoError("metadata overlaps the file data")
        meta_end = self.data_sector
        total_data = sum(f.size for f in self.files) or 1
        done = 0
        with out.open("wb") as fh:
            for s in range(meta_end):
                fh.write(self.sectors.get(s, bytes(SECTOR)))
            position = meta_end
            for f in sorted(self.files, key=lambda f: f.offset):
                target = self.data_sector + f.offset
                if target < position:
                    raise IsoError(f"{f.name} would overwrite earlier data")
                fh.write(bytes((target - position) * SECTOR))
                with f.path.open("rb") as src:
                    while chunk := src.read(16 * 1024 * 1024):
                        fh.write(chunk)
                        done += len(chunk)
                        if progress:
                            progress(done / total_data)
                fh.write(bytes(-f.size % SECTOR))
                position = target + f.sectors
            fh.write(bytes((self.total_sectors - 1 - position) * SECTOR))
            fh.write(self.sectors[self.total_sectors - 1])


def write_iso(
    video_ts: Path,
    out: Path,
    label: str,
    when: datetime | None = None,
    progress: Progress | None = None,
) -> Path:
    when = when or datetime.now(UTC).astimezone()
    image = _Image(Path(video_ts), label, when)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".part")
    try:
        image.write(tmp, progress)
        tmp.replace(out)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return out
