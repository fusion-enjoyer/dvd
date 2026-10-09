"""Pre-processing settings for the video chain, resolved through `dvd.profiles`.

A title can override them under `video.overrides`:
    deband: 0..4, dither: error_diffusion | ordered | none, kernel: spline36 | lanczos | bicubic,
    side_fill: black | blur (what fills the side bars of narrow, e.g. portrait, video)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from dvd.project.model import Profiles

KERNELS = ("spline36", "lanczos", "bicubic")
DITHERS = ("error_diffusion", "ordered", "none")

# Deband level -> (range in pixels, threshold on the 8-bit scale). 2 is neo_f3kdb's default.
DEBAND = {0: None, 1: (15, 0.75), 2: (15, 1.0), 3: (20, 1.5), 4: (24, 2.0)}


@dataclass(frozen=True)
class Preprocess:
    deband: int = 1
    dither: str = "error_diffusion"
    kernel: str = "spline36"
    side_fill: str = "black"
    source: dict[str, str] | None = None  # which layer set each value, for the UI

    @property
    def deband_args(self) -> tuple[int, float] | None:
        return DEBAND[self.deband]


def resolve(profiles: Profiles, overrides: dict[str, Any]) -> Preprocess:
    """Pre-processing for a title from the profile layers and its overrides."""
    from dvd import profiles as layers

    try:
        r = layers.resolve(profiles, overrides)
    except layers.ProfileError as exc:
        raise ValueError(str(exc)) from None
    keys = ("deband", "dither", "kernel", "side_fill")
    return Preprocess(*(r[k] for k in keys), {k: r.origin[k] for k in keys})
