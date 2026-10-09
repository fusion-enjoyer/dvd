"""HDR (PQ / HLG, BT.2020) -> SDR (BT.709 primaries, gamma) for DVD, inside VapourSynth.

zimg turns the signal into linear light in BT.709 primaries (1.0 = 100 nits for both PQ and
HLG); the BT.2390 EETF then compresses the source's peak brightness into the SDR range. The
curve is applied to max(R, G, B) and all three channels are scaled by the same factor, so hues
do not shift. Colours outside BT.709 are clipped. Everything runs on the already downscaled
picture, in 32-bit float.

Starting values, to be checked against the test corpus: SDR peak 100 nits; source peak from
the stream's MaxCLL / mastering display, else 1000 nits (also HLG's nominal peak).
"""

from __future__ import annotations

import vapoursynth as vs

core = vs.core

M1, M2 = 0.1593017578125, 78.84375
C1, C2, C3 = 0.8359375, 18.8515625, 18.6875
SDR_PEAK = 100.0  # nits
DEFAULT_PEAK = 1000.0
TRANSFERS = {"smpte2084": "st2084", "arib-std-b67": "std-b67"}


def pq(nits: float) -> float:
    """PQ signal (0..1) for an absolute luminance."""
    y = (nits / 10000) ** M1
    return ((C1 + C2 * y) / (1 + C3 * y)) ** M2


def _pq_rpn(x: str) -> str:
    """RPN for pq() of `x` given in nits."""
    y = f"{x} 0.0001 * {M1} pow"
    return f"{C1} {C2} {y} * + 1 {C3} {y} * + / {M2} pow"


def _pq_inverse_rpn(e: str) -> str:
    """RPN for the luminance in nits of PQ signal `e`."""
    p = f"{e} 0 max {1 / M2} pow"
    return f"{p} {C1} - 0 max {C2} {C3} {p} * - / {1 / M1} pow 10000 *"


def eetf(source_peak: float, target_peak: float = SDR_PEAK) -> tuple[float, float, list[float]]:
    """BT.2390 constants: (pq of source peak, knee start KS, Hermite polynomial in T, high
    power first). Below KS the curve is the identity in normalised PQ."""
    pw = pq(source_peak)
    max_lum = pq(target_peak) / pw
    ks = max(0.0, 1.5 * max_lum - 0.5)
    # P(T) = (2T³-3T²+1)KS + (T³-2T²+T)(1-KS) + (-2T³+3T²)maxLum, expanded.
    coeffs = [2 * ks + (1 - ks) - 2 * max_lum, -3 * ks - 2 * (1 - ks) + 3 * max_lum, 1 - ks, ks]
    return pw, ks, coeffs


def eetf_nits(nits: float, source_peak: float, target_peak: float = SDR_PEAK) -> float:
    """Reference implementation of the curve, for tests."""
    pw, ks, (a3, a2, a1, a0) = eetf(source_peak, target_peak)
    e1 = min(1.0, pq(nits) / pw)
    if e1 >= ks:
        t = (e1 - ks) / (1 - ks)
        e1 = ((a3 * t + a2) * t + a1) * t + a0
    e = (e1 * pw) ** (1 / M2)
    return (max(e - C1, 0) / (C2 - C3 * e)) ** (1 / M1) * 10000


def tonemap(
    clip: vs.VideoNode,
    transfer: str,
    out_matrix: str,
    out_format: int,
    source_peak: float | None = None,
    range_in: str = "limited",
) -> vs.VideoNode:
    """`clip`: YUV in BT.2020 non-constant luminance with `transfer` (ffprobe name).
    Returns `out_format` YUV with `out_matrix`, limited range, gamma for a BT.1886 display
    (zimg is display-referred by default)."""
    peak = source_peak or DEFAULT_PEAK
    if transfer == "arib-std-b67":
        peak = DEFAULT_PEAK  # HLG's nominal display peak; zimg maps signal 1.0 to it
    rgb = core.resize.Bicubic(
        clip, format=vs.RGBS, matrix_in_s="2020ncl", range_in_s=range_in,
        transfer_in_s=TRANSFERS[transfer], transfer_s="linear",
        primaries_in_s="2020", primaries_s="709",
    )  # fmt: skip
    planes = [core.std.ShufflePlanes(rgb, i, vs.GRAY) for i in range(3)]
    planes = [core.std.Expr(p, "x 0 max") for p in planes]  # out of BT.709 gamut: clip
    # Brightest channel in nits (1.0 = 100 nits).
    level = core.std.Expr(planes, "x y max z max 100 * 0.0001 max")
    if peak > SDR_PEAK:
        pw, ks, (a3, a2, a1, a0) = eetf(peak)
        # Constants are applied as products: std.Expr (R81) returned 0 for "<pow ...> c /".
        e1 = f"{_pq_rpn('x')} {1 / pw} * 1 min"
        t = f"{e1} {ks} - {1 / (1 - ks)} *"
        curve = f"{e1} {ks} < {e1} {t} {a3} * {a2} + {t} * {a1} + {t} * {a0} + ?"
        mapped = core.std.Expr(level, f"{_pq_inverse_rpn(f'{curve} {pw} *')}")
    else:
        mapped = level
    out = [core.std.Expr([p, level, mapped], "x z * y /") for p in planes]
    rgb = core.std.ShufflePlanes(out, [0, 0, 0], vs.RGB)
    return core.resize.Bicubic(
        rgb, format=out_format, matrix_s=out_matrix, range_s="limited",
        transfer_in_s="linear", transfer_s="709", primaries_in_s="709", primaries_s="709",
    )  # fmt: skip
