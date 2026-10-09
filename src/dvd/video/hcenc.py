"""HCEnc driver: two-pass MPEG-2 encode of a VapourSynth clip through the DvdSource bridge."""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import vapoursynth as vs

from dvd import toolchain
from dvd.video.frameserver import FrameServer


class EncodeError(Exception):
    pass


@dataclass(frozen=True)
class EncodeSettings:
    bitrate: int  # average, kbit/s
    maxrate: int  # peak, kbit/s
    aspect: str  # "16:9" | "4:3"
    standard: str  # "pal" | "ntsc"
    pulldown: bool = False
    interlaced: bool = False  # top field first
    chapters: list[int] = field(default_factory=list)  # frames that must start a closed GOP
    profile: str = "best"


def ini_text(avs: Path, m2v: Path, log: Path, workdir: Path, s: EncodeSettings) -> str:
    lines = [
        f"*INFILE {avs}",
        f"*OUTFILE {m2v}",
        f"*LOGFILE {log}",
        f"*DBPATH {workdir}",
        f"*BITRATE {s.bitrate}",
        f"*MAXBITRATE {s.maxrate}",
        f"*PROFILE {s.profile.upper()}",
        f"*ASPECT {s.aspect}",
        "*TFF" if s.interlaced else "*PROGRESSIVE",
        # DVD-compliant GOP lengths from the HCEnc manual: PAL 15, NTSC film with pulldown 12.
        f"*AUTOGOP {12 if s.pulldown else 15}",
        f"*COLOUR {5 if s.standard == 'pal' else 6}",
        "*PRIORITY LOW",
        "*SILENT",
        "*WAIT 0",
    ]
    if s.pulldown:
        lines.append("*PULLDOWN")
    chapters = sorted({c for c in s.chapters if c > 0})
    if chapters:
        lines.append(f"*CHAPTER {len(chapters)}")
        lines += [str(c) for c in chapters]
    return "\n".join(lines) + "\n"


def ansi_path(path: Path) -> str:
    """HCEnc and AviSynth read paths in the ANSI code page; fall back to the 8.3 short name.

    Short names exist only for existing files and folders, so pass a folder and append ASCII
    file names to the result.
    """
    text = str(path)
    if sys.platform != "win32" or _is_ansi(text):
        return text
    buf = ctypes.create_unicode_buffer(32768)
    # Short names can be disabled per volume; then the long name comes back unchanged.
    if ctypes.windll.kernel32.GetShortPathNameW(text, buf, len(buf)) == 0 or not _is_ansi(
        buf.value
    ):
        raise EncodeError(f"path cannot be passed to HCEnc (not ANSI, no short name): {path}")
    return buf.value


def _is_ansi(text: str) -> bool:
    try:
        text.encode("mbcs", errors="strict")
    except UnicodeEncodeError:
        return False
    return True


def _hcenc_workdir(workdir: Path) -> Path:
    workdir.mkdir(parents=True, exist_ok=True)
    try:
        ansi_path(workdir)
        return workdir
    except EncodeError:
        fallback = Path(tempfile.gettempdir()) / "dvd-hcenc"
        fallback.mkdir(exist_ok=True)
        ansi_path(fallback)  # raises with a clear message if this does not work either
        return fallback


def _tail(path: Path, lines: int = 15) -> str:
    try:
        return "\n".join(path.read_text(encoding="mbcs", errors="replace").splitlines()[-lines:])
    except OSError:
        return "(no log)"


def encode(
    clip: vs.VideoNode,
    out: Path,
    settings: EncodeSettings,
    workdir: Path,
    progress: Callable[[float], None] | None = None,
    hcenc: Path | None = None,
) -> Path:
    dirs = toolchain.tool_dirs()
    hcenc = hcenc or toolchain.find_executable(["HCenc_*.exe"], dirs)
    plugin = toolchain.find_executable(["DvdSource.dll"], dirs)
    if hcenc is None or plugin is None:
        raise EncodeError("HCEnc or DvdSource.dll not found; run `dvd doctor`")
    workdir = _hcenc_workdir(workdir)
    out.parent.mkdir(parents=True, exist_ok=True)
    # Every file HCEnc touches gets an ASCII name inside the work folder.
    work = Path(ansi_path(workdir))
    avs, ini, log, m2v = (workdir / n for n in ("video.avs", "hcenc.ini", "hcenc.log", "video.m2v"))
    for f in (log, m2v):
        f.unlink(missing_ok=True)

    with FrameServer(clip) as server:
        avs.write_text(
            f'LoadCPlugin("{ansi_path(plugin)}")\nDvdSource("{server.name}")\n', encoding="mbcs"
        )
        ini.write_text(
            ini_text(work / avs.name, work / m2v.name, work / log.name, work, settings),
            encoding="mbcs",
        )
        # "-noini" would also drop our -ini file, so HC.ini next to the exe is read too; the
        # settings that matter are repeated as parameters, which take priority over both files.
        s = settings
        proc = subprocess.Popen(
            [
                str(hcenc),
                "-ini",
                str(work / ini.name),
                "-2pass",
                "-i",
                str(work / avs.name),
                "-o",
                str(work / m2v.name),
                "-b",
                str(s.bitrate),
                "-maxbitrate",
                str(s.maxrate),
                "-profile",
                s.profile,
                "-aspectratio",
                s.aspect,
                *([] if s.interlaced else ["-progressive"]),
            ],  # fmt: skip
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        total = 2 * clip.num_frames
        while proc.poll() is None:
            if progress:
                progress(min(1.0, server.frames_served / total))
            time.sleep(0.5)
    if proc.returncode != 0 or not m2v.is_file() or m2v.stat().st_size == 0:
        raise EncodeError(f"HCEnc failed (exit {proc.returncode}):\n{_tail(log)}")
    os.replace(m2v, out)
    if progress:
        progress(1.0)
    return out
