"""Subpicture colours: from spumux's per-stream colour lists to the PGC's 16-colour palette.

spumux tells the authoring tool which colours each subpicture stream uses in a padding packet
("dvdauthor-data", left out of the disc), and numbers them from 0 in its SPUs. A PGC has a
single 16-entry palette for all its streams, so the colour numbers in each SPU's SET_COLOR
(and CHG_COLCON) commands are rewritten to palette entries, allocated in the order they are
first used. This follows dvdauthor's procremap state machine, so the palette and the SPUs
come out as dvdauthor writes them.
"""

from __future__ import annotations

from dataclasses import dataclass, field

UNUSED = 0x1000000
GREY = 0x108080  # what unused palette entries are written as


@dataclass
class Palette:
    colors: list[int] = field(default_factory=lambda: [UNUSED] * 16)

    def entries(self) -> list[int]:
        return [c if c < UNUSED else GREY for c in self.colors]


@dataclass
class _Remap:
    """One subpicture stream's colour mapping and where its SPU parser stands."""

    new: list[int] = field(default_factory=lambda: list(range(16)))
    palette: Palette | None = None
    state: str = "begin0"
    offset: int = 0
    length: int = 0
    next: int = 0
    skip: int = 0
    lines: int = 0

    def color(self, i: int) -> int:
        if self.new[i] < 16 or self.palette is None:
            return self.new[i] if self.new[i] < 16 else i
        wanted = self.new[i] & 0xFFFFFF
        colors = self.palette.colors
        if wanted in colors:
            self.new[i] = colors.index(wanted)
        elif UNUSED in colors:
            self.new[i] = colors.index(UNUSED)
            colors[self.new[i]] = wanted
        else:
            raise ValueError("the subpicture palette is full (16 colours)")
        return self.new[i]

    def byte(self, b: int) -> int:
        return self.color(b & 15) | self.color(b >> 4) << 4

    def feed(self, data: bytearray, start: int, end: int) -> None:
        """Run SPU bytes data[start:end] through the parser, rewriting colour bytes."""
        i = start
        while i < end:
            b = data[i]
            s = self.state
            if s == "begin0":
                self.offset, self.skip, self.length = 0, 0, b << 8
                self.state = "begin1"
            elif s == "begin1":
                self.length += b
                self.state = "begin2"
            elif s == "begin2":
                self.next = b << 8
                self.state = "begin3"
            elif s == "begin3":
                self.next += b
                self.state = "wait"
            elif s in ("wait", "skip0"):
                if s == "wait":
                    if self.offset == self.length:
                        self.state = "begin0"
                        continue  # this byte starts the next SPU
                    if self.offset != self.next:
                        self.offset += 1
                        i += 1
                        continue
                self.state = "skip1"
            elif s == "skip1":
                self.state = "next0"
            elif s == "next0":
                self.next = b << 8
                self.state = "next1"
            elif s == "next1":
                self.next += b
                self.state = "cmd"
            elif s in ("skipwait", "cmd"):
                if s == "skipwait":
                    if self.skip:
                        self.skip -= 1
                        self.offset += 1
                        i += 1
                        continue
                    self.state = "cmd"
                if b in (0x00, 0x01, 0x02):
                    pass
                elif b == 0x03:
                    self.state = "col0"
                elif b in (0x04, 0x05, 0x06):
                    self.skip = {0x04: 2, 0x05: 6, 0x06: 4}[b]
                    self.state = "skipwait"
                elif b == 0x07:
                    self.skip, self.state = 2, "chgarg"
                elif b == 0xFF:
                    self.state = "wait"
                else:
                    raise ValueError(f"unknown subpicture command {b:#x}")
            elif s == "col0":
                data[i] = self.byte(b)
                self.state = "col1"
            elif s == "col1":
                data[i] = self.byte(b)
                self.state = "cmd"
            elif s == "chgarg":
                self.skip -= 1
                if not self.skip:
                    self.state = "chgln0"
            elif s.startswith("chgln"):
                k = int(s[-1])
                self.lines = (self.lines if k else 0) | b << (24 - 8 * k)
                if k < 3:
                    self.state = f"chgln{k + 1}"
                elif self.lines == 0x0FFFFFFF:
                    self.state = "cmd"
                else:
                    self.lines = (self.lines >> 12) & 0xF
                    self.skip, self.state = 2, "chgpx0"
            elif s == "chgpx0":
                self.skip -= 1
                if not self.skip:
                    self.skip, self.state = 2, "chgpx1"
            elif s == "chgpx1":
                data[i] = self.byte(b)
                self.skip -= 1
                if not self.skip:
                    self.skip, self.state = 2, "chgpx2"
            elif s == "chgpx2":
                self.skip -= 1
                if not self.skip:
                    self.lines -= 1
                    self.skip = 2
                    self.state = "chgln0" if not self.lines else "chgpx0"
            self.offset += 1
            i += 1


def _cstring(data: bytes, at: int) -> tuple[str, int]:
    end = data.index(0, at)
    return data[at:end].decode("latin-1"), end + 1


class ColorRemapper:
    """Per VOB: rewrite subpicture colours of every pack into `palette`."""

    def __init__(self, palette: Palette) -> None:
        self.palette = palette
        self.streams = [_Remap() for _ in range(32)]
        # Menus: the buttons spumux placed (name, auto, group, x1, y1, x2, y2, up, down,
        # left, right) and their highlight colours, colour numbers already in `palette`.
        self.buttons: list[tuple] = []
        self.button_colors = bytes(24)

    def info_packet(self, pack: bytes) -> bool:
        """Read a spumux "dvdauthor-data" padding packet; True when it was one."""
        if pack[14:18] != b"\x00\x00\x01\xbe" or pack[20:35] != b"dvdauthor-data\x00":
            return False
        if pack[35] != 2 or pack[36] != 1:
            raise ValueError("unexpected spumux information packet")
        stream = self.streams[pack[37] & 31]
        i = 38 + 8  # skip the start and end times
        while pack[i] != 0xFF:
            cmd, count = pack[i], pack[i + 1]
            if cmd == 1:  # the stream's colours
                stream.palette = self.palette
                stream.new = [UNUSED | int.from_bytes(pack[i + 2 + 3 * j : i + 5 + 3 * j], "big")
                              for j in range(count)] + list(range(count, 16))  # fmt: skip
                i += 2 + 3 * count
            elif cmd == 2:  # button highlight colours: colours (not contrasts) renumbered
                colors = bytearray(pack[i + 2 : i + 2 + 8 * count])
                for j in range(count):
                    for k in (0, 1, 4, 5):
                        colors[8 * j + k] = stream.byte(colors[8 * j + k])
                self.button_colors = bytes(colors).ljust(24, b"\0")
                i += 2 + 8 * count
            elif cmd == 3:  # button positions
                i += 2
                for _ in range(count):
                    name, i = _cstring(pack, i)
                    i += 2  # modifier
                    auto, group = pack[i] != 0, pack[i + 1]
                    box = [int.from_bytes(pack[i + 2 + 2 * k : i + 4 + 2 * k], "big")
                           for k in range(4)]  # x1, y1, x2, y2  # fmt: skip
                    i += 10
                    near = []
                    for _ in range(4):
                        text, i = _cstring(pack, i)
                        near.append(text)
                    self.buttons.append((name, auto, group, *box, *near))
            else:
                raise ValueError(f"unknown spumux information command {cmd}")
        return True

    def pack(self, pack: bytearray) -> None:
        """Rewrite the colours of a subpicture packet in place."""
        if pack[14:18] != b"\x00\x00\x01\xbd":
            return
        data = pack[22] + 23
        sub = pack[data]
        if sub & 0xE0 != 0x20:
            return
        end = int.from_bytes(pack[18:20], "big") + 20
        self.streams[sub & 31].feed(pack, data + 1, end)
