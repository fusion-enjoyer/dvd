"""A minimal PGS (.sup) writer for tests: FFmpeg can read PGS but not write it."""

from __future__ import annotations

import numpy as np


def _segment(kind: int, pts: float, body: bytes) -> bytes:
    t = round(pts * 90000).to_bytes(4, "big")
    return b"PG" + t + t + bytes([kind]) + len(body).to_bytes(2, "big") + body


def encode_rle(indices: np.ndarray) -> bytes:
    out = bytearray()
    for row in indices:
        x = 0
        while x < len(row):
            color, run = int(row[x]), 1
            while x + run < len(row) and row[x + run] == color and run < 16383:
                run += 1
            if color and run < 3:
                out += bytes([color]) * run
            elif color == 0:
                out += bytes([0, run]) if run < 64 else bytes([0, 0x40 | run >> 8, run & 0xFF])
            elif run < 64:
                out += bytes([0, 0x80 | run, color])
            else:
                out += bytes([0, 0xC0 | run >> 8, run & 0xFF, color])
            x += run
        out += b"\x00\x00"
    return bytes(out)


def display_set(pts: float, comp: int, objects: list[tuple[np.ndarray, int, int, bool]],
                width: int = 1920, height: int = 1080) -> bytes:  # fmt: skip
    """One display set; `objects`: (palette-index image, x, y, forced). Palette: 1 = white,
    2 = black, both opaque; 0 transparent. No objects: clears the screen."""
    placements = b""
    for i, (_img, x, y, forced) in enumerate(objects):
        placements += (i.to_bytes(2, "big") + b"\x00" + bytes([0x40 if forced else 0])
                       + x.to_bytes(2, "big") + y.to_bytes(2, "big"))  # fmt: skip
    # frame rate 0x10, composition number, state 0x80 (epoch start), no palette update, palette 0
    pcs = (width.to_bytes(2, "big") + height.to_bytes(2, "big") + b"\x10"
           + comp.to_bytes(2, "big") + b"\x80\x00\x00" + bytes([len(objects)])
           + placements)  # fmt: skip
    data = _segment(0x16, pts, pcs)
    if objects:
        data += _segment(0x17, pts, b"\x01\x00" + b"\x00\x00\x00\x00" + (width).to_bytes(2, "big")
                         + (height).to_bytes(2, "big"))  # fmt: skip
        palette = b"\x00\x00" + bytes([1, 235, 128, 128, 255, 2, 16, 128, 128, 255])
        data += _segment(0x14, pts, palette)
        for i, (img, _x, _y, _f) in enumerate(objects):
            rle = encode_rle(img)
            h, w = img.shape
            body = (i.to_bytes(2, "big") + b"\x00\xc0" + (len(rle) + 4).to_bytes(3, "big")
                    + w.to_bytes(2, "big") + h.to_bytes(2, "big") + rle)  # fmt: skip
            data += _segment(0x15, pts, body)
    return data + _segment(0x80, pts, b"")


def caption(width: int = 400, height: int = 60) -> np.ndarray:
    """A white bar with a 4-pixel black border, as palette indices."""
    img = np.full((height, width), 2, np.uint8)
    img[4:-4, 4:-4] = 1
    return img
