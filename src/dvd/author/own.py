"""Our own authoring: VIDEO_TS for a disc without menus, without dvdauthor.

Each title's program stream is copied pack by pack into the titleset's VOB files (padding-
only packs left out, files split at 524272 sectors as players expect), with its NAV packs
written by `nav.py`; the IFO and BUP files come from `ifo_write.py`. Menus are still
authored by dvdauthor (see `dvdauthor.py`).
"""

from __future__ import annotations

from pathlib import Path

from dvd.author.ifo_write import PROVIDER, TitlesetSpec, vob_bases, write_vmg, write_vts
from dvd.author.nav import CellMap, nav_pack
from dvd.author.spu_colors import ColorRemapper, Palette

PACK = 2048
VOB_FILE_SECTORS = 524272  # just under 1 GB


def write_vobs(spec: TitlesetSpec, sources: list[Path], video_ts: Path,
               vts: int = 1) -> list[list[int]]:  # fmt: skip
    """VTS_nn_1.VOB, _2, ...: every title's packs, NAV packs filled in and subpicture colours
    numbered into each title's palette. Returns those palettes (16 x 0xYYCrCb each)."""
    palettes: list[list[int]] = []
    pal = spec.standard == "pal"
    files = 0
    handle = None
    in_file = VOB_FILE_SECTORS  # start a new file before the first pack
    bases = vob_bases(spec)
    try:
        for n, (title, source, base) in enumerate(zip(spec.titles, sources, bases, strict=True)):
            vobus = title.scan.vobus
            nav_at = {v.sector: i for i, v in enumerate(vobus)}
            cells = CellMap(title.cells, vob_id=n + 1)
            palette = Palette()
            colors = ColorRemapper(palette)
            sector = -1
            with Path(source).open("rb") as src:  # streamed: a film is several gigabytes
                while len(pack := src.read(PACK)) == PACK:
                    if pack[:4] != b"\x00\x00\x01\xba":
                        continue
                    pos = 14 + (pack[13] & 7)
                    if pack[pos : pos + 4] == b"\x00\x00\x01\xbe":
                        colors.info_packet(pack)  # spumux's colour list, not written
                        continue
                    sector += 1
                    pack = bytearray(pack)
                    colors.pack(pack)
                    if sector in nav_at:
                        pack = nav_pack(pack, title.scan, cells, nav_at[sector], pal,
                                        len(spec.audio), len(spec.subpictures), base)  # fmt: skip
                    if in_file >= VOB_FILE_SECTORS:
                        if handle is not None:
                            handle.close()
                        files += 1
                        handle = (video_ts / f"VTS_{vts:02}_{files}.VOB").open("wb")
                        in_file = 0
                    handle.write(pack)
                    in_file += 1
            palettes.append(palette.entries())
    finally:
        if handle is not None:
            handle.close()
    return palettes


def author_titles(spec: TitlesetSpec, sources: list[Path], out_dir: Path,
                  first_play: str = "", provider: str = PROVIDER) -> Path:  # fmt: skip
    """A complete VIDEO_TS with one titleset and no menus."""
    video_ts = out_dir / "VIDEO_TS"
    video_ts.mkdir(parents=True, exist_ok=True)
    for old in video_ts.iterdir():
        old.unlink()
    for title, palette in zip(spec.titles, write_vobs(spec, sources, video_ts), strict=True):
        title.palette = palette
    vts = write_vts(spec)
    vmg = write_vmg([(spec, vts)], first_play, provider)
    for name, data in (("VTS_01_0", vts), ("VIDEO_TS", vmg)):
        (video_ts / f"{name}.IFO").write_bytes(data)
        (video_ts / f"{name}.BUP").write_bytes(data)
    return video_ts
