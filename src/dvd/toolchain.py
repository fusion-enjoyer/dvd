"""Discovery of the external tools the engine drives (ffmpeg, HCEnc, dvdauthor, ...).

Tools are looked up first in the tools directory (``DVD_TOOLS_DIR``, the installed app's
``tools/``, or ``<repo>/tools``, including one level of subfolders), then on ``PATH``.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

REPO_TOOLS_DIR = Path(__file__).resolve().parents[2] / "tools"
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


@dataclass(frozen=True)
class ToolStatus:
    name: str
    purpose: str
    required: bool
    path: Path | None = None
    version: str | None = None
    note: str = ""

    @property
    def found(self) -> bool:
        return self.path is not None


@dataclass(frozen=True)
class ExeTool:
    """A command-line tool found by file name; version read from its output or name."""

    name: str
    purpose: str
    required: bool
    patterns: Sequence[str]
    version_args: Sequence[str] | None = None
    version_regex: str | None = None
    version_from_name: str | None = None


def tools_base() -> Path | None:
    """`DVD_TOOLS_DIR`, else `tools/` of the installed app (beside its python/), else the repo's."""
    env = os.environ.get("DVD_TOOLS_DIR")
    if env:
        return Path(env)
    for base in (Path(sys.prefix).parent / "tools", REPO_TOOLS_DIR):
        if base.is_dir():
            return base
    return None


def tool_dirs() -> list[Path]:
    base = tools_base()
    if base is None or not base.is_dir():
        return []
    return [base, *sorted(p for p in base.iterdir() if p.is_dir())]


def find_executable(patterns: Iterable[str], dirs: Iterable[Path]) -> Path | None:
    patterns = list(patterns)
    for d in dirs:
        for pattern in patterns:
            matches = sorted(p for p in d.glob(pattern) if p.is_file())
            if matches:
                return matches[-1]
    for pattern in patterns:
        if not any(ch in pattern for ch in "*?["):
            found = shutil.which(pattern)
            if found:
                return Path(found)
    return None


def parse_version(text: str, regex: str) -> str | None:
    m = re.search(regex, text)
    return m.group(1) if m else None


def _run_for_version(path: Path, args: Sequence[str]) -> str:
    try:
        proc = subprocess.run(
            [str(path), *args],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=10,
            creationflags=_NO_WINDOW,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return proc.stdout + proc.stderr


def check_exe(tool: ExeTool, dirs: Iterable[Path]) -> ToolStatus:
    path = find_executable(tool.patterns, dirs)
    if path is None:
        return ToolStatus(tool.name, tool.purpose, tool.required)
    version = None
    if tool.version_from_name:
        version = parse_version(path.name, tool.version_from_name)
    elif tool.version_args is not None and tool.version_regex:
        version = parse_version(_run_for_version(path, tool.version_args), tool.version_regex)
    return ToolStatus(tool.name, tool.purpose, tool.required, path, version)


def check_vapoursynth(dirs: Iterable[Path]) -> ToolStatus:
    name, purpose = "VapourSynth", "pre-processing"
    try:
        import vapoursynth as vs
    except ImportError as exc:
        return ToolStatus(name, purpose, True, note=str(exc))
    version = str(vs.core.version_number())
    return ToolStatus(name, purpose, True, Path(vs.__file__).parent, version)


def check_avisynth(dirs: Iterable[Path]) -> ToolStatus:
    """AviSynth+ is only needed to feed HCEnc, which reads .avs scripts.

    The 32-bit DLL is shipped next to HCenc_028.exe; a system install also works.
    """
    name, purpose = "AviSynth+", "HCEnc input"
    if sys.platform != "win32":
        return ToolStatus(name, purpose, False, note="Windows only")
    dll = find_executable(["AviSynth.dll"], dirs)
    if dll is None:
        system = Path(os.environ.get("SYSTEMROOT", r"C:\Windows")) / "SysWOW64" / "AviSynth.dll"
        dll = system if system.is_file() else None
    return ToolStatus(name, purpose, False, dll)


EXE_TOOLS: tuple[ExeTool, ...] = (
    ExeTool(
        "ffmpeg",
        "decode, audio encode",
        True,
        ("ffmpeg.exe", "ffmpeg"),
        ["-version"],
        r"ffmpeg version (\S+)",
    ),
    ExeTool(
        "ffprobe",
        "source analysis",
        True,
        ("ffprobe.exe", "ffprobe"),
        ["-version"],
        r"ffprobe version (\S+)",
    ),
    ExeTool(
        "HCEnc", "MPEG-2 encode", False, ("HCenc_*.exe",), version_from_name=r"HCenc_(\d+)\.exe"
    ),
    ExeTool("DvdSource", "HCEnc frame bridge", False, ("DvdSource.dll",)),
    ExeTool(
        "dvdauthor",
        "VIDEO_TS authoring",
        True,
        ("dvdauthor.exe", "dvdauthor"),
        ["-h"],
        r"version (\d+\.\d+\.\d+)",
    ),
    ExeTool(
        "spumux",
        "subpicture mux",
        True,
        ("spumux.exe", "spumux"),
        ["-h"],
        r"version (\d+\.\d+\.\d+)",
    ),
)

CHECKS: tuple[Callable[[list[Path]], ToolStatus], ...] = (check_vapoursynth, check_avisynth)


def check_all() -> list[ToolStatus]:
    dirs = tool_dirs()
    return [*(check_exe(t, dirs) for t in EXE_TOOLS), *(check(dirs) for check in CHECKS)]
