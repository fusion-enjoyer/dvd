"""Program-stream mux (FFmpeg) and VIDEO_TS authoring (dvdauthor) for menu-less discs."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from xml.sax.saxutils import quoteattr

from dvd import toolchain

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class AuthorError(Exception):
    pass


@dataclass(frozen=True)
class AuthorTitle:
    vob: str  # file name inside the work folder (ASCII)
    aspect: str  # "16:9" | "4:3"
    audio_langs: list[str] = field(default_factory=list)
    chapters: list[str] = field(default_factory=list)  # "h:mm:ss.mmm", first is 0
    subtitle_langs: list[str] = field(default_factory=list)
    subtitles_on: bool = False  # show subtitle stream 1 when the title starts


def timecode(seconds: float) -> str:
    ms = round(seconds * 1000)
    return f"{ms // 3_600_000}:{ms // 60_000 % 60:02}:{ms // 1000 % 60:02}.{ms % 1000:03}"


def mux(video: Path, audio: list[Path], out: Path, ffmpeg: Path | None = None) -> Path:
    ffmpeg = ffmpeg or toolchain.find_executable(["ffmpeg.exe", "ffmpeg"], toolchain.tool_dirs())
    if ffmpeg is None:
        raise AuthorError("ffmpeg not found")
    # A raw .m2v has no timestamps on most frames. The DVD muxer starts a new VOBU (with a
    # NAV pack) on an I-frame only by comparing timestamps, so without +genpts the whole film
    # becomes one VOBU: chapters collapse to the start and seeking breaks.
    args = [str(ffmpeg), "-v", "error", "-y", "-fflags", "+genpts", "-i", str(video)]
    for a in audio:
        args += ["-i", str(a)]
    args += ["-map", "0:v"]
    for i in range(len(audio)):
        args += ["-map", f"{i + 1}:a"]
    args += ["-c", "copy", "-f", "dvd", str(out)]
    proc = subprocess.run(args, capture_output=True, creationflags=_NO_WINDOW)
    if proc.returncode != 0:
        raise AuthorError("mux failed: " + proc.stderr.decode("utf-8", errors="replace").strip())
    return out


def dvdauthor_xml(titles: list[AuthorTitle], standard: str, dest: str = "disc") -> str:
    if len({t.aspect for t in titles}) > 1:
        raise AuthorError("titles with different aspect ratios on one disc are not supported yet")
    aspect = titles[0].aspect
    video = f'<video format="{standard}" aspect="{aspect}"'
    video += ' widescreen="nopanscan"/>' if aspect == "16:9" else "/>"
    langs, sub_langs = titles[0].audio_langs, titles[0].subtitle_langs
    lines = [
        f"<dvdauthor dest={quoteattr(dest)}>",
        "  <vmgm><fpc>jump title 1;</fpc></vmgm>",
        "  <titleset>",
        "    <titles>",
        f"      {video}",
        *(f"      <audio lang={quoteattr(lang)}/>" for lang in langs),
        *(f"      <subpicture lang={quoteattr(lang)}/>" for lang in sub_langs),
    ]
    for n, t in enumerate(titles, start=1):
        if t.audio_langs != langs or t.subtitle_langs != sub_langs:
            raise AuthorError("all titles must have the same audio and subtitle languages for now")
        chapters = ",".join(t.chapters or ["0:00:00.000"])
        lines.append("      <pgc>")
        if t.subtitles_on and t.subtitle_langs:
            lines.append("        <pre>subtitle=64;</pre>")  # 64 = display on, stream 0
        lines.append(f"        <vob file={quoteattr(t.vob)} chapters={quoteattr(chapters)}/>")
        if n < len(titles):
            lines.append(f"        <post>jump title {n + 1};</post>")
        lines.append("      </pgc>")
    lines += ["    </titles>", "  </titleset>", "</dvdauthor>"]
    return "\n".join(lines) + "\n"


def author(
    titles: list[AuthorTitle],
    standard: str,
    workdir: Path,
    out_dir: Path,
    dvdauthor: Path | None = None,
) -> Path:
    """Write VIDEO_TS into out_dir; the vob files must already be in workdir."""
    dvdauthor = dvdauthor or toolchain.find_executable(
        ["dvdauthor.exe", "dvdauthor"], toolchain.tool_dirs()
    )
    if dvdauthor is None:
        raise AuthorError("dvdauthor not found; run `dvd doctor`")
    staging = workdir / "disc"
    shutil.rmtree(staging, ignore_errors=True)
    (workdir / "dvdauthor.xml").write_text(dvdauthor_xml(titles, standard), encoding="utf-8")
    env = {**os.environ, "VIDEO_FORMAT": standard.upper()}
    proc = subprocess.run(
        [str(dvdauthor), "-x", "dvdauthor.xml"],
        cwd=workdir,
        env=env,
        capture_output=True,
        creationflags=_NO_WINDOW,
    )
    log = proc.stdout.decode("utf-8", errors="replace") + proc.stderr.decode("utf-8", "replace")
    (workdir / "dvdauthor.log").write_text(log, encoding="utf-8")
    if proc.returncode != 0 or not (staging / "VIDEO_TS" / "VIDEO_TS.IFO").is_file():
        errors = [line for line in log.splitlines() if line.startswith("ERR")]
        raise AuthorError("dvdauthor failed: " + ("\n".join(errors) or log[-2000:]))
    target = out_dir / "VIDEO_TS"
    out_dir.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(target, ignore_errors=True)
    shutil.move(str(staging / "VIDEO_TS"), str(target))
    return target
