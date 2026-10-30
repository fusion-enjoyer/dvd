"""Changing the disc's flow from the disc map: links (buttons) between menu pages and
titles, and new pages. Only the main page and custom pages hold buttons one can change;
the chapter, episode and language pages are made from the project and keep their own.

A main page that still has its made-up buttons gets them written out first (with their
places on the page), so adding or taking away one keeps the others as they were.
"""

from __future__ import annotations

from dvd.menu.layout import expand
from dvd.project.model import MAX_MENU_BUTTONS, MenuAction, MenuButton, MenuPage, Project

EDITABLE = ("main", "custom")


class MapEditError(ValueError):
    pass


def _page(project: Project, page_id: str) -> MenuPage:
    if project.menus is None:
        raise MapEditError("the disc has no menus")
    page = next((p for p in project.menus.pages if p.id == page_id), None)
    if page is None:
        raise MapEditError(f"no menu page {page_id!r}")
    if page.kind not in EDITABLE:
        raise MapEditError(f"the {page.kind} page makes its buttons from the project")
    return page


def _write_out(project: Project, infos: list, page: MenuPage) -> None:
    """Give a main page that still shows its made-up buttons those buttons for good."""
    if page.buttons:
        return
    made = next(p for p in expand(project, infos) if p.id == page.id)
    page.buttons = [MenuButton(id=b.id, label=b.label, action=b.action, rect=b.rect,
                               **{d: t for d, t in b.nav.items()})
                    for b in made.buttons if not b.hidden]  # fmt: skip


def targets(project: Project) -> list[tuple[str, str]]:
    """(map node id, name) of everything a link can lead to: titles, then menu pages."""
    out = [(f"title{n}", t.name or f"Başlık {n}") for n, t in enumerate(project.titles, start=1)]
    if project.menus is not None:
        out += [(f"page:{p.id}", p.title or p.id) for p in project.menus.pages]
    return out


def _action(project: Project, target: str) -> MenuAction:
    if target.startswith("title"):
        n = int(target.removeprefix("title"))
        if not 1 <= n <= len(project.titles):
            raise MapEditError(f"there is no title {n}")
        return MenuAction(do="play", title=n)
    page_id = target.removeprefix("page:")
    if project.menus is None or all(p.id != page_id for p in project.menus.pages):
        raise MapEditError(f"no menu page {page_id!r}")
    return MenuAction(do="page", page=page_id)


def _leads_to(action: MenuAction, target: str) -> bool:
    if target.startswith("title"):
        return action.do == "play" and action.title == int(target.removeprefix("title"))
    return action.do == "page" and action.page == target.removeprefix("page:")


def links(project: Project, infos: list, page_id: str) -> list[str]:
    """The map nodes this page's own buttons lead to (empty for pages made from the project)."""
    try:
        page = _page(project, page_id)
    except MapEditError:
        return []
    buttons = page.buttons or next(p for p in expand(project, infos) if p.id == page_id).buttons
    out: list[str] = []
    for node, _name in targets(project):
        if node != f"page:{page_id}" and any(_leads_to(b.action, node) for b in buttons):
            out.append(node)
    return out


def add_link(project: Project, infos: list, page_id: str, target: str) -> MenuButton:
    """A new button on `page_id` leading to `target` (a map node id), placed under the last."""
    page = _page(project, page_id)
    action = _action(project, target)
    _write_out(project, infos, page)
    if len(page.buttons) >= MAX_MENU_BUTTONS:
        raise MapEditError(f"a page holds at most {MAX_MENU_BUTTONS} buttons")
    name = dict(targets(project))[target]
    ids = {b.id for b in page.buttons}
    n = 1
    while f"link{n}" in ids:
        n += 1
    rect = None
    placed = [b.rect for b in page.buttons if b.rect is not None]
    if placed:
        x, y, w, h = max(placed, key=lambda r: r[1])
        if y + 2.25 * h <= 0.92:  # under the lowest button, inside the title-safe area
            rect = (x, round(y + 1.25 * h, 4), w, h)
    button = MenuButton(id=f"link{n}", label=name[:60], action=action, rect=rect)
    page.buttons.append(button)
    return button


def remove_link(project: Project, infos: list, page_id: str, target: str) -> int:
    """Take away the buttons of `page_id` that lead to `target`; how many went."""
    page = _page(project, page_id)
    _write_out(project, infos, page)
    gone = [b.id for b in page.buttons if _leads_to(b.action, target)]
    if not gone:
        raise MapEditError(f"page {page_id!r} has no button to {target}")
    if any(h.after in gone for h in page.hidden):
        raise MapEditError("a hidden clip is placed next to that button; move it first")
    if len(gone) == len(page.buttons):
        raise MapEditError("a page needs at least one button")
    page.buttons = [b for b in page.buttons if b.id not in gone]
    for b in page.buttons:  # arrows that led to a removed button find their own way again
        for d in ("up", "down", "left", "right"):
            if getattr(b, d) in gone:
                setattr(b, d, None)
    return len(gone)


def add_page(project: Project, infos: list, from_page: str, title: str = "Yeni sayfa") -> str:
    """A new custom page, linked from `from_page`, with a button back to it; its id."""
    _page(project, from_page)
    ids = {p.id for p in project.menus.pages}
    n = 1
    while f"sayfa{n}" in ids:
        n += 1
    new = MenuPage(id=f"sayfa{n}", kind="custom", title=title,
                   buttons=[MenuButton(id="back", label="Geri",
                                       action=MenuAction(do="page", page=from_page))])  # fmt: skip
    project.menus.pages.append(new)
    add_link(project, infos, from_page, f"page:{new.id}")
    return new.id


def remove_page(project: Project, infos: list, page_id: str) -> None:
    """Delete a custom page and every button that led to it."""
    page = _page(project, page_id)
    if page.kind != "custom":
        raise MapEditError("only pages added by hand can be deleted")
    if project.menus.first == page_id:
        raise MapEditError("the disc opens on this page")
    for other in project.menus.pages:
        if other is page or other.kind not in EDITABLE:
            continue
        if other.buttons and any(_leads_to(b.action, f"page:{page_id}") for b in other.buttons):
            remove_link(project, infos, other.id, f"page:{page_id}")
    project.menus.pages.remove(page)
