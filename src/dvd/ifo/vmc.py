"""Compile our menu command language into DVD VM commands (8 bytes each).

The language is the one the menu code writes (and dvdauthor reads): statements separated by
`;`, `if (X op V) statement` and `if (X op V) { statements }`. Blocks become a Goto over
them with the opposite test, the way players run them. Supported statements:

    gN = V | gN = gM | gN += V | gN -= V | gN = random(V)
    audio = N | subtitle = N | button = N
    jump title N [chapter C] | jump menu N | jump cell N | jump vmgm menu entry title
    jump titleset N menu | call menu entry root | resume | exit

`domain` says where the commands run, because some jumps differ between the disc's own
menus ("vmg"), a titleset's menus ("vtsm") and its titles ("title"). The bit layout is the
inverse of `dvd.ifo.vm.decode`.
"""

from __future__ import annotations

import re

CMP_CODE = {"&": 1, "==": 2, "!=": 3, ">=": 4, ">": 5, "<=": 6, "<": 7}
OPPOSITE = {"==": "!=", "!=": "==", ">=": "<", "<": ">=", ">": "<=", "<=": ">"}
SET_CODE = {"=": 1, "+=": 3, "-=": 4, "*=": 5, "/=": 6, "%=": 7}
MENU_CODE = {"title": 2, "root": 3, "subtitle": 4, "audio": 5, "angle": 6, "ptt": 7}
SYSTEM_REG = {"audio": 0x81, "subtitle": 0x82, "button": 0x88}


class CompileError(ValueError):
    pass


class _Bits:
    def __init__(self) -> None:
        self.v = 0

    def put(self, start: int, count: int, value: int) -> _Bits:
        if not 0 <= value < (1 << count):
            raise CompileError(f"value {value} does not fit in {count} bits")
        shift = start - count + 1
        self.v = (self.v & ~(((1 << count) - 1) << shift)) | (value << shift)
        return self

    def bytes(self) -> bytes:
        return self.v.to_bytes(8, "big")


def _reg(name: str) -> int:
    m = re.fullmatch(r"g(\d+)", name)
    if m and int(m.group(1)) < 16:
        return int(m.group(1))
    if name in SYSTEM_REG:
        return SYSTEM_REG[name]
    raise CompileError(f"unknown register {name!r}")


def _number(text: str) -> int | None:
    return int(text) if re.fullmatch(r"\d+", text) else None


def _set(target: str, op: str, value: str, compare: tuple[str, str, str] | None) -> bytes:
    """Group 3: gN op value, optionally guarded by a test of a gN against a number."""
    b = _Bits().put(63, 3, 3)
    if op == "random":
        b.put(59, 4, 8)
    else:
        b.put(59, 4, SET_CODE[op])
    b.put(35, 4, _reg(target))
    n = _number(value)
    if n is not None:
        b.put(60, 1, 1).put(31, 16, n)
    else:
        b.put(23, 8, _reg(value))
    if compare is not None:
        left, cmp, right = compare
        if not left.startswith("g") or _number(right) is None:
            raise CompileError("a set can only be guarded by 'gN op number'")
        b.put(54, 3, CMP_CODE[cmp]).put(55, 1, 1).put(43, 4, _reg(left)).put(15, 16, int(right))
    return b.bytes()


def _guard(b: _Bits, compare: tuple[str, str, str] | None) -> _Bits:
    """The group 0/1 test: a register against a number or another register."""
    if compare is None:
        return b
    left, cmp, right = compare
    b.put(54, 3, CMP_CODE[cmp]).put(39, 8, _reg(left))
    n = _number(right)
    if n is not None:
        b.put(55, 1, 1).put(31, 16, n)
    else:
        b.put(23, 8, _reg(right))
    return b


def _jump_guard(b: _Bits, compare: tuple[str, str, str] | None) -> _Bits:
    """Jumps and system sets test two registers only (bits 15 and 7)."""
    if compare is None:
        return b
    left, cmp, right = compare
    if _number(right) is not None:
        raise CompileError("a guarded jump compares two registers; use Goto for numbers")
    return b.put(54, 3, CMP_CODE[cmp]).put(15, 8, _reg(left)).put(7, 8, _reg(right))


def statement(text: str, domain: str, compare: tuple[str, str, str] | None = None) -> bytes:
    """One statement as one command."""
    s = " ".join(text.split())
    if m := re.fullmatch(r"(g\d+) = random\((\d+)\)", s):
        return _set(m.group(1), "random", m.group(2), compare)
    if m := re.fullmatch(r"(g\d+) (=|\+=|-=|\*=|/=|%=) (g\d+|\d+)", s):
        return _set(m.group(1), m.group(2), m.group(3), compare)
    if m := re.fullmatch(r"(audio|subtitle) = (\d+)", s):
        b = _jump_guard(_Bits().put(63, 3, 2).put(59, 4, 1).put(60, 1, 1), compare)
        flag, value = (39, 38) if m.group(1) == "audio" else (31, 30)
        return b.put(flag, 1, 1).put(value, 7, int(m.group(2))).bytes()
    if m := re.fullmatch(r"button = (\d+)", s):
        b = _jump_guard(_Bits().put(63, 3, 2).put(59, 4, 6).put(60, 1, 1), compare)
        return b.put(31, 16, int(m.group(1))).bytes()
    if s == "exit":
        return _jump_guard(_Bits().put(63, 3, 1).put(60, 1, 1).put(51, 4, 1), compare).bytes()
    if s == "resume":
        return _guard(_Bits().put(63, 3, 1).put(51, 4, 1).put(7, 8, 16), compare).bytes()
    if m := re.fullmatch(r"jump cell (\d+)", s):
        return _guard(_Bits().put(63, 3, 1).put(51, 4, 7).put(7, 8, int(m.group(1))),
                      compare).bytes()  # fmt: skip
    if m := re.fullmatch(r"jump menu (\d+)", s):
        return _guard(_Bits().put(63, 3, 1).put(51, 4, 4).put(14, 15, int(m.group(1))),
                      compare).bytes()  # fmt: skip
    if m := re.fullmatch(r"jump title (\d+)(?: chapter (\d+))?", s):
        b = _jump_guard(_Bits().put(63, 3, 1).put(60, 1, 1), compare)
        title = int(m.group(1))
        if m.group(2):
            if domain == "vmg":
                raise CompileError("jump to a chapter only works inside a titleset")
            return b.put(51, 4, 5).put(22, 7, title).put(41, 10, int(m.group(2))).bytes()
        return b.put(51, 4, 2 if domain == "vmg" else 3).put(22, 7, title).bytes()
    if s == "jump vmgm menu entry title":
        b = _jump_guard(_Bits().put(63, 3, 1).put(60, 1, 1).put(51, 4, 6), compare)
        return b.put(23, 2, 1).put(19, 4, MENU_CODE["title"]).bytes()
    if m := re.fullmatch(r"jump titleset (\d+) menu(?: entry (\w+))?", s):
        b = _jump_guard(_Bits().put(63, 3, 1).put(60, 1, 1).put(51, 4, 6), compare)
        menu = MENU_CODE[m.group(2) or "root"]
        return b.put(23, 2, 2).put(30, 7, int(m.group(1))).put(38, 7, 1).put(19, 4, menu).bytes()
    if m := re.fullmatch(r"call menu entry (\w+)(?: resume (\d+))?", s):
        if domain != "title":
            raise CompileError("'call menu' only works from a title")
        b = _jump_guard(_Bits().put(63, 3, 1).put(60, 1, 1).put(51, 4, 8), compare)
        cell = int(m.group(2) or 1)
        return b.put(23, 2, 2).put(19, 4, MENU_CODE[m.group(1)]).put(31, 8, cell).bytes()
    raise CompileError(f"cannot compile {text!r}")


def _goto(line: int, compare: tuple[str, str, str] | None) -> bytes:
    return _guard(_Bits().put(63, 3, 0).put(51, 4, 1).put(7, 8, line), compare).bytes()


def _split(text: str) -> list[str]:
    """Top-level statements; an if with its block stays one piece."""
    out, depth, cur = [], 0, ""
    for ch in text:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                out.append(cur + ch)
                cur = ""
                continue
        if ch == ";" and depth == 0:
            if cur.strip():
                out.append(cur.strip())
            cur = ""
            continue
        cur += ch
    if cur.strip():
        out.append(cur.strip())
    return [s.strip() for s in out if s.strip()]


_IF = re.compile(r"if \((\w+) (==|!=|>=|<=|>|<|&) (\w+)\) (.*)", re.S)


def compile_program(text: str, domain: str) -> list[bytes]:
    """A whole pre/post/button program. Line numbers for Goto count from 1."""
    out: list[bytes] = []

    def emit(part) -> None:
        if isinstance(part, bytes):  # already compiled (see _merged)
            out.append(part)
            return
        m = _IF.fullmatch(" ".join(part.split()) if "{" not in part else part.strip())
        if m is None:
            out.append(statement(part, domain))
            return
        left, cmp, right, rest = m.groups()
        rest = rest.strip()
        if rest.startswith("{"):
            if cmp not in OPPOSITE:
                raise CompileError(f"cannot invert {cmp!r} for a block")
            body = rest[1 : rest.rindex("}")]
            inner = _split(body)
            if len(inner) == 1 and "{" not in inner[0]:  # one statement: test it directly
                emit(f"if ({left} {cmp} {right}) {inner[0]}")
                return
            at = len(out)
            out.append(b"")  # the skip, filled in once the block's length is known
            for inner in _merged(_split(body), domain):
                emit(inner)
            out[at] = _goto(len(out) + 1, (left, OPPOSITE[cmp], right))
            return
        compare = (left, cmp, right)
        try:
            out.append(statement(rest.rstrip(";"), domain, compare))
        except CompileError:  # the test does not fit this command: skip over it instead
            if cmp not in OPPOSITE:
                raise
            out.append(_goto(len(out) + 3, (left, OPPOSITE[cmp], right)))
            out.append(statement(rest.rstrip(";"), domain))

    for part in _merged(_split(text), domain):
        emit(part)
    return out


def _merged(parts: list[str], domain: str) -> list:
    """`button = N` followed by `jump menu M` becomes one command (a system set may carry a
    link), as dvdauthor's optimizer does: one command instead of two counts toward the 128."""
    out: list = []
    for part in parts:
        flat = " ".join(part.split())
        jump = re.fullmatch(r"jump menu (\d+)", flat)
        before = " ".join(out[-1].split()) if out and isinstance(out[-1], str) else ""
        if jump and re.fullmatch(r"button = \d+", before):
            combined = bytearray(statement(out[-1], domain))
            combined[1] |= 4  # link: LinkPGCN
            combined[6:8] = int(jump.group(1)).to_bytes(2, "big")
            out[-1] = bytes(combined)
            continue
        out.append(part)
    return out
