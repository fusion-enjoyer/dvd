"""Soft pulldown: turn a 23.976 fps progressive MPEG-2 stream into a 29.97 fps DVD stream by
setting flags, without re-encoding.

The film frames stay as they are; the player repeats fields in the 2:3 pattern. Per picture,
in display order, (top_field_first, repeat_first_field) cycles through (1,1) (0,0) (0,1) (1,0):
four film frames become ten fields, five video frames. The edits, all in place and of the same
size, are:
  - sequence header: frame_rate_code 1 (23.976) -> 4 (29.97);
  - sequence extension: progressive_sequence -> 0 (DVD-Video requires 0);
  - picture coding extension: top_field_first and repeat_first_field from the pattern,
    progressive_frame and chroma_420_type = 1 (required with repeat_first_field);
  - GOP header: time code counted in 29.97 frames (non-drop).
The stream must be coded as frame pictures with frame_pred_frame_dct = 1, which is what an
encoder writes for progressive input.
"""

from __future__ import annotations

import mmap
import re
from dataclasses import dataclass
from pathlib import Path

PATTERN = ((1, 1), (0, 0), (0, 1), (1, 0))  # (top_field_first, repeat_first_field)
_HEADER = re.compile(rb"\x00\x00\x01[\x00\xb3\xb5\xb8]")


class PulldownError(ValueError):
    pass


@dataclass
class _Picture:
    gop: int
    temporal_reference: int
    ext: int = -1  # offset of the picture coding extension start code


def _fields(display_index: int) -> int:
    return 3 if PATTERN[display_index % 4][1] else 2


def _time_code(fields: int) -> int:
    """25-bit GOP time code for a position given in fields, 30 frames per second, non-drop."""
    frames = fields // 2
    seconds, pictures = divmod(frames, 30)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return ((hours % 24) << 19) | (minutes << 13) | (1 << 12) | (seconds << 6) | pictures


def inject(path: Path) -> int:
    """Apply soft pulldown flags to `path` in place. Returns the number of pictures."""
    with path.open("r+b") as f, mmap.mmap(f.fileno(), 0) as data:
        pictures: list[_Picture] = []
        gops: list[int] = []  # offsets of GOP headers
        sequences: list[int] = []
        seq_exts: list[int] = []
        current: _Picture | None = None
        for m in _HEADER.finditer(data):
            pos, code = m.start(), data[m.start() + 3]
            if code == 0xB3:
                sequences.append(pos)
                current = None
            elif code == 0xB8:
                gops.append(pos)
                current = None
            elif code == 0x00:
                tr = (data[pos + 4] << 2) | (data[pos + 5] >> 6)
                current = _Picture(max(len(gops) - 1, 0), tr)
                pictures.append(current)
            elif code == 0xB5:
                ext = data[pos + 4] >> 4
                if ext == 1 and current is None:
                    seq_exts.append(pos)
                elif ext == 8 and current is not None and current.ext < 0:
                    current.ext = pos
        if not sequences or not pictures:
            raise PulldownError(f"{path.name} is not an MPEG-2 video stream")
        for pos in sequences:
            if data[pos + 7] & 0x0F != 1:
                raise PulldownError("soft pulldown needs a 23.976 fps stream")
        if any(p.ext < 0 for p in pictures):
            raise PulldownError("an MPEG-1 stream cannot carry pulldown flags")

        # Display index of each picture: pictures in earlier GOPs plus temporal_reference.
        per_gop: dict[int, int] = {}
        for p in pictures:
            per_gop[p.gop] = per_gop.get(p.gop, 0) + 1
        gop_start, total = {}, 0
        for g in sorted(per_gop):
            gop_start[g] = total
            total += per_gop[g]

        for p in pictures:
            e = p.ext
            if (data[e + 6] & 0x03) != 3:
                raise PulldownError("soft pulldown needs frame pictures, found field pictures")
            if not data[e + 7] & 0x40:
                raise PulldownError("soft pulldown needs frame_pred_frame_dct = 1 (progressive)")
            tff, rff = PATTERN[(gop_start[p.gop] + p.temporal_reference) % 4]
            b7 = data[e + 7] & ~0x80 & ~0x02  # clear top_field_first, repeat_first_field
            data[e + 7] = b7 | (tff << 7) | (rff << 1) | 0x01  # chroma_420_type = 1
            data[e + 8] |= 0x80  # progressive_frame = 1
        for pos in sequences:
            data[pos + 7] = (data[pos + 7] & 0xF0) | 4
        for pos in seq_exts:
            data[pos + 5] &= ~0x08 & 0xFF  # progressive_sequence = 0
        fields = 0
        for g, pos in enumerate(gops):
            word = int.from_bytes(data[pos + 4 : pos + 8], "big")
            word = (word & 0x7F) | (_time_code(fields) << 7)  # keep closed_gop, broken_link
            data[pos + 4 : pos + 8] = word.to_bytes(4, "big")
            start = gop_start.get(g, 0)
            fields += sum(_fields(start + i) for i in range(per_gop.get(g, 0)))
        data.flush()
    return len(pictures)
