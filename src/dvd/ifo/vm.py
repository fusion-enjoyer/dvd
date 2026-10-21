"""DVD VM commands (8 bytes each) as readable text.

The decoding follows the instruction groups of the DVD-Video navigation commands as the
open-source players implement them (libdvdnav's vmcmd.c): the top three bits pick the group
(special, link/jump, system set, register set, and the combined compare-set-link forms), a
compare may guard the command, and a link may follow a set. Bit positions below count from
63 (the first bit of the first byte) down to 0.
"""

from __future__ import annotations

CMP = {1: "&", 2: "==", 3: "!=", 4: ">=", 5: ">", 6: "<=", 7: "<"}
SET = {1: "=", 2: "<->", 3: "+=", 4: "-=", 5: "*=", 6: "/=", 7: "%=", 8: "= random", 9: "&=",
       10: "|=", 11: "^="}  # fmt: skip
SYSTEM = {0: "menu_language", 1: "audio", 2: "subtitle", 3: "angle", 4: "title", 5: "vts_title",
          6: "pgc", 7: "chapter", 8: "button", 9: "timer", 10: "timer_pgc", 11: "karaoke",
          12: "country", 13: "parental_level", 14: "video_pref", 15: "audio_pref",
          16: "audio_lang", 17: "audio_lang_ext", 18: "subtitle_lang", 19: "subtitle_lang_ext",
          20: "region"}  # fmt: skip
LINKS = {0: "LinkNoLink", 1: "LinkTopC", 2: "LinkNextC", 3: "LinkPrevC", 5: "LinkTopPG",
         6: "LinkNextPG", 7: "LinkPrevPG", 9: "LinkTopPGC", 10: "LinkNextPGC",
         11: "LinkPrevPGC", 12: "LinkGoUpPGC", 13: "LinkTailPGC", 16: "Resume"}  # fmt: skip
MENUS = {2: "title", 3: "root", 4: "subtitle", 5: "audio", 6: "angle", 7: "chapter"}


class _Cmd:
    def __init__(self, raw: bytes) -> None:
        if len(raw) != 8:
            raise ValueError("a VM command is 8 bytes")
        self.v = int.from_bytes(raw, "big")

    def bits(self, start: int, count: int) -> int:
        return (self.v >> (start - count + 1)) & ((1 << count) - 1)


def _reg(r: int) -> str:
    if r & 0x80:
        return SYSTEM.get(r & 0x7F, f"s{r & 0x7F}")
    return f"g{r & 0x0F}"


def _reg_or_data(c: _Cmd, immediate: int, start: int) -> str:
    return str(c.bits(start, 16)) if immediate else _reg(c.bits(start - 8, 8))


def _compare(c: _Cmd, left: str, right: str) -> str:
    op = c.bits(54, 3)
    return f"if ({left} {CMP[op]} {right}) " if op else ""


def _if1(c: _Cmd) -> str:
    if not c.bits(54, 3):
        return ""
    return _compare(c, _reg(c.bits(39, 8)), _reg_or_data(c, c.bits(55, 1), 31))


def _if2(c: _Cmd) -> str:
    if not c.bits(54, 3):
        return ""
    return _compare(c, _reg(c.bits(15, 8)), _reg(c.bits(7, 8)))


def _if3(c: _Cmd) -> str:
    if not c.bits(54, 3):
        return ""
    return _compare(c, _reg(c.bits(43, 4)), _reg_or_data(c, c.bits(55, 1), 15))


def _if4(c: _Cmd) -> str:
    if not c.bits(54, 3):
        return ""
    return _compare(c, _reg(c.bits(51, 4)), _reg_or_data(c, c.bits(55, 1), 31))


def _if5(c: _Cmd) -> str:
    if not c.bits(54, 3):
        return ""
    if c.bits(60, 1):
        return _compare(c, _reg(c.bits(31, 8)), _reg(c.bits(23, 8)))
    return _compare(c, _reg(c.bits(39, 8)), _reg_or_data(c, c.bits(55, 1), 31))


def _button(c: _Cmd) -> str:
    b = c.bits(15, 6)
    return f" (button {b})" if b else ""


def _link_sub(c: _Cmd) -> str:
    op = c.bits(7, 8)
    name = LINKS.get(op)
    return f"{name}{_button(c)}" if name and op else ""


def _link(c: _Cmd, optional: bool) -> str:
    op = c.bits(51, 4)
    if op == 1:
        text = _link_sub(c)
    elif op == 4:
        text = f"LinkPGCN {c.bits(14, 15)}"
    elif op == 5:
        text = f"LinkPTTN {c.bits(9, 10)}{_button(c)}"
    elif op == 6:
        text = f"LinkPGN {c.bits(6, 7)}{_button(c)}"
    elif op == 7:
        text = f"LinkCN {c.bits(7, 8)}{_button(c)}"
    else:
        text = "" if optional else "Nop"
    return (", " if optional and text else "") + text


def _menu(n: int) -> str:
    return MENUS.get(n, f"menu {n}")


def _jump(c: _Cmd) -> str:
    op = c.bits(51, 4)
    if op == 1:
        return "Exit"
    if op == 2:
        return f"JumpTT {c.bits(22, 7)}"
    if op == 3:
        return f"JumpVTS_TT {c.bits(22, 7)}"
    if op == 5:
        return f"JumpVTS_PTT {c.bits(22, 7)}:{c.bits(41, 10)}"
    if op in (6, 8):
        kind = c.bits(23, 2)
        verb = "JumpSS" if op == 6 else "CallSS"
        resume = f", resume cell {c.bits(31, 8)}" if op == 8 else ""
        if kind == 0:
            return f"{verb} FP{resume}"
        if kind == 1:
            return f"{verb} VMGM {_menu(c.bits(19, 4))}{resume}"
        if kind == 2:
            if op == 8:
                return f"{verb} VTSM {_menu(c.bits(19, 4))}{resume}"
            return (f"{verb} VTSM (vts {c.bits(30, 7)}, title {c.bits(38, 7)}) "
                    f"{_menu(c.bits(19, 4))}")  # fmt: skip
        return f"{verb} VMGM pgc {c.bits(46, 15)}{resume}"
    return f"jump op {op}"


def _system_set(c: _Cmd) -> str:
    op = c.bits(59, 4)
    if op == 1:  # audio, subtitle, angle
        parts = []
        for i in (1, 2, 3):
            if c.bits(63 - (2 + i) * 8, 1):
                start = 47 - i * 8
                value = str(c.bits(start - 1, 7)) if c.bits(60, 1) else _reg(c.bits(start - 4, 4))
                parts.append(f"{SYSTEM[i]} = {value}")
        return "; ".join(parts)
    if op == 2:
        return f"timer = {_reg_or_data(c, c.bits(60, 1), 47)}; timer_pgc = {c.bits(14, 15)}"
    if op == 3:
        mode = "counter" if c.bits(23, 1) else "register"
        return f"g{c.bits(19, 4)} = {_reg_or_data(c, c.bits(60, 1), 47)} ({mode})"
    if op == 4:
        return f"karaoke = {_reg_or_data(c, c.bits(60, 1), 47)}"
    if op == 6:
        value = str(c.bits(31, 16)) if c.bits(60, 1) else _reg(c.bits(23, 8))
        return f"button = {value}"
    return f"system set {op}" if op else ""


def _set1(c: _Cmd) -> str:
    op = c.bits(59, 4)
    if not op:
        return ""
    return _assign(f"g{c.bits(35, 4)}", op, _reg_or_data(c, c.bits(60, 1), 31))


def _set2(c: _Cmd) -> str:
    op = c.bits(59, 4)
    if not op:
        return ""
    return _assign(f"g{c.bits(51, 4)}", op, _reg_or_data(c, c.bits(60, 1), 47))


def _set3(c: _Cmd) -> str:
    op = c.bits(59, 4)
    if not op:
        return ""
    value = str(c.bits(47, 16)) if c.bits(60, 1) else _reg(c.bits(39, 8))
    return _assign(f"g{c.bits(51, 4)}", op, value)


def _assign(target: str, op: int, value: str) -> str:
    if op == 8:
        return f"{target} = random({value})"
    return f"{target} {SET.get(op, f'op{op}')} {value}"


def _join(*parts: str) -> str:
    return ", ".join(p for p in parts if p)


def decode(raw: bytes) -> str:
    """One command as text, e.g. "if (g2 == 0) Goto 3" or "audio = 1, LinkPGCN 2"."""
    c = _Cmd(raw)
    group = c.bits(63, 3)
    if group == 0:
        op = c.bits(51, 4)
        special = {0: "Nop", 1: f"Goto {c.bits(7, 8)}", 2: "Break",
                   3: f"SetTmpPML {c.bits(11, 4)}, Goto {c.bits(7, 8)}"}  # fmt: skip
        special = special.get(op, f"special {op}")
        return _if1(c) + special
    if group == 1:
        if c.bits(60, 1):
            return _if2(c) + _jump(c)
        return _if1(c) + _link(c, optional=False)
    if group == 2:
        return _if2(c) + _system_set(c) + _link(c, optional=True)
    if group == 3:
        return _if3(c) + _set1(c) + _link(c, optional=True)
    if group == 4:
        return _join(_set2(c), _if4(c) + _link_sub(c))
    if group == 5:
        return _if5(c) + "{ " + _join(_set3(c), _link_sub(c)) + " }"
    if group == 6:
        return _if5(c) + "{ " + _set3(c) + " } " + _link_sub(c)
    return f"unknown {raw.hex()}"


def program(commands: list[bytes]) -> list[str]:
    """Numbered lines, as Goto counts them (from 1)."""
    return [f"{n:>3}  {decode(cmd)}" for n, cmd in enumerate(commands, start=1)]
