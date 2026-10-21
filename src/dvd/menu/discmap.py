"""The disc as a graph: what plays when the disc goes in, which menu page leads where, what
follows each title. Built from the same pages and commands that go onto the disc."""

from __future__ import annotations

from dataclasses import dataclass, field

from dvd.menu.layout import expand
from dvd.project.model import Project

COLUMNS = ("start", "intro", "page", "title")  # left to right on the map


@dataclass
class Node:
    id: str
    kind: str  # start | intro | page | title | hidden | end
    label: str
    note: str = ""  # a second, smaller line


@dataclass
class Edge:
    src: str
    dst: str
    labels: list[str] = field(default_factory=list)
    style: str = "solid"  # solid: a button or the normal order; dashed: automatic; dotted: chance

    @property
    def text(self) -> str:
        tail = [x.removeprefix("bölüm ") for x in self.labels if x.startswith("bölüm ")]
        numbers = [int(x) for x in tail if x.isdigit()]
        if len(numbers) > 1 and len(numbers) == len(self.labels):
            return f"bölüm {min(numbers)}–{max(numbers)}"
        shown = [x for x in self.labels if x][:2]
        more = len([x for x in self.labels if x]) - len(shown)
        return ", ".join(shown) + (f" +{more}" if more > 0 else "")


@dataclass
class DiscMap:
    nodes: list[Node]
    edges: list[Edge]

    def node(self, node_id: str) -> Node:
        return next(n for n in self.nodes if n.id == node_id)


def _column(kind: str) -> str:
    return {"hidden": "title", "end": "title"}.get(kind, kind)


def disc_map(project: Project, infos: list) -> DiscMap:
    nodes = [Node("start", "start", "Disk takılınca")]
    edges: dict[tuple[str, str, str], Edge] = {}

    def link(src: str, dst: str, label: str = "", style: str = "solid") -> None:
        edge = edges.setdefault((src, dst, style), Edge(src, dst, [], style))
        if label and label not in edge.labels:
            edge.labels.append(label)

    for k, intro in enumerate(project.first_play, start=1):
        name = intro.file.replace("\\", "/").rsplit("/", 1)[-1]
        nodes.append(Node(f"intro{k}", "intro", f"Giriş {k}", name if intro.skippable
                          else f"{name} · atlanamaz"))  # fmt: skip
        link("start" if k == 1 else f"intro{k - 1}", f"intro{k}")
    last_intro = f"intro{len(project.first_play)}" if project.first_play else "start"

    for n, title in enumerate(project.titles, start=1):
        nodes.append(Node(f"title{n}", "title", title.name or f"Başlık {n}",
                          title.source.rsplit("/", 1)[-1]))  # fmt: skip
    menus = project.menus
    pages = expand(project, infos) if menus is not None else []
    first_page = next((p.id for p in pages if p.id == menus.first), None) if pages else None
    for page in pages:
        picks = [b for b in page.buttons if b.action.do in ("audio", "subtitle")]
        note = "ses / altyazı seçimi" if picks else ""
        if page.id == first_page:
            note = "açılış sayfası" + (f" · {note}" if note else "")
        nodes.append(Node(f"page:{page.id}", "page", page.title or page.id, note))
    hidden = menus.hidden_clips() if menus is not None else []
    for k, clip in enumerate(hidden, start=1):
        name = clip.file.replace("\\", "/").rsplit("/", 1)[-1]
        nodes.append(Node(f"hidden{k}", "hidden", f"Gizli video {k}", name))

    if first_page:
        link(last_intro, f"page:{first_page}")
    else:
        link(last_intro, "title1")
    for page in pages:
        src = f"page:{page.id}"
        for b in page.buttons:
            a = b.action
            label = b.label or ("gizli nokta" if b.hidden else b.id)
            if a.do == "play" and page.kind == "chapters":
                link(src, f"title{a.title}", f"bölüm {a.chapter}")
            elif a.do == "play":
                link(src, f"title{a.title}", label)
            elif a.do == "page":
                link(src, f"page:{a.page}", label)
            elif a.do == "random":
                for n in range(1, len(project.titles) + 1):
                    link(src, f"title{n}", label, "dotted")
            elif a.do == "hidden":
                link(src, f"hidden{a.stream + 1}", "gizli nokta")
            elif a.do == "resume":
                link(src, "title1", label, "dashed")
    if first_page and menus.timeout:
        link(f"page:{first_page}", "title1", f"{menus.timeout} sn beklenince", "dashed")
    for k in range(1, len(hidden) + 1):
        link(f"hidden{k}", f"page:{first_page}" if first_page else "title1", "bitince")

    count = len(project.titles)
    menu_target = f"page:{first_page}" if first_page else None
    stop_needed = False
    for n in range(1, count + 1):
        src = f"title{n}"
        if n < count:
            link(src, f"title{n + 1}", "hepsini oynatırken" if menu_target else "bitince",
                 "dashed" if menu_target else "solid")  # fmt: skip
            if menu_target:
                link(src, menu_target, "tek bölüm bitince", "dashed")
        elif project.at_end == "repeat":
            link(src, "title1", "bitince baştan", "dashed")
        elif project.at_end == "menu" and menu_target:
            link(src, menu_target, "bitince", "dashed")
        else:
            stop_needed = True
            link(src, "end", "bitince", "dashed")
    if stop_needed:
        nodes.append(Node("end", "end", "Durur"))
    return DiscMap(nodes, list(edges.values()))


def columns(m: DiscMap) -> list[list[Node]]:
    """The nodes in their map columns (empty columns left out)."""
    out = [[n for n in m.nodes if _column(n.kind) == c] for c in COLUMNS]
    return [c for c in out if c]
