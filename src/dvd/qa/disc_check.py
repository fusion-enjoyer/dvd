"""After authoring: read the IFO files back and compare them with what the build asked for.

dvdauthor turns our XML into the disc's tables; this check catches a disc whose tables do
not say what we meant (a missing title, a lost chapter, a film that does not return to the
main menu), before anyone burns it. It only reports; it never stops the build.
"""

from __future__ import annotations

from pathlib import Path

from dvd.ifo import IfoError, read_disc
from dvd.ifo.vm import decode


def check_disc(video_ts: Path, titles: list[tuple[int, float]], extras: int, menus: bool,
               at_end: str, locked: dict[int, int] | None = None) -> list[str]:  # fmt: skip
    """Problems found, as sentences. `titles`: (chapters, seconds) of each film title;
    `extras`: intro and hidden titles in the second titleset; `locked`: intro number ->
    expected user operation mask."""
    try:
        disc = read_disc(video_ts)
    except (IfoError, OSError, IndexError) as exc:
        return [f"disc check: the IFO files cannot be read back ({exc})"]
    problems = []
    if len(disc.titles) != len(titles) + extras:
        problems.append(f"disc check: {len(disc.titles)} titles on the disc, "
                        f"{len(titles) + extras} expected")  # fmt: skip
    film = disc.titlesets[0] if disc.titlesets else None
    for n, (chapters, seconds) in enumerate(titles, start=1):
        on_disc = next((t for t in disc.titles if t.number == n), None)
        if on_disc is None or film is None or n > len(film.titles):
            problems.append(f"disc check: title {n} is missing")
            continue
        if on_disc.chapters != chapters:
            problems.append(f"disc check: title {n} has {on_disc.chapters} chapters, "
                            f"{chapters} expected")  # fmt: skip
        length = film.titles[n - 1].seconds
        if abs(length - seconds) > max(1.0, seconds * 0.01):
            problems.append(f"disc check: title {n} lasts {length:.1f} s, {seconds:.1f} s "
                            "expected")  # fmt: skip
    if menus and film is not None:
        if not any(m.entry == "root" for m in film.menus):
            problems.append("disc check: the titleset has no root menu")
        last = film.titles[len(titles) - 1] if len(film.titles) >= len(titles) else None
        text = " ".join(decode(c) for c in last.post) if last is not None else ""
        if at_end == "menu" and "CallSS VTSM root" not in text:
            problems.append(f"disc check: the last title does not return to the main menu ({text})")
    if locked and len(disc.titlesets) > 1:
        intro = disc.titlesets[1]
        for k, mask in locked.items():
            if k > len(intro.titles) or intro.titles[k - 1].uops & mask != mask:
                problems.append(f"disc check: intro {k} can still be skipped")
    return problems
