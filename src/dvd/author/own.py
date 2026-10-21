"""Our own authoring: VIDEO_TS for a disc without menus, without dvdauthor.

Each title's program stream is copied pack by pack into the titleset's VOB files (padding-
only packs left out, files split at 524272 sectors as players expect), with its NAV packs
written by `nav.py`; the IFO and BUP files come from `ifo_write.py`. Titleset menus (one
language unit, pages made by spumux) come from `menu_write.py`.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path

from dvd.author.ifo_write import PROVIDER, TitlesetSpec, vob_bases, write_vmg, write_vts
from dvd.author.menu_write import Button, MenuSource, MenuSpec, button_info
from dvd.author.menu_write import layout as menu_layout
from dvd.author.nav import CellMap, nav_pack
from dvd.author.spu_colors import ColorRemapper, Palette
from dvd.author.vobu import Scan, scan_stream

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
    """VTS_nn_0.VOB (vts 0: VIDEO_TS.VOB, the disc's own menus) with every menu page, NAV
    packs carrying the buttons; the menu specs for the IFO (sources scanned, colours
    numbered into each page's palette)."""
    pal, wide = standard == "pal", aspect == "16:9"
    fps = Fraction(25) if pal else Fraction(30000, 1001)
    specs = []
    for m in menus:
        spec = MenuSpec([], m.entry, m.pre, m.post, domain="vmg" if vts == 0 else "vtsm")
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
    name = "VIDEO_TS.VOB" if vts == 0 else f"VTS_{vts:02}_0.VOB"
    streams = (1, 0) if vts == 0 else (1, 1)  # the disc's menus carry no subpicture here
    with (video_ts / name).open("wb") as out:
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
                                                      *streams, base))  # fmt: skip
                            if source is spec.sources[-1] and spec.buttons:  # the loop / still
                                button_info(pack, spec, scan.vobus[0].start_pts, wide)
                        out.write(pack)
    return specs


@dataclass
class TitlesetInput:
    spec: TitlesetSpec
    sources: list[Path]  # each title's program stream
    menus: list[MenuInput] = field(default_factory=list)


def author_disc(spec: TitlesetSpec, sources: list[Path], menus: list[MenuInput],
                out_dir: Path, first_play: str = "", provider: str = PROVIDER,
                more: list[TitlesetInput] | None = None,
                disc_menus: list[MenuInput] | None = None) -> Path:  # fmt: skip
    """VIDEO_TS with titleset 1 (and `more` titlesets) with their menus; `disc_menus` are
    the disc's own menus (VIDEO_TS.VOB). Without `first_play` the disc opens on the root
    menu of titleset 1."""
    video_ts = out_dir / "VIDEO_TS"
    video_ts.mkdir(parents=True, exist_ok=True)
    for old in video_ts.iterdir():
        old.unlink()
    written = []
    for n, ts in enumerate([TitlesetInput(spec, sources, menus), *(more or [])], start=1):
        for title, palette in zip(ts.spec.titles, write_vobs(ts.spec, ts.sources, video_ts, n),
                                  strict=True):  # fmt: skip
            title.palette = palette
        menu_specs = write_menu_vob(ts.menus, video_ts, ts.spec.standard, ts.spec.aspect, n) \
            if ts.menus else None  # fmt: skip
        vts = write_vts(ts.spec, menu_specs)
        written.append((ts.spec, vts))
        (video_ts / f"VTS_{n:02}_0.IFO").write_bytes(vts)
        (video_ts / f"VTS_{n:02}_0.BUP").write_bytes(vts)
    vmgm = write_menu_vob(disc_menus, video_ts, spec.standard, spec.aspect, 0) \
        if disc_menus else None  # fmt: skip
    default = "jump titleset 1 menu;" if menus else ""
    vmg = write_vmg(written, first_play or default, provider, vmgm)
    (video_ts / "VIDEO_TS.IFO").write_bytes(vmg)
    (video_ts / "VIDEO_TS.BUP").write_bytes(vmg)
    return video_ts


def chapter_cells(scan: Scan, chapters: list[float]) -> list[int]:
    """The VOBU each chapter starts on: the one whose start is nearest the chapter time
    (dvdauthor's findnearestvobu, ties to the earlier one). Times in seconds from the start."""
    starts = [v.start_pts for v in scan.vobus]
    first = starts[0]
    cells: list[int] = []
    for t in chapters:
        pts = int(t * 90000 + 0.5) + first
        if pts >= scan.vobus[-1].end_pts:
            continue  # past the end: dvdauthor drops it
        i = max(bisect_right(starts, pts) - 1, 0)
        if i + 1 < len(starts) and abs(pts - starts[i + 1]) < abs(pts - starts[i]):
            i += 1
        if i not in cells:
            cells.append(i)
    return sorted(cells) or [0]


def _seconds(timecode: str) -> float:
    total = 0.0
    for part in timecode.split(":"):
        total = total * 60 + float(part)
    return total


def _menu_inputs(element, work: Path) -> list[MenuInput]:
    if element is None:
        return []
    out = []
    for pgc in element.findall("pgc"):
        vobs = pgc.findall("vob")
        stills = [255 if v.get("pause") == "inf" else int(v.get("pause") or 0) for v in vobs]
        commands = {b.get("name"): b.text or "" for b in pgc.findall("button")}
        out.append(MenuInput([work / v.get("file") for v in vobs], stills, pgc.get("entry"),
                             pgc.findtext("pre") or "", pgc.findtext("post") or "",
                             commands))  # fmt: skip
    return out


def author_xml(xml_path: Path, out_dir: Path, provider: str = PROVIDER,
               uops: dict[tuple[int, int], int] | None = None) -> Path:  # fmt: skip
    """The disc a dvdauthor.xml describes (the subset `dvdauthor.dvdauthor_xml` writes),
    authored by us. Stream attributes come from the program streams as dvdauthor reads them;
    `uops`: (titleset, title PGC) from 1 -> what the viewer may not do."""
    import xml.etree.ElementTree as ET

    from dvd.author.ifo_write import AudioAttr, SubpictureAttr, TitleSpec

    work = Path(xml_path).parent
    root = ET.parse(xml_path).getroot()
    inputs = []
    for n, titleset in enumerate(root.findall("titleset"), start=1):
        block = titleset.find("titles")
        video = block.find("video")
        standard = video.get("format", "pal").lower()
        fps = Fraction(25) if standard == "pal" else Fraction(30000, 1001)
        titles, sources = [], []
        for k, pgc in enumerate(block.findall("pgc"), start=1):
            vob = pgc.find("vob")
            path = work / vob.get("file")
            scan = scan_stream(path, fps)
            marks = [_seconds(c) for c in (vob.get("chapters") or "0").split(",")]
            titles.append(TitleSpec(scan, chapter_cells(scan, marks), pgc.findtext("pre") or "",
                                    pgc.findtext("post") or "",
                                    uops=(uops or {}).get((n, k), 0)))  # fmt: skip
            sources.append(path)
        langs = [a.get("lang") for a in block.findall("audio")]
        sub_langs = [s.get("lang") for s in block.findall("subpicture")]
        formats = {k: f for t in reversed(titles) for k, f in t.scan.audio_formats.items()}
        streams = sorted(formats) if formats else []
        audio = [AudioAttr(formats[k].coding, langs[i] if i < len(langs) else None,
                           formats[k].channels, k, formats[k].surround)
                 for i, k in enumerate(streams)]  # fmt: skip
        found = {k for t in titles for k in t.scan.subpictures}
        count = max(len(sub_langs), max(found) + 1 if found else 0)
        subs = [SubpictureAttr(sub_langs[k] if k < len(sub_langs) else None, k)
                for k in range(count)]  # fmt: skip
        spec = TitlesetSpec(standard, video.get("aspect", "4:3"), titles, audio, subs)
        inputs.append(TitlesetInput(spec, sources, _menu_inputs(titleset.find("menus"), work)))
    vmgm = root.find("vmgm")
    first_play = (vmgm.findtext("fpc") or "") if vmgm is not None else ""
    disc_menus = _menu_inputs(vmgm.find("menus"), work) if vmgm is not None else []
    one = inputs[0]
    if len(inputs) == 1 and not one.menus and not disc_menus:
        return author_titles(one.spec, one.sources, out_dir, first_play, provider)
    return author_disc(one.spec, one.sources, one.menus, out_dir, first_play, provider,
                       more=inputs[1:], disc_menus=disc_menus)  # fmt: skip
