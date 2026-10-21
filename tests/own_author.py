"""Test helper: author a disc that dvdauthor built, again with our own code, from the same
inputs (dvdauthor.xml names the program streams, commands and still times)."""

import xml.etree.ElementTree as ET
from fractions import Fraction
from pathlib import Path

from dvd.author.ifo_write import AudioAttr, SubpictureAttr, TitlesetSpec, TitleSpec
from dvd.author.own import MenuInput, TitlesetInput, author_disc, author_titles
from dvd.author.uops import read_masks
from dvd.author.vobu import scan_stream
from dvd.ifo import read_disc


def _menus(element, work: Path) -> list[MenuInput]:
    if element is None:
        return []
    out = []
    for pgc in element.findall("pgc"):
        vobs = pgc.findall("vob")
        stills = [255 if v.get("pause") == "inf" else int(v.get("pause") or 0) for v in vobs]
        commands = {b.get("name"): b.text for b in pgc.findall("button")}
        out.append(
            MenuInput(
                [work / v.get("file") for v in vobs],
                stills,
                pgc.get("entry"),
                pgc.findtext("pre") or "",
                pgc.findtext("post") or "",
                commands,
            )
        )
    return out


def reauthor(work_root: Path, video_ts: Path, out: Path, fps: Fraction) -> Path:
    xml_path = next(work_root.rglob("dvdauthor.xml"))
    work = xml_path.parent
    root = ET.parse(xml_path).getroot()
    disc = read_disc(video_ts)
    inputs = []
    for n, titleset in enumerate(root.findall("titleset")):
        ts = disc.titlesets[n]
        titles, sources = [], []
        masks = read_masks(video_ts / f"VTS_{n + 1:02}_0.IFO")  # dvdauthor writes none
        for k, pgc in enumerate(titleset.find("titles").findall("pgc")):
            path = work / pgc.find("vob").get("file")
            scan = scan_stream(path, fps)
            first = ts.titles[k].cells[0].first_sector
            starts = {c.first_sector - first for c in ts.titles[k].cells}
            cells = [i for i, v in enumerate(scan.vobus) if v.sector in starts]
            titles.append(TitleSpec(scan, cells, pgc.findtext("pre") or "",
                                    pgc.findtext("post") or "",
                                    uops=masks[k]))  # fmt: skip
            sources.append(path)
        audio = [AudioAttr(a.coding, a.language, a.channels, k) for k, a in enumerate(ts.audio)]
        subs = [SubpictureAttr(s.language, k) for k, s in enumerate(ts.subpictures)]
        spec = TitlesetSpec(ts.standard, ts.aspect, titles, audio, subs)
        inputs.append(TitlesetInput(spec, sources, _menus(titleset.find("menus"), work)))
    vmgm = root.find("vmgm")
    first_play = vmgm.findtext("fpc") or "" if vmgm is not None else ""
    disc_menus = _menus(vmgm.find("menus"), work) if vmgm is not None else []
    one = inputs[0]
    if len(inputs) == 1 and not one.menus and not disc_menus:
        return author_titles(one.spec, one.sources, out, first_play,
                             provider="DVDAuthor 0.7.2+")  # fmt: skip
    return author_disc(one.spec, one.sources, one.menus, out, first_play,
                       provider="DVDAuthor 0.7.2+", more=inputs[1:],
                       disc_menus=disc_menus)  # fmt: skip


def same_files(ours: Path, theirs: Path) -> list[str]:
    """Names of the files that differ (or are missing on one side)."""
    names = {p.name for p in ours.iterdir()} | {p.name for p in theirs.iterdir()}
    return sorted(
        n
        for n in names
        if not (ours / n).is_file()
        or not (theirs / n).is_file()
        or (ours / n).read_bytes() != (theirs / n).read_bytes()
    )
