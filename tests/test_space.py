import shutil
from collections import namedtuple
from pathlib import Path

from dvd.budget import space

Usage = namedtuple("Usage", "total used free")


def test_space_needed_per_drive_counts_what_the_build_replaces(tmp_path: Path, monkeypatch):
    work, out = tmp_path / "build" / "Film", tmp_path / "Film"
    disc = 4_000_000_000
    monkeypatch.setattr(shutil, "disk_usage", lambda p: Usage(0, 0, 20_000_000_000))
    (need,) = space.needs(disc, work, out, out / "Film.iso")  # one drive for both
    assert need.needed == round(3 * disc * 1.1) + round(2 * disc * 1.1)
    assert need.free == 20_000_000_000 and not need.enough
    # An earlier build's files will be replaced: they count as free.
    (out / "VIDEO_TS").mkdir(parents=True)
    (out / "VIDEO_TS" / "VTS_01_1.VOB").write_bytes(b"x" * 1000)
    work.mkdir(parents=True)
    (work / "t01.m2v").write_bytes(b"x" * 500)
    (need,) = space.needs(disc, work, out, None)
    assert need.needed == round(3 * disc * 1.1) + round(disc * 1.1)
    assert need.free == 20_000_000_000 + 1500 and need.enough
    assert space.gb(4_400_000_000) == "4.4 GB"
