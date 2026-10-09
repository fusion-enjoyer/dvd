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


@dataclass
class Page:
    id: str
    kind: str
    title: str
    buttons: list[Button]
    headings: list[tuple[str, Rect]] = field(default_factory=list)  # text that is not a button


# Minimal template: a column of text buttons at the lower left.
LIST_X, LIST_Y, LIST_W, ROW_H, ROW_GAP = 0.10, 0.50, 0.42, 0.060, 0.012


def _column(x: float, y: float, count: int, w: float = LIST_W) -> list[Rect]:
    return [(x, y + i * (ROW_H + ROW_GAP), w, ROW_H) for i in range(count)]


def _play(chapter: int = 1) -> MenuAction:
    return MenuAction(do="play", title=1, chapter=chapter)


def _page_action(page: str) -> MenuAction:
    return MenuAction(do="page", page=page)


def chapter_page_ids(page_id: str, chapters: int) -> list[str]:
    count = max(1, -(-chapters // CHAPTERS_PER_PAGE))
    return [page_id if i == 0 else f"{page_id}-{i + 1}" for i in range(count)]


def expand(project: Project, info: SourceInfo) -> list[Page]:
    """Concrete pages for the disc (the first title's tracks and chapters fill them)."""
    menus = project.menus
    if menus is None:
        return []
    title = project.titles[0]
    first = menus.first
    times = edit.chapter_times(title, info)
    # A film without chapters gets no chapter page (and no button for it).
    shown = [p for p in menus.pages if not (p.kind == "chapters" and len(times) < 2)]
    pages: list[Page] = []
    for page in shown:
        if page.kind == "main":
            pages.append(_main(page, shown, project))
        elif page.kind == "chapters":
            pages += _chapters(page, times, first)
        elif page.kind in ("languages", "audio", "subtitles"):
            pages.append(_languages(page, project, first))
        else:
            pages.append(_custom(page))
    for p in pages:
        auto_nav(p.buttons)
    return pages


def _main(page: MenuPage, all_pages: list[MenuPage], project: Project) -> Page:
    if page.buttons:
        return _custom(page)
    title = project.titles[0]
    choices = [("play", "Filmi oynat", _play())]
    labels = {"chapters": "Bölümler", "languages": "Dil ayarları", "audio": "Ses",
              "subtitles": "Altyazı"}  # fmt: skip
    for other in all_pages:
        if other.id == page.id or other.kind not in labels:
            continue
        if other.kind in ("languages", "audio") and len(title.audio) < 2 and not title.subtitles:
            continue  # nothing to choose
        if other.kind == "subtitles" and not title.subtitles:
            continue
        label = other.title or labels.get(other.kind, other.id)
        choices.append((other.id, label, _page_action(other.id)))
    rects = _column(LIST_X, LIST_Y, len(choices))
    buttons = [Button(i, label, a, r) for (i, label, a), r in zip(choices, rects, strict=True)]
    return Page(page.id, "main", page.title or project.disc.name, buttons)


def _chapters(page: MenuPage, times: list[float], back: str) -> list[Page]:
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
        for j, (bid, label, action) in enumerate(bottom):
            buttons.append(Button(bid, label, action, (0.10 + j * 0.28, 0.84, 0.24, ROW_H)))
        title = page.title or "Bölümler"
        if len(ids) > 1:
            title += f"  {n + 1}/{len(ids)}"
        out.append(Page(page_id, "chapters", title, buttons))
    return out


def _languages(page: MenuPage, project: Project, back: str) -> Page:
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
    buttons.append(Button("back", "Ana menü", _page_action(back), (0.10, 0.84, 0.24, ROW_H)))
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
