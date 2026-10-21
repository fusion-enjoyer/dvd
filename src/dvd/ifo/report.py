"""A disc's IFO tables as readable lines: titles, titlesets, menus, cells and commands."""

from __future__ import annotations

from dvd.ifo.reader import Disc, Pgc
from dvd.ifo.uops_names import uop_names
from dvd.ifo.vm import program


def _time(seconds: float) -> str:
    s = round(seconds)
    return f"{s // 3600}:{s // 60 % 60:02}:{s % 60:02}"


def _pgc(name: str, pgc: Pgc, commands: bool) -> list[str]:
    still = {0: "", 255: ", still forever"}.get(pgc.cells[-1].still if pgc.cells else 0)
    still = still if still is not None else f", still {pgc.cells[-1].still} s"
    lines = [f"  {name}: {len(pgc.programs)} programs, {len(pgc.cells)} cells, "
             f"{_time(pgc.seconds)}{still}"]  # fmt: skip
    if pgc.uops:
        lines.append(f"    blocked: {', '.join(uop_names(pgc.uops))}")
    if commands:
        for label, cmds in (("pre", pgc.pre), ("post", pgc.post), ("cell", pgc.cell_commands)):
            if cmds:
                lines.append(f"    {label}:")
                lines += [f"    {line}" for line in program(cmds)]
    return lines


def describe(disc: Disc, commands: bool = False) -> list[str]:
    lines = [f"{len(disc.titles)} titles, {len(disc.titlesets)} titlesets"
             + (f", provider {disc.provider!r}" if disc.provider else "")]  # fmt: skip
    for t in disc.titles:
        lines.append(f"title {t.number}: titleset {t.titleset} title {t.titleset_title}, "
                     f"{t.chapters} chapters, {t.angles} angle(s)")  # fmt: skip
    if disc.first_play is not None:
        lines += _pgc("first play", disc.first_play, commands)
    for k, m in enumerate(disc.menus, start=1):
        lines += _pgc(f"VMG menu {k}" + (f" ({m.entry})" if m.entry else ""), m, commands)
    for ts in disc.titlesets:
        audio = ", ".join(f"{a.language or '?'} {a.coding} {a.channels}ch" for a in ts.audio)
        subs = ", ".join(s.language or "?" for s in ts.subpictures)
        lines.append(f"titleset {ts.number}: {ts.standard.upper()} {ts.aspect} {ts.width} wide; "
                     f"audio: {audio or 'none'}; subtitles: {subs or 'none'}")  # fmt: skip
        for k, m in enumerate(ts.menus, start=1):
            lines += _pgc(f"menu {k}" + (f" ({m.entry})" if m.entry else ""), m, commands)
        for k, pgc in enumerate(ts.titles, start=1):
            lines += _pgc(f"title pgc {k}", pgc, commands)
    return lines
