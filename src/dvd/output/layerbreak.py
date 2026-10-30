"""Where a dual-layer (DVD-9) image changes layers.

The burner writes layer 0 up to the break and layer 1 after it (opposite track path), so
the break needs: a sector where a cell of a title starts (players pause there for a moment;
inside a cell it would cut a picture), on an ECC block boundary (a multiple of 16 sectors),
layer 0 at least as large as layer 1 and no larger than a layer holds. Of the cells that fit,
the one nearest the middle is taken. Burning programs read the choice from a `.dvd` file
next to the image (ImgBurn's format: `LayerBreak=<sector>` and the image name).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from dvd.ifo import read_disc
from dvd.output.iso import _Image

LAYER_SECTORS = 2_086_912  # one layer of a DVD-9 (DVD-R DL: 2,084,960)
SAFE_LAYER = 2_084_960  # what fits on both DVD+R DL and DVD-R DL
ECC_BLOCK = 16


@dataclass(frozen=True)
class LayerBreak:
    sector: int  # first sector of layer 1 (= sectors on layer 0)
    total: int  # sectors in the image
    title: int  # disc title whose cell starts there
    cell: int  # that cell, from 1

    @property
    def layer1(self) -> int:
        return self.total - self.sector


def candidates(video_ts: Path) -> tuple[int, list[tuple[int, int, int]]]:
    """Image size in sectors, and (sector, disc title, cell) for every title cell start."""
    image = _Image(Path(video_ts), "DVD", datetime.now(UTC))
    offsets = {f.name: f.offset for f in image.files}
    disc = read_disc(video_ts)
    out = []
    for title in disc.titles:
        if not 1 <= title.titleset <= len(disc.titlesets):
            continue
        ts = disc.titlesets[title.titleset - 1]
        first = offsets.get(f"VTS_{ts.number:02}_1.VOB")
        if first is None or not ts.chapters or title.titleset_title > len(ts.chapters):
            continue
        pgcs = {pgc for pgc, _program in ts.chapters[title.titleset_title - 1]}
        for pgc in sorted(pgcs):
            for k, cell in enumerate(ts.titles[pgc - 1].cells, start=1):
                out.append((image.data_sector + first + cell.first_sector, title.number, k))
    return image.total_sectors, sorted(set(out))


def pick(total: int, cells: list[tuple[int, int, int]],
         layer: int | None = None) -> tuple[LayerBreak | None, str]:  # fmt: skip
    """The break among `cells` (see `candidates`), or None with the reason; (None, "")
    when the image fits on one layer. `layer`: sectors a layer holds (SAFE_LAYER)."""
    layer = layer or SAFE_LAYER
    if total <= layer:
        return None, ""
    if total > 2 * layer:
        return None, f"the image ({total} sectors) is larger than two layers"
    inside = [c for c in cells if total - c[0] <= c[0] <= layer]
    fit = [c for c in inside if c[0] % ECC_BLOCK == 0]
    if not fit:
        if not inside:
            return None, "no cell starts between the middle of the image and the end of layer 0"
        return None, (f"{len(inside)} cells start where layer 0 could end, none on a "
                      "16-sector boundary")  # fmt: skip
    sector, title, cell = min(fit, key=lambda c: (abs(c[0] - total / 2), c[0]))
    return LayerBreak(sector, total, title, cell), ""


def choose(video_ts: Path, layer: int | None = None) -> tuple[LayerBreak | None, str]:
    """The layer break for the image of `video_ts` (see `pick`)."""
    return pick(*candidates(video_ts), layer)


def split_point(video_ts: Path, layer: int | None = None) -> tuple[int, float] | None:
    """Where a new cell (not a chapter) would give a layer break when no cell does: the film
    VOBU (titleset 1) nearest the middle that starts on an ECC block inside the window, as
    (disc title, seconds from the title's start). VOBU sectors do not move when a cell is
    added, only the IFO changes."""
    from dvd.qa.validate import _Vobs

    layer = layer or SAFE_LAYER
    image = _Image(Path(video_ts), "DVD", datetime.now(UTC))
    total = image.total_sectors
    offsets = {f.name: f.offset for f in image.files}
    first = offsets.get("VTS_01_1.VOB")
    disc = read_disc(video_ts)
    if first is None or not disc.titlesets or total <= layer or total > 2 * layer:
        return None
    ts = disc.titlesets[0]
    best = None
    for title in disc.titles:
        if title.titleset != 1 or title.titleset_title > len(ts.chapters):
            continue
        pgc = ts.titles[ts.chapters[title.titleset_title - 1][0][0] - 1]
        if not pgc.cells:
            continue
        starts = {c.first_sector for c in pgc.cells}
        lo, hi = pgc.cells[0].first_sector, pgc.cells[-1].last_sector
        for v in ts.title_vobus:
            lba = image.data_sector + first + v
            if lo <= v <= hi and v not in starts and lba % ECC_BLOCK == 0 \
                    and total - lba <= lba <= layer:  # fmt: skip
                key = abs(lba - total / 2)
                if best is None or key < best[0]:
                    best = (key, title.number, lo, v)
    if best is None:
        return None
    _key, number, lo, v = best
    vobs = _Vobs([video_ts / f"VTS_01_{n}.VOB" for n in range(1, 10)])
    try:
        start, here = vobs.read(lo), vobs.read(v)
    finally:
        vobs.close()
    ptm = int.from_bytes(here[0x39:0x3D], "big") - int.from_bytes(start[0x39:0x3D], "big")
    return number, ptm / 90_000


def write_dvd_file(iso: Path, brk: LayerBreak) -> Path:
    """ImgBurn's layer break file for `iso`."""
    path = iso.with_suffix(".dvd")
    path.write_text(f"LayerBreak={brk.sector}\n{iso.name}\n", encoding="utf-8")
    return path
