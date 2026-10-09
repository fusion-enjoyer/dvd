"""Program-stream mux (FFmpeg) and VIDEO_TS authoring (dvdauthor), with or without menus."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from xml.sax.saxutils import quoteattr

from dvd import toolchain

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


VMGM_STILL = "vmgm.mpg"  # black still for the forwarding VMG menu (with intros)


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
    # FFmpeg derives the mux rate from the streams and can declare more than DVD allows; fix it
    # at the DVD rate so an overloaded stream shows up as late packets (author/pscheck.py).
    args += ["-c", "copy", "-muxrate", "10080000", "-f", "dvd", str(out)]
    proc = subprocess.run(args, capture_output=True, creationflags=_NO_WINDOW)
    if proc.returncode != 0:
        raise AuthorError("mux failed: " + proc.stderr.decode("utf-8", errors="replace").strip())
    return out


@dataclass(frozen=True)
class AuthorMenu:
    vob: str  # menu program stream with its button subpicture
    buttons: list[tuple[str, str]]  # (button name in the subpicture, VM command)
    entry: str | None = None  # "root", "ptt", "audio", "subtitle": the remote's menu keys


def dvdauthor_xml(
    titles: list[AuthorTitle],
    standard: str,
    dest: str = "disc",
    menus: list[AuthorMenu] | None = None,
    intros: list[AuthorTitle] | None = None,
    at_end: str = "menu",
) -> str:
    """Without menus the disc plays the titles in a row. With menus it opens on the root
    menu. The default subtitle is switched on once, the first time the root menu runs (g0
    marks that), so a choice made in the menu is not undone when the film starts.

    `intros` play first, from a second titleset (their own picture and sound settings, the
    film's title numbers unchanged); the last one goes through a VMG menu that only jumps
    on to the menu or the film. `at_end`: after the last title, "menu" (stop if there are
    no menus), "stop" or "repeat"."""
    if len({t.aspect for t in titles}) > 1:
        raise AuthorError("titles with different aspect ratios on one disc are not supported yet")
    aspect = titles[0].aspect
    video = f'<video format="{standard}" aspect="{aspect}"'
    video += ' widescreen="nopanscan"/>' if aspect == "16:9" else "/>"
    langs, sub_langs = titles[0].audio_langs, titles[0].subtitle_langs
    start = "jump titleset 1 menu;" if menus else "jump title 1;"
    lines = [f"<dvdauthor dest={quoteattr(dest)}>"]
    if intros:
        # Intro titles are numbered after the film titles across the disc.
        # The VMG menu only forwards; its black still never shows, but a menu without a
        # video cell would leave the IFO pointing at a VIDEO_TS.VOB that is not written.
        lines += [f"  <vmgm><fpc>jump title {len(titles) + 1};</fpc>",
                  f"    <menus>{video}<pgc entry=\"title\"><pre>{start}</pre>"
                  f"<vob file={quoteattr(VMGM_STILL)}/></pgc></menus>",
                  "  </vmgm>"]  # fmt: skip
    else:
        lines.append(f"  <vmgm><fpc>{start}</fpc></vmgm>")
    lines.append("  <titleset>")
    if menus:
        lines += ["    <menus>", f"      {video}"]
        subs_on = titles[0].subtitles_on and bool(sub_langs)
        for m in menus:
            entry = f" entry={quoteattr(m.entry)}" if m.entry else ""
            lines.append(f"      <pgc{entry}>")
            if m.entry == "root":
                start = "subtitle=64; " if subs_on else ""
                lines.append(f"        <pre>if (g0 == 0) {{ g0 = 1; {start}}}</pre>")
            for name, command in m.buttons:
                lines.append(f"        <button name={quoteattr(name)}>{command}</button>")
            lines.append(f'        <vob file={quoteattr(m.vob)} pause="inf"/>')
            lines.append("      </pgc>")
        lines.append("    </menus>")
    lines += [
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
        if t.subtitles_on and t.subtitle_langs and not menus:
            lines.append("        <pre>subtitle=64;</pre>")  # 64 = display on, stream 0
        lines.append(f"        <vob file={quoteattr(t.vob)} chapters={quoteattr(chapters)}/>")
        if n < len(titles) and menus:
            # Play all (g1 = 1) goes on; a single episode chosen in the menu returns to it.
            lines.append(f"        <post>if (g1 == 1) jump title {n + 1}; call menu;</post>")
        elif n < len(titles):
            lines.append(f"        <post>jump title {n + 1};</post>")
        elif at_end == "repeat":
            lines.append("        <post>jump title 1;</post>")
        elif at_end == "menu" and menus:
            lines.append("        <post>call menu;</post>")
        elif at_end == "stop":
            lines.append("        <post>exit;</post>")  # no menus and "menu": playback just ends
        lines.append("      </pgc>")
    lines += ["    </titles>", "  </titleset>"]
    if intros:
        lines += ["  <titleset>", "    <titles>", f"      {video}"]
        for k, t in enumerate(intros, start=1):
            nxt = f"jump title {k + 1};" if k < len(intros) else "call vmgm menu entry title;"
            lines += ["      <pgc>", f"        <vob file={quoteattr(t.vob)}/>",
                      f"        <post>{nxt}</post>", "      </pgc>"]  # fmt: skip
        lines += ["    </titles>", "  </titleset>"]
    lines.append("</dvdauthor>")
    return "\n".join(lines) + "\n"


def author(
    titles: list[AuthorTitle],
    standard: str,
    workdir: Path,
    out_dir: Path,
    dvdauthor: Path | None = None,
    menus: list[AuthorMenu] | None = None,
    intros: list[AuthorTitle] | None = None,
    at_end: str = "menu",
) -> Path:
    """Write VIDEO_TS into out_dir; the vob files must already be in workdir."""
    dvdauthor = dvdauthor or toolchain.find_executable(
        ["dvdauthor.exe", "dvdauthor"], toolchain.tool_dirs()
    )
    if dvdauthor is None:
        raise AuthorError("dvdauthor not found; run `dvd doctor`")
    staging = workdir / "disc"
    shutil.rmtree(staging, ignore_errors=True)
    (workdir / "dvdauthor.xml").write_text(
        dvdauthor_xml(titles, standard, menus=menus, intros=intros, at_end=at_end),
        encoding="utf-8",
    )
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
