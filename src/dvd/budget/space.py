"""How much free disk space a build needs, and whether it is there.

With D the disc's estimated size: the encoded picture and sound (D), the muxed program
stream and, while a subtitle is added, the next one (2 D) in the work folder; VIDEO_TS (D)
and the ISO (D) in the output folder. Files a build replaces (an earlier build's work files,
VIDEO_TS and ISO) count as free. A tenth more is asked for, for menus and estimates.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

MARGIN = 1.1


@dataclass(frozen=True)
class Need:
    drive: str  # the folder's drive (or mount point)
    needed: int  # bytes
    free: int  # bytes, counting what the build will replace

    @property
    def enough(self) -> bool:
        return self.free >= self.needed


def _anchor(path: Path) -> Path:
    """The nearest existing folder (the work and output folders may not exist yet)."""
    path = path.resolve()
    while not path.exists() and path != path.parent:
        path = path.parent
    return path


def _size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    if path.is_dir():
        return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())
    return 0


def needs(disc_bytes: int, work_dir: Path, out_dir: Path, iso: Path | None) -> list[Need]:
    """What each drive needs for this build, with what it has."""
    wants = {work_dir: 3 * disc_bytes, out_dir: disc_bytes + (disc_bytes if iso else 0)}
    replaced = {work_dir: _size(work_dir),
                out_dir: _size(out_dir / "VIDEO_TS") + (_size(iso) if iso else 0)}  # fmt: skip
    by_drive: dict[str, list[int]] = {}
    for folder, want in wants.items():
        anchor = _anchor(folder)
        drive = anchor.drive or anchor.anchor or str(anchor)
        entry = by_drive.setdefault(drive, [0, shutil.disk_usage(anchor).free])
        entry[0] += round(want * MARGIN)
        entry[1] += replaced[folder]
    return [Need(drive, needed, free) for drive, (needed, free) in by_drive.items()]


def gb(n: int) -> str:
    return f"{n / 1e9:.1f} GB"
