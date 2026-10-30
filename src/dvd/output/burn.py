"""Writing the finished image to a disc, and checking the disc afterwards.

The drives come from Windows' IMAPI2 (read only). Burning goes through ImgBurn when it is
installed: it takes the `.dvd` file with the DVD-9 layer break, the speed, and reads the
disc back against the image (verify). Without ImgBurn, Windows' own disc image burner opens
with the image (no layer break choice, no verify of its own). `verify_disc` then compares
the VIDEO_TS files on the burnt disc with the ones that were built, byte for byte.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from dvd import toolchain

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
# IMAPI2 media profiles a drive can write that matter here
WRITES = {0x11: "DVD-R", 0x13: "DVD-RW", 0x14: "DVD-RW", 0x15: "DVD-R DL", 0x16: "DVD-R DL",
          0x1A: "DVD+RW", 0x1B: "DVD+R", 0x2B: "DVD+R DL"}  # fmt: skip
SPEEDS = ("auto", "2", "4", "8", "16")
CHUNK = 1 << 20

_LIST = r"""
$m = New-Object -ComObject IMAPI2.MsftDiscMaster2
foreach ($id in $m) {
  $r = New-Object -ComObject IMAPI2.MsftDiscRecorder2
  $r.InitializeDiscRecorder($id)
  ($r.VolumePathNames -join ',') + '|' + $r.VendorId.Trim() + ' ' + $r.ProductId.Trim() + '|' +
    (($r.SupportedProfiles | ForEach-Object { [int]$_ }) -join ',')
}
"""


class BurnError(RuntimeError):
    pass


@dataclass(frozen=True)
class Drive:
    path: str  # "E:\\"
    name: str  # vendor and product
    media: tuple[str, ...]  # what it can write: "DVD+R", "DVD+R DL", ...

    @property
    def dual_layer(self) -> bool:
        return any(m.endswith("DL") for m in self.media)


def parse_drives(text: str) -> list[Drive]:
    """The lines the IMAPI2 script prints: paths|name|profile numbers."""
    out = []
    for line in text.splitlines():
        parts = line.strip().split("|")
        if len(parts) != 3 or not parts[0]:
            continue
        profiles = [int(p) for p in parts[2].split(",") if p.strip().isdigit()]
        media = tuple(dict.fromkeys(WRITES[p] for p in profiles if p in WRITES))
        out.append(Drive(parts[0].split(",")[0], parts[1].strip(), media))
    return out


def drives() -> list[Drive]:
    """DVD writers on this computer (empty elsewhere than Windows or without one)."""
    if sys.platform != "win32":
        return []
    proc = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", _LIST],
                          capture_output=True, text=True, creationflags=_NO_WINDOW,
                          check=False)  # fmt: skip
    return [d for d in parse_drives(proc.stdout) if d.media]


def imgburn() -> Path | None:
    dirs = [*toolchain.tool_dirs()]
    for env in ("ProgramFiles(x86)", "ProgramFiles"):
        if os.environ.get(env):
            dirs.append(Path(os.environ[env]) / "ImgBurn")
    return toolchain.find_executable(["ImgBurn.exe"], dirs)


def imgburn_command(exe: Path, iso: Path, drive: str, speed: str = "auto", verify: bool = True,
                    log: Path | None = None) -> list[str]:  # fmt: skip
    """ImgBurn writing `iso` (its `.dvd` file when there is one: the DVD-9 layer break) to
    `drive`, closing itself when done."""
    if speed not in SPEEDS:
        raise BurnError(f"speed: one of {', '.join(SPEEDS)}")
    source = iso.with_suffix(".dvd") if iso.with_suffix(".dvd").is_file() else iso
    args = [str(exe), "/MODE", "WRITE", "/SRC", str(source), "/DEST", drive.rstrip("\\"),
            "/SPEED", "MAX" if speed == "auto" else f"{speed}x",
            "/VERIFY", "YES" if verify else "NO", "/EJECT", "NO", "/START", "/CLOSE",
            "/NOIMAGEDETAILS"]  # fmt: skip
    if log is not None:
        args += ["/LOG", str(log)]
    return args


def windows_burner_command(iso: Path, drive: str) -> list[str]:
    """Windows' own disc image burner, with the image and drive filled in."""
    return ["isoburn.exe", "/Q", drive.rstrip("\\"), str(iso)]


def burn(iso: Path, drive: str, speed: str = "auto", verify: bool = True) -> str:
    """Write the image; which program did it ("imgburn" or "windows")."""
    exe = imgburn()
    if exe is None:
        subprocess.Popen(windows_burner_command(iso, drive))  # its own window takes over
        return "windows"
    log = iso.with_suffix(".burn.log")
    proc = subprocess.run(imgburn_command(exe, iso, drive, speed, verify, log), check=False)
    if proc.returncode != 0:
        tail = log.read_text(encoding="utf-8", errors="replace")[-1500:] if log.is_file() else ""
        raise BurnError(f"ImgBurn stopped with code {proc.returncode}\n{tail}".strip())
    return "imgburn"


def verify_disc(disc_root: Path, video_ts: Path,
                progress: Callable[[float], None] | None = None) -> list[str]:  # fmt: skip
    """Problems found comparing the disc's VIDEO_TS with the built one (empty: same)."""
    disc = Path(disc_root) / "VIDEO_TS"
    if not disc.is_dir():
        return [f"no VIDEO_TS folder on {disc_root}"]
    built = {p.name.upper(): p for p in Path(video_ts).iterdir() if p.is_file()}
    burnt = {p.name.upper(): p for p in disc.iterdir() if p.is_file()}
    problems = [f"{n} is missing on the disc" for n in sorted(built.keys() - burnt.keys())]
    problems += [f"{n} is on the disc but was not built" for n in sorted(burnt.keys() - built)]
    total = sum(built[n].stat().st_size for n in built.keys() & burnt.keys()) or 1
    done = 0
    for name in sorted(built.keys() & burnt.keys()):
        a, b = built[name], burnt[name]
        if a.stat().st_size != b.stat().st_size:
            problems.append(f"{name}: {b.stat().st_size} bytes on the disc, {a.stat().st_size} "
                            "built")  # fmt: skip
            done += a.stat().st_size
            continue
        with a.open("rb") as fa, b.open("rb") as fb:
            offset = 0
            while chunk := fa.read(CHUNK):
                if fb.read(len(chunk)) != chunk:
                    problems.append(f"{name}: differs from byte {offset}")
                    break
                offset += len(chunk)
                done += len(chunk)
                if progress:
                    progress(done / total)
    return problems
