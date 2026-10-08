"""Mux rendered subtitle bitmaps into a DVD program stream with spumux."""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Callable
from fractions import Fraction
from pathlib import Path
from xml.sax.saxutils import quoteattr

from dvd import toolchain
from dvd.subs.render import DEFAULT_STYLE, SubStyle, render_cue, save_png
from dvd.subs.srt import Cue, SubtitleError

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _time(seconds: float) -> str:
    cs = round(max(0.0, seconds) * 100)
    return f"{cs // 360000}:{cs // 6000 % 60:02}:{cs // 100 % 60:02}.{cs % 100:02}"


def spumux_xml(entries: list[tuple[Cue, str, int, int]], standard: str, forced: bool) -> str:
    lines = [f'<subpictures format="{standard.upper()}">', "  <stream>"]
    for cue, image, x, y in entries:
        attrs = (
            f'start="{_time(cue.start)}" end="{_time(cue.end)}" image={quoteattr(image)} '
            f'xoffset="{x}" yoffset="{y}"'
        )
        if forced:
            attrs += ' force="yes"'
        lines.append(f"    <spu {attrs}/>")
    lines += ["  </stream>", "</subpictures>"]
    return "\n".join(lines) + "\n"


def add_subtitle_stream(
    mpg_in: Path,
    mpg_out: Path,
    cues: list[Cue],
    stream: int,
    frame: tuple[int, int, Fraction],
    standard: str,
    workdir: Path,
    forced: bool = False,
    style: SubStyle = DEFAULT_STYLE,
    progress: Callable[[float], None] | None = None,
    spumux: Path | None = None,
) -> Path:
    """Render `cues` and mux them as subpicture stream `stream` (0-31).

    Cue times are relative to the start of the film: spumux finds the first video timestamp of
    the program stream itself and adds it.
    """
    spumux = spumux or toolchain.find_executable(["spumux.exe", "spumux"], toolchain.tool_dirs())
    if spumux is None:
        raise SubtitleError("spumux not found; run `dvd doctor`")
    folder = workdir / f"sub{stream:02}"
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)
    width, height, aspect = frame
    entries = []
    for i, cue in enumerate(cues):
        bitmap = render_cue(cue, width, height, aspect, style)
        name = f"s{i:05}.png"
        save_png(bitmap, folder / name)
        entries.append((cue, name, bitmap.x, bitmap.y))
        if progress:
            progress((i + 1) / len(cues) * 0.8)
    (folder / "spumux.xml").write_text(spumux_xml(entries, standard, forced), encoding="utf-8")
    env = {**os.environ, "VIDEO_FORMAT": standard.upper()}
    with mpg_in.open("rb") as src, mpg_out.open("wb") as dst:
        proc = subprocess.run(
            [str(spumux), "-m", "dvd", "-s", str(stream), "spumux.xml"],
            stdin=src,
            stdout=dst,
            stderr=subprocess.PIPE,
            cwd=folder,
            env=env,
            creationflags=_NO_WINDOW,
        )
    log = proc.stderr.decode("utf-8", errors="replace")
    (folder / "spumux.log").write_text(log, encoding="utf-8")
    if proc.returncode != 0:
        errors = [line for line in log.splitlines() if line.startswith("ERR")]
        raise SubtitleError("spumux failed: " + ("\n".join(errors) or log[-1500:]))
    if progress:
        progress(1.0)
    return mpg_out
