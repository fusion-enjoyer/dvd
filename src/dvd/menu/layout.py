"""Menu pages as they go on the disc: the project's page list expanded into concrete pages
with placed buttons and remote-control navigation.

Standard pages are filled from the project: the main page links to the others, the chapter
page is split into pages of six chapters, the languages page lists audio and subtitle choices.
Positions are fractions of the frame (x, y, w, h), so one layout serves PAL and NTSC; the
renderer turns them into pixels. The texts are Turkish, the language of the disc menus.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from dvd.lang import name_tr
from dvd.menu.templates import Template, template
from dvd.probe import SourceInfo
from dvd.probe.report import timecode
from dvd.project import edit
from dvd.project.model import MenuAction, MenuPage, Project

Rect = tuple[float, float, float, float]
CHAPTERS_PER_PAGE = 6
DIRECTIONS = ("up", "down", "left", "right")


@dataclass
class Button:
    id: str
    label: str
    action: MenuAction
    rect: Rect
    nav: dict[str, str] = field(default_factory=dict)  # direction -> button id
    thumb: float | None = None  # source time of the picture shown in the button (chapters)
    thumb_title: int = 0  # which title's source that picture comes from (episodes)


@dataclass
class Page:
    id: str
    kind: str
    title: str
    buttons: list[Button]
    headings: list[tuple[str, Rect]] = field(default_factory=list)  # text that is not a button
    subtitle: str = ""  # small line under the title ("Disk 2 / 4")


LIST_X, LIST_Y, LIST_W, ROW_H, ROW_GAP = 0.10, 0.50, 0.42, 0.060, 0.012
BOTTOM_Y, BOTTOM_W, BOTTOM_GAP = 0.84, 0.24, 0.04


def _column(x: float, y: float, count: int, w: float = LIST_W) -> list[Rect]:
    return [(x, y + i * (ROW_H + ROW_GAP), w, ROW_H) for i in range(count)]


def _row(count: int, y: float, w: float, gap: float, centred: bool) -> list[Rect]:
    total = count * w + (count - 1) * gap
    x0 = 0.5 - total / 2 if centred else 0.10
    return [(x0 + i * (w + gap), y, w, ROW_H) for i in range(count)]


def main_rects(count: int, tpl: Template) -> list[Rect]:
    """Where the template puts the main page's buttons."""
    if tpl.main == "row-bottom":
        return _row(count, 0.80, 0.19, 0.025, centred=True)
    if tpl.main == "column-center":
        return _column(0.5 - 0.18, 0.42, count, 0.36)
    return _column(LIST_X, LIST_Y, count)


def _bottom(items: list, tpl: Template) -> list[Button]:
    """The navigation row at the foot of the chapter and language pages."""
    rects = _row(len(items), BOTTOM_Y, BOTTOM_W, BOTTOM_GAP, tpl.title_align == "center")
    return [Button(i, label, a, r) for (i, label, a), r in zip(items, rects, strict=True)]


def _play(chapter: int = 1, title: int = 1, every: bool = False) -> MenuAction:
    return MenuAction(do="play", title=title, chapter=chapter, all=every)


def _page_action(page: str) -> MenuAction:
    return MenuAction(do="page", page=page)


def chapter_page_ids(page_id: str, chapters: int) -> list[str]:
    count = max(1, -(-chapters // CHAPTERS_PER_PAGE))
    return [page_id if i == 0 else f"{page_id}-{i + 1}" for i in range(count)]


def expand(project: Project, infos: SourceInfo | list[SourceInfo]) -> list[Page]:
    """Concrete pages for the disc. The first title's tracks and chapters fill the pages; with
    several titles (a series disc) the episode page lists them and chapters are left out."""
    menus = project.menus
    if menus is None:
        return []
    infos = infos if isinstance(infos, list) else [infos]
    tpl = template(menus.template)
    title = project.titles[0]
    first = menus.first
    times = edit.chapter_times(title, infos[0])
    several = len(project.titles) > 1

    def wanted(p: MenuPage) -> bool:
        if p.id == first:
            return True  # the page the disc opens on is always there
        if p.kind == "chapters":  # a film without chapters, or a series disc
            return len(times) >= 2 and not several
        if p.kind in ("languages", "audio", "subtitles"):
            return has_choice(p.kind, title)  # a page with one option is left out
        return p.kind != "episodes" or several

    shown = [p for p in menus.pages if wanted(p)]
    pages: list[Page] = []
    for page in shown:
        if page.kind == "main":
            made = [_main(page, shown, project, tpl)]
        elif page.kind == "chapters":
            made = _chapters(page, times, first, tpl)
        elif page.kind == "episodes":
            made = _episodes(page, project, infos, first, tpl)
        elif page.kind in ("languages", "audio", "subtitles"):
            made = [_languages(page, project, first, tpl)]
        else:
            made = [_custom(page)]
        for p in made:
            apply_edits(p, page.edits)
        pages += made
    for p in pages:
        auto_nav(p.buttons)
    return pages


def overlapping(rects: dict[str, Rect]) -> list[tuple[str, str]]:
    """Pairs of buttons whose areas overlap: a player may light the wrong one."""
    items = list(rects.items())
    out = []
    for i, (a, (ax, ay, aw, ah)) in enumerate(items):
        for b, (bx, by, bw, bh) in items[i + 1 :]:
            if ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah:
                out.append((a, b))
    return out


def apply_edits(page: Page, edits: dict) -> None:
    """Hand changes from the menu editor over the generated buttons; arrow targets that point
    to a button missing on this page (another chapter page) are left to auto_nav."""
    ids = {b.id for b in page.buttons}
    for b in page.buttons:
        e = edits.get(b.id)
        if e is None:
            continue
        if e.rect is not None:
            b.rect = tuple(e.rect)
        if e.label:
            b.label = e.label
        for d in DIRECTIONS:
            target = getattr(e, d)
            if target in ids:
                b.nav[d] = target


def has_choice(kind: str, title) -> bool:
    """Whether a language page would offer anything to pick."""
    if kind == "audio":
        return len(title.audio) > 1
    if kind == "subtitles":
        return bool(title.subtitles)
    if kind == "languages":
        return len(title.audio) > 1 or bool(title.subtitles)
    return True


def _main(page: MenuPage, all_pages: list[MenuPage], project: Project, tpl: Template) -> Page:
    if page.buttons:
        return _custom(page)
    title = project.titles[0]
    several = len(project.titles) > 1
    choices = [("play", "Hepsini oynat" if several else "Filmi oynat", _play(every=several))]
    labels = {"chapters": "Bölümler", "episodes": "Bölümler", "languages": "Dil ayarları",
              "audio": "Ses", "subtitles": "Altyazı"}  # fmt: skip
    for other in all_pages:
        if other.id == page.id or other.kind not in labels:
            continue
        if not has_choice(other.kind, title):
            continue
        label = other.title or labels.get(other.kind, other.id)
        choices.append((other.id, label, _page_action(other.id)))
    rects = main_rects(len(choices), tpl)
    buttons = [Button(i, label, a, r) for (i, label, a), r in zip(choices, rects, strict=True)]
    series = project.series
    name = page.title or (series.name if series else project.disc.name)
    subtitle = f"Disk {series.disc} / {series.discs}" if series and series.discs > 1 else ""
    return Page(page.id, "main", name, buttons, subtitle=subtitle)


def _episodes(page: MenuPage, project: Project, infos: list[SourceInfo], back: str,
              tpl: Template) -> list[Page]:  # fmt: skip
    """The episodes of a series disc, six to a page, each with a frame from a tenth in."""
    titles = project.titles
    ids = chapter_page_ids(page.id, len(titles))
    out = []
    for n, page_id in enumerate(ids):
        buttons = []
        for i, t in enumerate(titles[n * CHAPTERS_PER_PAGE : (n + 1) * CHAPTERS_PER_PAGE]):
            k = n * CHAPTERS_PER_PAGE + i  # 0-based title index
            info = infos[k] if k < len(infos) else None
            at = (info.duration or 0) * 0.1 if info is not None else 0.0
            col, row = i % 3, i // 3
            rect = (0.10 + col * 0.28, 0.19 + row * 0.32, 0.22, 0.29)
            buttons.append(Button(f"ep{k + 1}", t.name or f"{k + 1}. bölüm",
                                  _play(title=k + 1), rect, thumb=at, thumb_title=k))  # fmt: skip
        bottom = []
        if n > 0:
            bottom.append(("prev", "‹ Önceki", _page_action(ids[n - 1])))
        bottom.append(("back", "Ana menü", _page_action(back)))
        if n < len(ids) - 1:
            bottom.append(("next", "Sonraki ›", _page_action(ids[n + 1])))
        buttons += _bottom(bottom, tpl)
        title = page.title or "Bölümler"
        if len(ids) > 1:
            title += f"  {n + 1}/{len(ids)}"
        out.append(Page(page_id, "episodes", title, buttons))
    return out


def _chapters(page: MenuPage, times: list[float], back: str, tpl: Template) -> list[Page]:
    ids = chapter_page_ids(page.id, len(times))
    out = []
    for n, page_id in enumerate(ids):
        chunk = times[n * CHAPTERS_PER_PAGE : (n + 1) * CHAPTERS_PER_PAGE]
        buttons = []
        for i, at in enumerate(chunk):
            number = n * CHAPTERS_PER_PAGE + i + 1
            col, row = i % 3, i // 3
            rect = (0.10 + col * 0.28, 0.19 + row * 0.32, 0.22, 0.29)  # picture + label line
            buttons.append(Button(f"ch{number}", f"{number}  {timecode(at)}", _play(number),
                                  rect, thumb=at))  # fmt: skip
        bottom = []
        if n > 0:
            bottom.append(("prev", "‹ Önceki", _page_action(ids[n - 1])))
        bottom.append(("back", "Ana menü", _page_action(back)))
        if n < len(ids) - 1:
            bottom.append(("next", "Sonraki ›", _page_action(ids[n + 1])))
        buttons += _bottom(bottom, tpl)
        title = page.title or "Bölümler"
        if len(ids) > 1:
            title += f"  {n + 1}/{len(ids)}"
        out.append(Page(page_id, "chapters", title, buttons))
    return out


def _languages(page: MenuPage, project: Project, back: str, tpl: Template) -> Page:
    title = project.titles[0]
    buttons, headings = [], []
    columns = []
    # On the combined page a column only appears when it offers a choice.
    show_audio = page.kind == "audio" or (page.kind == "languages" and len(title.audio) > 1)
    show_subs = page.kind == "subtitles" or (page.kind == "languages" and bool(title.subtitles))
    if show_audio:
        audio = [(f"a{i}", f"{name_tr(a.lang)}  {a.channels}", MenuAction(do="audio", stream=i))
                 for i, a in enumerate(edit.disc_audio(title))]  # fmt: skip
        columns.append(("Ses", audio))
    if show_subs:
        subs = [("s-off", "Kapalı", MenuAction(do="subtitle", stream=None))]
        subs += [(f"s{i}", name_tr(s.lang), MenuAction(do="subtitle", stream=i))
                 for i, s in enumerate(edit.disc_subtitles(title))]  # fmt: skip
        columns.append(("Altyazı", subs))
    for c, (heading, items) in enumerate(columns):
        x = 0.10 + c * 0.42
        headings.append((heading, (x, 0.22, 0.36, ROW_H)))
        for (bid, label, action), rect in zip(items, _column(x, 0.30, len(items), 0.36),
                                              strict=True):  # fmt: skip
            buttons.append(Button(bid, label, action, rect))
    buttons += _bottom([("back", "Ana menü", _page_action(back))], tpl)
    names = {"languages": "Dil ayarları", "audio": "Ses", "subtitles": "Altyazı"}
    return Page(page.id, page.kind, page.title or names[page.kind], buttons, headings)


def _custom(page: MenuPage) -> Page:
    placed = _column(LIST_X, LIST_Y, len(page.buttons))
    buttons = []
    for b, default in zip(page.buttons, placed, strict=True):
        nav = {d: getattr(b, d) for d in DIRECTIONS if getattr(b, d)}
        buttons.append(Button(b.id, b.label, b.action, b.rect or default, nav))
    return Page(page.id, page.kind, page.title or "", buttons)


def auto_nav(buttons: list[Button]) -> None:
    """Fill the arrow-key targets that are not set: the nearest button in that direction,
    measured between centres, with distance across the direction counting double so a press
    stays in its row or column when it can. No target: the highlight stays."""

    def centre(b: Button) -> tuple[float, float]:
        x, y, w, h = b.rect
        return x + w / 2, y + h / 2

    for b in buttons:
        bx, by = centre(b)
        for direction in DIRECTIONS:
            if direction in b.nav:
                continue
            best, best_cost = None, float("inf")
            for other in buttons:
                if other is b:
                    continue
                ox, oy = centre(other)
                dx, dy = ox - bx, oy - by
                along, across = {"up": (-dy, dx), "down": (dy, dx), "left": (-dx, dy),
                                 "right": (dx, dy)}[direction]  # fmt: skip
                if along <= 1e-6:
                    continue
                cost = along + 2 * abs(across)
                if cost < best_cost:
                    best, best_cost = other, cost
            if best is not None:
                b.nav[direction] = best.id
