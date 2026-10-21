"""Our own authoring: VIDEO_TS for a disc without menus, without dvdauthor.

Each title's program stream is copied pack by pack into the titleset's VOB files (padding-
only packs left out, files split at 524272 sectors as players expect), with its NAV packs
written by `nav.py`; the IFO and BUP files come from `ifo_write.py`. Titleset menus (one
language unit, pages made by spumux) come from `menu_write.py`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path

from dvd.author.ifo_write import PROVIDER, TitlesetSpec, vob_bases, write_vmg, write_vts
from dvd.author.menu_write import Button, MenuSource, MenuSpec, button_info
from dvd.author.menu_write import layout as menu_layout
from dvd.author.nav import CellMap, nav_pack
from dvd.author.spu_colors import ColorRemapper, Palette
from dvd.author.vobu import scan_stream

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


@dataclass
class MenuInput:
    """A menu page as spumux made it: its VOB files (an intro and a loop, or one still), the
    still time of each (255: until a key), and what its buttons do, by spumux name."""

    files: list[Path]
    stills: list[int]
    entry: str | None = None
    pre: str = ""
    post: str = ""
    commands: dict[str, str] = field(default_factory=dict)


def write_menu_vob(menus: list[MenuInput], video_ts: Path, standard: str, aspect: str,
                   vts: int = 1) -> list[MenuSpec]:  # fmt: skip
    """VTS_nn_0.VOB with every menu page, NAV packs carrying the buttons; the menu specs for
    the IFO (sources scanned, colours numbered into each page's palette)."""
    pal, wide = standard == "pal", aspect == "16:9"
    fps = Fraction(25) if pal else Fraction(30000, 1001)
    specs = []
    for m in menus:
        spec = MenuSpec([], m.entry, m.pre, m.post)
        palette = Palette()
        for path, still in zip(m.files, m.stills, strict=True):
            spec.sources.append(MenuSource(scan_stream(path, fps), still))
            colors = ColorRemapper(palette)
            with path.open("rb") as src:  # a dry run: buttons and the palette they need
                while len(pack := src.read(PACK)) == PACK:
                    if not colors.info_packet(pack):
                        colors.pack(bytearray(pack))
            if colors.buttons:
                spec.buttons = [Button(name, x1, y1, x2, y2, up, down, left, right, group,
                                       auto, m.commands.get(name, ""))
                                for name, auto, group, x1, y1, x2, y2, up, down, left, right
                                in colors.buttons]  # fmt: skip
                spec.button_colors = colors.button_colors
        spec.palette = palette.entries()
        specs.append(spec)
    ids, bases, _length = menu_layout(specs)
    with (video_ts / f"VTS_{vts:02}_0.VOB").open("wb") as out:
        for m, spec, vob_ids, starts in zip(menus, specs, ids, bases, strict=True):
            palette = Palette()  # the same packs in the same order: the same numbering
            for path, source, vob_id, base in zip(m.files, spec.sources, vob_ids, starts,
                                                  strict=True):  # fmt: skip
                scan = source.scan
                nav_at = {v.sector: i for i, v in enumerate(scan.vobus)}
                cells = CellMap([0], vob_id=vob_id)
                colors = ColorRemapper(palette)
                sector = -1
                with path.open("rb") as src:
                    while len(pack := src.read(PACK)) == PACK:
                        pos = 14 + (pack[13] & 7)
                        if pack[pos : pos + 4] == b"\x00\x00\x01\xbe":
                            colors.info_packet(pack)
                            continue
                        sector += 1
                        pack = bytearray(pack)
                        colors.pack(pack)
                        if sector in nav_at:
                            pack = bytearray(nav_pack(pack, scan, cells, nav_at[sector], pal,
                                                      1, 1, base))  # fmt: skip
                            if source is spec.sources[-1] and spec.buttons:  # the loop / still
                                button_info(pack, spec, scan.vobus[0].start_pts, wide)
                        out.write(pack)
    return specs


def author_disc(spec: TitlesetSpec, sources: list[Path], menus: list[MenuInput],
                out_dir: Path, first_play: str = "", provider: str = PROVIDER) -> Path:  # fmt: skip
    """VIDEO_TS with one titleset and its menus (the disc opens on the root menu)."""
    video_ts = out_dir / "VIDEO_TS"
    video_ts.mkdir(parents=True, exist_ok=True)
    for old in video_ts.iterdir():
        old.unlink()
    for title, palette in zip(spec.titles, write_vobs(spec, sources, video_ts), strict=True):
        title.palette = palette
    menu_specs = write_menu_vob(menus, video_ts, spec.standard, spec.aspect)
    vts = write_vts(spec, menu_specs)
    vmg = write_vmg([(spec, vts)], first_play or "jump titleset 1 menu;", provider)
    for name, data in (("VTS_01_0", vts), ("VIDEO_TS", vmg)):
        (video_ts / f"{name}.IFO").write_bytes(data)
        (video_ts / f"{name}.BUP").write_bytes(data)
    return video_ts
