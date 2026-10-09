"""Menu pages to disc menus: a short MPEG-2 still with silent audio per page, the button
subpicture muxed in by spumux, and the DVD VM commands for each button."""

from __future__ import annotations

import os
import subprocess
from fractions import Fraction
from pathlib import Path
from xml.sax.saxutils import quoteattr

from dvd import toolchain
from dvd.author.dvdauthor import AuthorError, AuthorMenu
from dvd.menu.layout import DIRECTIONS, Page
from dvd.menu.render import RenderedPage, save_rgba

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
SECONDS = 1  # length of the still; the player holds the last frame (pause="inf")
ENTRIES = {"main": "root", "chapters": "ptt", "languages": "audio", "audio": "audio",
           "subtitles": "subtitle"}  # fmt: skip


def commands(pages: list[Page]) -> dict[str, list[tuple[str, str]]]:
    """VM commands per page: (button name, command). Menu pages are numbered in list order."""
    number = {p.id: i + 1 for i, p in enumerate(pages)}
    out = {}
    for p in pages:
        cmds = []
        for k, b in enumerate(p.buttons, start=1):
            a = b.action
            stay = f"button = {k * 1024}; jump menu {number[p.id]};"  # keep the cursor here
            if a.do == "play":
                cmd = f"jump title {a.title};" if a.chapter == 1 else (
                    f"jump title {a.title} chapter {a.chapter};")  # fmt: skip
            elif a.do == "page":
                if a.page not in number:
                    raise AuthorError(f"button {b.id} opens page {a.page}, which has no menu")
                cmd = f"jump menu {number[a.page]};"
            elif a.do == "audio":
                cmd = f"audio = {a.stream}; {stay}"
            elif a.stream is None:
                cmd = f"subtitle = 0; {stay}"  # stream 0 without the display bit: off
            else:
                cmd = f"subtitle = {64 + a.stream}; {stay}"
            cmds.append((b.id, cmd))
        out[p.id] = cmds
    return out


def entries(pages: list[Page], first: str) -> dict[str, str]:
    """Remote-control entry points: the first page is root; each other key goes to the first
    page of its kind."""
    out, used = {first: "root"}, {"root"}
    for p in pages:
        entry = ENTRIES.get(p.kind)
        if entry and entry not in used and p.id not in out:
            out[p.id] = entry
            used.add(entry)
    return out


def spumux_menu_xml(rendered: RenderedPage, standard: str) -> str:
    spu = '<spu start="00:00:00.00" force="yes" highlight="hl.png" select="sel.png">'
    lines = [f'<subpictures format="{standard.upper()}">', "  <stream>", f"    {spu}"]
    for b, (x0, y0, x1, y1) in rendered.buttons:
        nav = "".join(f" {d}={quoteattr(b.nav[d])}" for d in DIRECTIONS if d in b.nav)
        lines.append(f'      <button name={quoteattr(b.id)} x0="{x0}" y0="{y0}" x1="{x1 - 1}" '
                     f'y1="{y1 - 1}"{nav}/>')  # fmt: skip
    lines += ["    </spu>", "  </stream>", "</subpictures>"]
    return "\n".join(lines) + "\n"


def menu_vob(
    rendered: RenderedPage,
    standard: str,
    aspect: Fraction,
    folder: Path,
    name: str,
) -> Path:
    """Write `name`.mpg in `folder`: the background as a short still, silent AC-3, and the
    highlight subpicture with the buttons."""
    dirs = toolchain.tool_dirs()
    ffmpeg = toolchain.find_executable(["ffmpeg.exe", "ffmpeg"], dirs)
    spumux = toolchain.find_executable(["spumux.exe", "spumux"], dirs)
    if ffmpeg is None or spumux is None:
        raise AuthorError("ffmpeg or spumux not found; run `dvd doctor`")
    work = folder / name
    work.mkdir(parents=True, exist_ok=True)
    rendered.background.save(str(work / "bg.png"))
    save_rgba(rendered.highlight, work / "hl.png")
    save_rgba(rendered.select, work / "sel.png")
    pal = standard == "pal"
    rate = "25" if pal else "30000/1001"
    sd = "bt470bg" if pal else "smpte170m"
    still = work / "still.mpg"
    proc = subprocess.run(
        [str(ffmpeg), "-v", "error", "-y", "-loop", "1", "-framerate", rate,
         "-i", str(work / "bg.png"), "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
         "-t", str(SECONDS),
         "-vf", f"scale=out_color_matrix=bt601:out_range=tv,format=yuv420p,"
                f"setparams=field_mode=prog:color_primaries={sd}:color_trc={sd}:colorspace={sd}",
         "-c:v", "mpeg2video", "-q:v", "2", "-maxrate", "8000k", "-bufsize", "1835k",
         "-g", "15" if pal else "18", "-bf", "0", "-flags", "+ildct+cgop",
         "-sc_threshold", "1000000000", "-aspect", "16:9" if aspect > Fraction(3, 2) else "4:3",
         "-c:a", "ac3", "-b:a", "192k", "-muxrate", "10080000", "-f", "dvd", str(still)],
        capture_output=True, creationflags=_NO_WINDOW,
    )  # fmt: skip
    if proc.returncode != 0:
        raise AuthorError("menu video failed: " + proc.stderr.decode("utf-8", "replace")[-1500:])
    (work / "spumux.xml").write_text(spumux_menu_xml(rendered, standard), encoding="utf-8")
    out = folder / f"{name}.mpg"
    env = {**os.environ, "VIDEO_FORMAT": standard.upper()}
    with still.open("rb") as src, out.open("wb") as dst:
        proc = subprocess.run([str(spumux), "-m", "dvd", "spumux.xml"], stdin=src, stdout=dst,
                              stderr=subprocess.PIPE, cwd=work, env=env,
                              creationflags=_NO_WINDOW)  # fmt: skip
    log = proc.stderr.decode("utf-8", errors="replace")
    (work / "spumux.log").write_text(log, encoding="utf-8")
    if proc.returncode != 0:
        errors = [line for line in log.splitlines() if line.startswith("ERR")]
        raise AuthorError("menu spumux failed: " + ("\n".join(errors) or log[-1500:]))
    return out


def author_menus(pages: list[Page], rendered: dict[str, RenderedPage], first: str,
                 standard: str, aspect: Fraction, workdir: Path) -> list[AuthorMenu]:  # fmt: skip
    """Menu VOBs in `workdir` and their dvdauthor entries, the `first` page first."""
    ordered = sorted(pages, key=lambda p: p.id != first)
    cmds, entry = commands(ordered), entries(ordered, first)
    menus = []
    for i, page in enumerate(ordered):
        vob = menu_vob(rendered[page.id], standard, aspect, workdir, f"menu{i + 1:02}")
        menus.append(AuthorMenu(vob.name, cmds[page.id], entry.get(page.id)))
    return menus
