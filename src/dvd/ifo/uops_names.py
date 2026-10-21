"""Names of the bits of a user operation mask (see `dvd.author.uops`)."""

from __future__ import annotations

from dvd.author.uops import UOP_BITS


def uop_names(mask: int) -> list[str]:
    return [name for name, bit in sorted(UOP_BITS.items(), key=lambda kv: kv[1])
            if mask & (1 << bit)]  # fmt: skip
