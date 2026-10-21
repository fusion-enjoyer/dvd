"""Disc inspector: a finished VIDEO_TS (ours or a commercial disc's) as a tree of what the
player sees: first play, the disc's menus, titles, each titleset's menus and title program
chains. Selecting one shows its commands, buttons, cells and blocked keys as text; the
compliance check's findings are listed too."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from dvd.gui.i18n import t
from dvd.gui.theme import MONO_FONT
from dvd.ifo import Disc, IfoError, Pgc, read_disc
from dvd.ifo.buttons import menu_buttons
from dvd.ifo.uops_names import uop_names
from dvd.ifo.vm import decode, program

ENTRIES = ("root", "ptt", "audio", "subtitle", "title", "angle")


def _time(seconds: float) -> str:
    s = round(seconds)
    return f"{s // 3600}:{s // 60 % 60:02}:{s % 60:02}"


def _menu_name(k: int, pgc: Pgc) -> str:
    name = t("inspect.menu", n=k)
    if pgc.entry in ENTRIES:
        name += f" ({t(f'inspect.entry.{pgc.entry}')})"
    return name


def pgc_text(pgc: Pgc, video_ts: Path | None = None, titleset: int | None = None) -> str:
    """A program chain as text; with `video_ts` and `titleset` a menu's buttons too."""
    still = pgc.cells[-1].still if pgc.cells else 0
    lines = [t("inspect.pgc", programs=len(pgc.programs), cells=len(pgc.cells),
               time=_time(pgc.seconds))]  # fmt: skip
    if still:
        lines.append(t("inspect.still_forever") if still == 255
                     else t("inspect.still", seconds=still))  # fmt: skip
    if pgc.uops:
        lines.append(t("inspect.blocked") + " " + ", ".join(uop_names(pgc.uops)))
    for key, cmds in (("pre", pgc.pre), ("post", pgc.post), ("cell", pgc.cell_commands)):
        if cmds:
            lines += ["", t(f"inspect.{key}"), *program(cmds)]
    if video_ts is not None and titleset is not None:
        buttons = menu_buttons(video_ts, titleset, pgc)
        if buttons:
            lines += ["", t("inspect.buttons", n=len(buttons))]
        for b in buttons:
            x1, y1, x2, y2 = b.rect
            auto = " auto" if b.auto else ""
            lines.append(f"{b.number:>3}  {x1},{y1}–{x2},{y2}  ↑{b.up} ↓{b.down} ←{b.left} "
                         f"→{b.right}{auto}  {decode(b.command)}")  # fmt: skip
    if pgc.cells:
        lines += ["", t("inspect.cells")]
        for n, c in enumerate(pgc.cells, start=1):
            command = "  " + t("inspect.cell_command", n=c.command) if c.command else ""
            lines.append(f"{n:>3}  {_time(c.seconds)}  "
                         + t("inspect.sectors", first=c.first_sector, last=c.last_sector)
                         + command)  # fmt: skip
    return "\n".join(lines)


def disc_tree(disc: Disc, video_ts: Path) -> list[tuple[str, str, list]]:
    """(label, detail text, children) nodes, children in the same shape."""
    nodes: list[tuple[str, str, list]] = []
    summary = [t("inspect.summary", titles=len(disc.titles), titlesets=len(disc.titlesets))]
    if disc.provider:
        summary.append(t("inspect.provider", name=disc.provider))
    nodes.append((t("inspect.disc"), "\n".join(summary), []))
    if disc.first_play is not None:
        nodes.append((t("inspect.first_play"), pgc_text(disc.first_play), []))
    if disc.menus:
        menus = [(_menu_name(k, m), pgc_text(m, video_ts, 0), [])
                 for k, m in enumerate(disc.menus, start=1)]  # fmt: skip
        nodes.append((t("inspect.disc_menus", n=len(menus)), "", menus))
    titles = []
    for title in disc.titles:
        ts = disc.titlesets[title.titleset - 1] if title.titleset <= len(disc.titlesets) else None
        text = t("inspect.title_line", titleset=title.titleset, n=title.titleset_title,
                 chapters=title.chapters, angles=title.angles)  # fmt: skip
        if ts is not None and title.titleset_title <= len(ts.chapters) and ts.chapters[
                title.titleset_title - 1]:  # fmt: skip
            pgc_no = ts.chapters[title.titleset_title - 1][0][0]
            if 0 < pgc_no <= len(ts.titles):
                text += "\n\n" + pgc_text(ts.titles[pgc_no - 1])
        titles.append((t("inspect.title", n=title.number), text, []))
    nodes.append((t("inspect.titles", n=len(titles)), "", titles))
    for ts in disc.titlesets:
        audio = ", ".join(f"{a.language or '?'} {a.coding} {a.channels}ch" for a in ts.audio)
        subs = ", ".join(s.language or "?" for s in ts.subpictures)
        text = t("inspect.titleset_detail", standard=ts.standard.upper(), aspect=ts.aspect,
                 width=ts.width, audio=audio or "—", subs=subs or "—")  # fmt: skip
        children = []
        if ts.menus:
            menus = [(_menu_name(k, m), pgc_text(m, video_ts, ts.number), [])
                     for k, m in enumerate(ts.menus, start=1)]  # fmt: skip
            children.append((t("inspect.menus", n=len(menus)), "", menus))
        pgcs = [(t("inspect.title_pgc", n=k), pgc_text(p), [])
                for k, p in enumerate(ts.titles, start=1)]  # fmt: skip
        children.append((t("inspect.title_pgcs", n=len(pgcs)), "", pgcs))
        label = t("inspect.titleset", n=ts.number, standard=ts.standard.upper(),
                  aspect=ts.aspect)  # fmt: skip
        nodes.append((label, text, children))
    return nodes


class DiscInspector(QDialog):
    def __init__(self, video_ts: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.video_ts = Path(video_ts)
        self.setWindowTitle(t("inspect.window", folder=str(self.video_ts)))
        self.resize(1000, 640)
        box = QVBoxLayout(self)
        box.setContentsMargins(16, 16, 16, 16)
        self.status = QLabel()
        self.status.setObjectName("muted")
        self.status.setWordWrap(True)
        box.addWidget(self.status)
        split = QSplitter(Qt.Orientation.Horizontal)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.currentItemChanged.connect(self._show)
        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.detail.setFont(QFont(MONO_FONT))
        split.addWidget(self.tree)
        split.addWidget(self.detail)
        split.setSizes([320, 680])
        box.addWidget(split, 1)
        row = QHBoxLayout()
        row.addStretch()
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(self.reject)
        row.addWidget(close)
        box.addLayout(row)
        self.load()

    def load(self) -> None:
        self.tree.clear()
        try:
            disc = read_disc(self.video_ts)
        except (IfoError, OSError) as exc:
            self.status.setText(t("inspect.unreadable", error=str(exc)))
            return
        for label, text, children in disc_tree(disc, self.video_ts):
            self.tree.addTopLevelItem(self._item(label, text, children))
        from dvd.qa.validate import validate

        findings = validate(self.video_ts)
        self.status.setText(t("inspect.clean") if not findings
                            else t("inspect.findings", n=len(findings)))  # fmt: skip
        if findings:
            self.tree.addTopLevelItem(
                self._item(t("inspect.check", n=len(findings)), "\n".join(map(str, findings)), [])
            )
        self.tree.expandToDepth(0)
        self.tree.setCurrentItem(self.tree.topLevelItem(0))

    def _item(self, label: str, text: str, children: list) -> QTreeWidgetItem:
        item = QTreeWidgetItem([label])
        item.setData(0, Qt.ItemDataRole.UserRole, text)
        for child in children:
            item.addChild(self._item(*child))
        return item

    def _show(self, item: QTreeWidgetItem | None, _previous=None) -> None:
        self.detail.setPlainText(item.data(0, Qt.ItemDataRole.UserRole) or "" if item else "")
