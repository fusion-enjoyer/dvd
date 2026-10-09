"""A small DVD player for the menus we author: runs the same button commands that go into
dvdauthor, so trying the menus here checks what the disc will do.

Supported commands (all we generate): `jump title T [chapter C]`, `jump menu N`,
`audio = N`, `subtitle = N` (64 + stream: on; below 64: off), `button = N` (N / 1024 is the
button to highlight). Arrow keys follow the buttons' navigation; Menu returns to the root
page, as the remote's Menu key does.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from dvd.menu.author import commands, entries
from dvd.menu.layout import Page

_STATEMENT = re.compile(
    r"jump title (\d+)(?: chapter (\d+))?|jump menu (\d+)|audio = (\d+)|subtitle = (\d+)"
    r"|button = (\d+)"
)


class SimulatorError(ValueError):
    pass


@dataclass
class State:
    page: int = 0  # index into the ordered pages
    button: int = 0  # index of the highlighted button on the page
    audio: int = 0
    subtitle: int | None = None  # stream shown, None: off
    playing: tuple[int, int] | None = None  # (title, chapter) once a play button is pressed
    log: list[str] = field(default_factory=list)


class Simulator:
    def __init__(self, pages: list[Page], first: str, subtitles_on: bool = False) -> None:
        self.pages = sorted(pages, key=lambda p: p.id != first)  # same order as on the disc
        self.commands = commands(self.pages)
        self.entries = entries(self.pages, first)
        self.state = State(subtitle=0 if subtitles_on else None)

    @property
    def page(self) -> Page:
        return self.pages[self.state.page]

    @property
    def button(self):
        return self.page.buttons[self.state.button] if self.page.buttons else None

    def move(self, direction: str) -> None:
        b = self.button
        if b is None or direction not in b.nav:
            return
        ids = [x.id for x in self.page.buttons]
        self.state.button = ids.index(b.nav[direction])

    def menu_key(self) -> None:
        """The remote's Menu key: back to the root page; also stops the film."""
        self.state.playing = None
        self._show(0, 0)

    def press(self) -> None:
        b = self.button
        if b is None:
            return
        command = dict(self.commands[self.page.id])[b.id]
        self.run(command)

    def run(self, command: str) -> None:
        statements = [s.strip() for s in command.split(";") if s.strip()]
        highlight = None
        for s in statements:
            m = _STATEMENT.fullmatch(s)
            if m is None:
                raise SimulatorError(f"the simulator does not know the command {s!r}")
            title, chapter, menu, audio, subtitle, button = m.groups()
            if title:
                self.state.playing = (int(title), int(chapter or 1))
                self.state.log.append(f"play title {title} chapter {chapter or 1}")
                return
            if menu:
                n = int(menu)
                if not 1 <= n <= len(self.pages):
                    raise SimulatorError(f"jump menu {n}: the disc has {len(self.pages)} menus")
                self._show(n - 1, highlight or 0)
            elif audio:
                self.state.audio = int(audio)
                self.state.log.append(f"audio {audio}")
            elif subtitle:
                value = int(subtitle)
                self.state.subtitle = value - 64 if value >= 64 else None
                self.state.log.append(f"subtitle {self.state.subtitle}")
            elif button:
                highlight = int(button) // 1024 - 1

    def _show(self, page: int, button: int) -> None:
        self.state.page = page
        count = len(self.pages[page].buttons)
        self.state.button = min(max(0, button), max(0, count - 1))
