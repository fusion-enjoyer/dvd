"""A small DVD player for the menus we author: runs the same button commands that go into
dvdauthor, so trying the menus here checks what the disc will do.

Supported commands (all we generate): `jump title T [chapter C]`, `jump menu N`,
`audio = N`, `subtitle = N` (64 + stream: on; below 64: off), `button = N` (N / 1024 is the
button to highlight), `gN = V`, `gN = random(M)`, `resume`, and
`if (X == V) <command or { block }>` with X one of `audio`, `subtitle`, `gN`. A page's pre
commands run as it opens; `wait()` lets the first page's timeout run out. Arrow keys follow the
buttons' navigation; Menu returns to the root page, as the remote's Menu key does.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass, field

from dvd.menu.author import commands, entries, pre_commands, timeout_command
from dvd.menu.layout import Page

_CONDITION = re.compile(r"(audio|subtitle|g\d+) == (\d+)")
_STATEMENT = re.compile(
    r"jump title (\d+)(?: chapter (\d+))?|jump menu (\d+)|audio = (\d+)|subtitle = (\d+)"
    r"|button = (\d+)|g(\d+) = (\d+)|g(\d+) = random\((\d+)\)|(resume)"
)


def _closing(text: str) -> int:
    """Index of the brace closing the one `text` starts with."""
    depth = 0
    for i, ch in enumerate(text):
        depth += {"{": 1, "}": -1}.get(ch, 0)
        if depth == 0:
            return i
    raise SimulatorError(f"unclosed block in {text!r}")


class SimulatorError(ValueError):
    pass


@dataclass
class State:
    page: int = 0  # index into the ordered pages
    button: int = 0  # index of the highlighted button on the page
    audio: int = 0
    subtitle: int | None = None  # stream shown, None: off
    playing: tuple[int, int] | None = None  # (title, chapter) once a play button is pressed
    left: tuple[int, int] | None = None  # where the Menu key stopped the film (for resume)
    registers: dict[int, int] = field(default_factory=dict)  # general registers set so far
    log: list[str] = field(default_factory=list)


class Simulator:
    def __init__(self, pages: list[Page], first: str, subtitles_on: bool = False,
                 titles: int = 1, timeout: int | None = None) -> None:  # fmt: skip
        self.pages = sorted(pages, key=lambda p: p.id != first)  # same order as on the disc
        self.titles, self.timeout = titles, timeout
        self.commands = commands(self.pages, titles)
        self.entries = entries(self.pages, first)
        self.pre = pre_commands(self.pages)
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
        """The remote's Menu key: back to the root page; also stops the film (the player
        remembers where, for resume)."""
        if self.state.playing is not None:
            self.state.left = self.state.playing
        self.state.playing = None
        self._show(0, 0)

    def wait(self) -> None:
        """Nobody touches the remote: the first page's timeout plays the film."""
        if self.timeout and self.state.playing is None and self.state.page == 0:
            self.run(timeout_command(self.titles))

    def press(self) -> None:
        b = self.button
        if b is None:
            return
        command = dict(self.commands[self.page.id])[b.id]
        self.run(command)

    def run(self, command: str) -> None:
        self._block(command, {"highlight": None, "done": False})

    def _value(self, name: str) -> int:
        if name == "audio":
            return self.state.audio
        if name == "subtitle":
            return 64 + self.state.subtitle if self.state.subtitle is not None else 0
        return self.state.registers.get(int(name[1:]), 0)

    def _block(self, text: str, ctx: dict) -> None:
        """Run statements; `if (...)` takes the next statement or a { block }."""
        rest = text.strip()
        while rest and not ctx["done"]:
            if rest.startswith("if ("):
                close = rest.index(")")
                m = _CONDITION.fullmatch(rest[4:close].strip())
                if m is None:
                    raise SimulatorError(f"the simulator does not know the test {rest[:close]!r}")
                holds = self._value(m.group(1)) == int(m.group(2))
                rest = rest[close + 1 :].strip()
                if rest.startswith("{"):
                    end = _closing(rest)
                    body, rest = rest[1:end], rest[end + 1 :].strip()
                else:
                    body, _, rest = rest.partition(";")
                    rest = rest.strip()
                if holds:
                    self._block(body, ctx)
                continue
            statement, _, rest = rest.partition(";")
            rest = rest.strip()
            if statement.strip():
                self._statement(statement.strip(), ctx)

    def _statement(self, s: str, ctx: dict) -> None:
        m = _STATEMENT.fullmatch(s)
        if m is None:
            raise SimulatorError(f"the simulator does not know the command {s!r}")
        (title, chapter, menu, audio, subtitle, button, register, value, rnd_register,
         rnd_top, resume) = m.groups()  # fmt: skip
        if rnd_register:
            self.state.registers[int(rnd_register)] = random.randint(1, int(rnd_top))
            return
        if resume:
            if self.state.left is not None:
                self.state.playing = self.state.left
                self.state.log.append("resume")
                ctx["done"] = True
            return
        if register:
            self.state.registers[int(register)] = int(value)
            return
        if title:
            self.state.playing = (int(title), int(chapter or 1))
            self.state.log.append(f"play title {title} chapter {chapter or 1}")
            ctx["done"] = True
            return
        if menu:
            n = int(menu)
            if not 1 <= n <= len(self.pages):
                raise SimulatorError(f"jump menu {n}: the disc has {len(self.pages)} menus")
            self._show(n - 1, ctx["highlight"] or 0)
            ctx["done"] = True
            return
        if audio:
            self.state.audio = int(audio)
            self.state.log.append(f"audio {audio}")
        elif subtitle:
            number = int(subtitle)
            self.state.subtitle = number - 64 if number >= 64 else None
            self.state.log.append(f"subtitle {self.state.subtitle}")
        elif button:
            ctx["highlight"] = int(button) // 1024 - 1
            if ctx.get("pre"):  # the page is already up: move the cursor now
                self._place(ctx["highlight"])

    def _show(self, page: int, button: int) -> None:
        self.state.page = page
        self._place(button)
        pre = self.pre.get(self.pages[page].id)
        if pre:
            self._block(pre, {"highlight": None, "done": False, "pre": True})

    def _place(self, button: int) -> None:
        count = len(self.page.buttons)
        self.state.button = min(max(0, button), max(0, count - 1))
