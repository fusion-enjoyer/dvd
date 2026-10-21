"""Menu pages to disc menus: a short MPEG-2 still with silent audio per page, the button
subpicture muxed in by spumux, and the DVD VM commands for each button."""

from __future__ import annotations

import os
import shutil
import subprocess
from fractions import Fraction
from pathlib import Path
from xml.sax.saxutils import quoteattr

from PySide6.QtGui import QImage

from dvd import toolchain
from dvd.author.dvdauthor import AuthorError, AuthorMenu
from dvd.menu.layout import DIRECTIONS, Page
from dvd.menu.render import RenderedPage, save_rgba

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
SECONDS = 1  # length of the still; the player holds the last frame (pause="inf")
ENTRIES = {"main": "root", "chapters": "ptt", "episodes": "ptt", "languages": "audio",
           "audio": "audio", "subtitles": "subtitle"}  # fmt: skip


MAX_RANDOM_TITLES = 60  # each title is one more command in the page's command table


Commands = dict[str, list[tuple[str, str]]]


def commands(pages: list[Page], titles: int = 1,
             via: dict[tuple[str, str], int] | None = None) -> Commands:  # fmt: skip
    """VM commands per page: (button name, command). Menu pages are numbered in list order;
    `titles` is how many titles a random pick chooses from. `via`: (from page, to page) ->
    the menu number of a transition clip played on the way."""
    number = {p.id: i + 1 for i, p in enumerate(pages)}
    via = via or {}
    out = {}
    for p in pages:
        cmds = []
        for k, b in enumerate(p.buttons, start=1):
            a = b.action
            # Keep the cursor on the choice; g2 = 1 tells the page's pre not to move it.
            stay = f"g2 = 1; button = {k * 1024}; jump menu {number[p.id]};"
            if a.do == "play":
                # g1 tells the end of a title whether to go on to the next one (play all).
                jump = f"jump title {a.title};" if a.chapter == 1 else (
                    f"jump title {a.title} chapter {a.chapter};")  # fmt: skip
                cmd = f"g1 = {int(a.all)}; {jump}"
            elif a.do == "page":
                if a.page not in number:
                    raise AuthorError(f"button {b.id} opens page {a.page}, which has no menu")
                cmd = f"jump menu {via.get((p.id, a.page), number[a.page])};"
            elif a.do == "audio":
                cmd = f"audio = {a.stream}; {stay}"
            elif a.do == "hidden":
                # The clip lives in the second titleset; the VMG menu jumps there (g4).
                cmd = f"g4 = {a.stream + 1}; jump vmgm menu entry title;"
            elif a.do == "resume":
                cmd = "resume;"  # players ignore it when nothing was interrupted
            elif a.do == "random":
                if not 1 <= titles <= MAX_RANDOM_TITLES:
                    raise AuthorError(f"a random pick needs 1-{MAX_RANDOM_TITLES} titles")
                jumps = " ".join(f"if (g3 == {n}) jump title {n};" for n in range(1, titles + 1))
                cmd = f"g1 = 0; g3 = random({titles}); {jumps}"
            elif a.stream is None:
                cmd = f"subtitle = 0; {stay}"  # stream 0 without the display bit: off
            else:
                cmd = f"subtitle = {64 + a.stream}; {stay}"
            cmds.append((b.id, cmd))
        out[p.id] = cmds
    return out


def pre_commands(pages: list[Page]) -> dict[str, str]:
    """What a language page runs as it opens: the cursor goes to the audio track playing now
    (or, without an audio column, to the subtitle shown now), so the page shows the current
    choice. Not after a choice on the page itself (g2 = 1): the cursor stays where it was."""
    out = {}
    for p in pages:
        index = {b.id: k for k, b in enumerate(p.buttons, start=1)}
        audio = [(b.action.stream, index[b.id]) for b in p.buttons if b.action.do == "audio"]
        subs = [(b.action.stream, index[b.id]) for b in p.buttons if b.action.do == "subtitle"]
        if audio:
            picks = [f"if (audio == {s}) button = {k * 1024};" for s, k in audio]
        elif subs:
            off = next((k for s, k in subs if s is None), None)
            picks = [f"button = {off * 1024};"] if off else []  # display bit clear: off
            picks += [f"if (subtitle == {64 + s}) button = {k * 1024};"
                      for s, k in subs if s is not None]  # fmt: skip
        else:
            continue
        out[p.id] = f"if (g2 == 0) {{ {' '.join(picks)} }} g2 = 0;"
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


def still_mpg(image: QImage, standard: str, aspect: Fraction, out: Path) -> Path:
    """A one-second program stream of `image` (disc frame size) with silent AC-3."""
    ffmpeg = toolchain.find_executable(["ffmpeg.exe", "ffmpeg"], toolchain.tool_dirs())
    if ffmpeg is None:
        raise AuthorError("ffmpeg not found; run `dvd doctor`")
    png = out.with_suffix(".png")
    image.save(str(png))
    pal = standard == "pal"
    rate = "25" if pal else "30000/1001"
    sd = "bt470bg" if pal else "smpte170m"
    proc = subprocess.run(
        [str(ffmpeg), "-v", "error", "-y", "-loop", "1", "-framerate", rate,
         "-i", str(png), "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
         "-t", str(SECONDS),
         "-vf", f"scale=out_color_matrix=bt601:out_range=tv,format=yuv420p,"
                f"setparams=field_mode=prog:color_primaries={sd}:color_trc={sd}:colorspace={sd}",
         "-c:v", "mpeg2video", "-q:v", "2", "-maxrate", "8000k", "-bufsize", "1835k",
         "-g", "15" if pal else "18", "-bf", "0", "-flags", "+ildct+cgop",
         "-sc_threshold", "1000000000", "-aspect", "16:9" if aspect > Fraction(3, 2) else "4:3",
         "-c:a", "ac3", "-b:a", "192k", "-muxrate", "10080000", "-f", "dvd", str(out)],
        capture_output=True, creationflags=_NO_WINDOW,
    )  # fmt: skip
    if proc.returncode != 0:
        raise AuthorError("menu video failed: " + proc.stderr.decode("utf-8", "replace")[-1500:])
    return out


def menu_vob(
    rendered: RenderedPage,
    standard: str,
    aspect: Fraction,
    folder: Path,
    name: str,
    video: Path | None = None,
) -> Path:
    """Write `name`.mpg in `folder`: the background as a short still with silent AC-3 (or
    `video`, a moving background already muxed), and the highlight subpicture with the
    buttons."""
    spumux = toolchain.find_executable(["spumux.exe", "spumux"], toolchain.tool_dirs())
    if spumux is None:
        raise AuthorError("spumux not found; run `dvd doctor`")
    work = folder / name
    work.mkdir(parents=True, exist_ok=True)
    save_rgba(rendered.highlight, work / "hl.png")
    save_rgba(rendered.select, work / "sel.png")
    still = video or still_mpg(rendered.background, standard, aspect, work / "still.mpg")
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


def transition_mpg(a: QImage, b: QImage, seconds: float, standard: str, aspect: Fraction,
                   out: Path) -> Path:  # fmt: skip
    """A dissolve from page picture `a` to `b` with silent AC-3 (no buttons)."""
    ffmpeg = toolchain.find_executable(["ffmpeg.exe", "ffmpeg"], toolchain.tool_dirs())
    if ffmpeg is None:
        raise AuthorError("ffmpeg not found; run `dvd doctor`")
    first, second = out.with_name(out.stem + "_a.png"), out.with_name(out.stem + "_b.png")
    a.save(str(first))
    b.save(str(second))
    pal = standard == "pal"
    rate = "25" if pal else "30000/1001"
    sd = "bt470bg" if pal else "smpte170m"
    proc = subprocess.run(
        [str(ffmpeg), "-v", "error", "-y",
         "-loop", "1", "-framerate", rate, "-t", f"{seconds:.3f}", "-i", str(first),
         "-loop", "1", "-framerate", rate, "-t", f"{seconds:.3f}", "-i", str(second),
         "-f", "lavfi", "-t", f"{seconds:.3f}", "-i", "anullsrc=r=48000:cl=stereo",
         "-filter_complex",
         f"[0:v][1:v]blend=all_expr='A*(1-T/{seconds:.3f})+B*(T/{seconds:.3f})',"
         f"scale=out_color_matrix=bt601:out_range=tv,format=yuv420p,"
         f"setparams=field_mode=prog:color_primaries={sd}:color_trc={sd}:colorspace={sd}[v]",
         "-map", "[v]", "-map", "2:a", "-t", f"{seconds:.3f}",
         "-c:v", "mpeg2video", "-b:v", "6000k", "-maxrate", "8000k", "-bufsize", "1835k",
         "-g", "12", "-bf", "2", "-flags", "+cgop", "-sc_threshold", "1000000000",
         "-aspect", "16:9" if aspect > Fraction(3, 2) else "4:3",
         "-c:a", "ac3", "-b:a", "192k", "-muxrate", "10080000", "-f", "dvd", str(out)],
        capture_output=True, creationflags=_NO_WINDOW,
    )  # fmt: skip
    if proc.returncode != 0:
        raise AuthorError("menu transition failed: "
                          + proc.stderr.decode("utf-8", "replace")[-1500:])  # fmt: skip
    return out


def timeout_command(titles: int) -> str:
    """What the first page does when nobody presses a key: play (a series: all of it)."""
    return f"g1 = {int(titles > 1)}; jump title 1;"


def author_menus(pages: list[Page], rendered: dict[str, RenderedPage], first: str,
                 standard: str, aspect: Fraction, workdir: Path, titles: int = 1,
                 timeout: int | None = None, videos: dict[str, tuple[Path, float]] | None = None,
                 intros: dict[str, Path] | None = None,
                 transition: float | None = None) -> list[AuthorMenu]:  # fmt: skip
    """Menu VOBs in `workdir` and their dvdauthor entries, the `first` page first. With
    `timeout`, the first page waits that many seconds, then plays. `videos`: moving
    backgrounds by page id (muxed file, seconds it lasts); those pages loop, and a timeout
    counts the loops in g5. `transition`: seconds of a dissolve played between pages; each
    pair gets its own menu after the pages, which jumps on to the page."""
    ordered = sorted(pages, key=lambda p: p.id != first)
    pairs: list[tuple[str, str]] = []
    if transition:
        for page in ordered:
            for b in page.buttons:
                pair = (page.id, b.action.page)
                if b.action.do == "page" and pair not in pairs:
                    pairs.append(pair)
    via = {pair: len(ordered) + k + 1 for k, pair in enumerate(pairs)}
    cmds = commands(ordered, titles, via)
    entry, pre = entries(ordered, first), pre_commands(ordered)
    menus = []
    videos = videos or {}
    for i, page in enumerate(ordered):
        moving = videos.get(page.id)
        vob = menu_vob(rendered[page.id], standard, aspect, workdir, f"menu{i + 1:02}",
                       moving[0] if moving else None)  # fmt: skip
        wait = timeout if timeout and page.id == first else None
        if moving is None:
            menus.append(AuthorMenu(vob.name, cmds[page.id], entry.get(page.id),
                                    pre.get(page.id, ""), wait,
                                    timeout_command(titles) if wait else ""))  # fmt: skip
            continue
        pre_cmd, post = pre.get(page.id, ""), ""
        if wait:  # count the loops: g5 is reset as the page opens
            loops = max(1, -(-wait // max(1, round(moving[1]))))
            pre_cmd = f"g5 = 0; {pre_cmd}".strip()
            post = f"g5 += 1; if (g5 == {loops}) {{ g5 = 0; {timeout_command(titles)} }}"
        intro = (intros or {}).get(page.id)
        if intro is not None and intro.parent != workdir:
            intro = Path(shutil.copy2(intro, workdir / f"menu{i + 1:02}_intro.mpg"))
        menus.append(AuthorMenu(vob.name, cmds[page.id], entry.get(page.id), pre_cmd,
                                post=post, loop=True,
                                intro=intro.name if intro else None))  # fmt: skip
    number = {p.id: i + 1 for i, p in enumerate(ordered)}
    for k, (src, dst) in enumerate(pairs, start=1):
        out = transition_mpg(rendered[src].background, rendered[dst].background, transition,
                             standard, aspect, workdir / f"trans{k:02}.mpg")  # fmt: skip
        menus.append(AuthorMenu(out.name, [], None, pause=0, post=f"jump menu {number[dst]};"))
    return menus
