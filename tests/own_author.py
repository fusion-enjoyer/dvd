"""Test helper: author a disc that dvdauthor built, again with our own code, from the same
inputs (dvdauthor.xml names the program streams, commands and still times)."""

import xml.etree.ElementTree as ET
from fractions import Fraction
from pathlib import Path

from dvd.author.ifo_write import AudioAttr, SubpictureAttr, TitlesetSpec, TitleSpec
from dvd.author.own import MenuInput, author_disc, author_titles
from dvd.author.vobu import scan_stream
from dvd.ifo import read_disc


def reauthor(work_root: Path, video_ts: Path, out: Path, fps: Fraction) -> Path:
    xml_path = next(work_root.rglob("dvdauthor.xml"))
    work = xml_path.parent
    titleset = ET.parse(xml_path).getroot().find("titleset")
    ts = read_disc(video_ts).titlesets[0]
    titles, sources = [], []
    for k, pgc in enumerate(titleset.find("titles").findall("pgc")):
        path = work / pgc.find("vob").get("file")
        scan = scan_stream(path, fps)
        firsts = {c.first_sector - ts.titles[k].cells[0].first_sector for c in ts.titles[k].cells}
        cells = [i for i, v in enumerate(scan.vobus) if v.sector in firsts]
        titles.append(TitleSpec(scan, cells, pgc.findtext("pre") or "", pgc.findtext("post") or ""))
        sources.append(path)
    audio = [AudioAttr(a.coding, a.language, a.channels, k) for k, a in enumerate(ts.audio)]
    subs = [SubpictureAttr(s.language, k) for k, s in enumerate(ts.subpictures)]
    spec = TitlesetSpec(ts.standard, ts.aspect, titles, audio, subs)
    menus_el = titleset.find("menus")
    if menus_el is None:
        return author_titles(spec, sources, out, provider="DVDAuthor 0.7.2+")
    menus = []
    for pgc in menus_el.findall("pgc"):
        vobs = pgc.findall("vob")
        stills = [255 if v.get("pause") == "inf" else int(v.get("pause") or 0) for v in vobs]
        commands = {b.get("name"): b.text for b in pgc.findall("button")}
        menus.append(
            MenuInput(
                [work / v.get("file") for v in vobs],
                stills,
                pgc.get("entry"),
                pgc.findtext("pre") or "",
                pgc.findtext("post") or "",
                commands,
            )
        )
    return author_disc(spec, sources, menus, out, provider="DVDAuthor 0.7.2+")


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
