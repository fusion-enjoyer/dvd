"""Test helper: author a disc that dvdauthor built, again with our own code, from the same
inputs (dvdauthor.xml names the program streams, commands and still times)."""

from fractions import Fraction
from pathlib import Path

from dvd.author.own import author_xml
from dvd.author.uops import read_masks


def reauthor(work_root: Path, video_ts: Path, out: Path, fps: Fraction | None = None) -> Path:
    xml_path = next(work_root.rglob("dvdauthor.xml"))
    # dvdauthor writes no UOP masks (the build adds them afterwards); give ours the same.
    uops = {}
    for ifo in sorted(video_ts.glob("VTS_*_0.IFO")):
        for k, mask in enumerate(read_masks(ifo), start=1):
            if mask:
                uops[(int(ifo.name[4:6]), k)] = mask
    return author_xml(xml_path, out, provider="DVDAuthor 0.7.2+", uops=uops)


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
