"""Pre-processing settings resolved from the profile layers (docs/profiller.md).

Values here are starting points; Phase 2 calibrates them against the test corpus and reference
discs. A project can override any of them under `video.overrides`:
    deband: 0..4, dither: error_diffusion | ordered | none, kernel: spline36 | lanczos | bicubic
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from dvd.project.model import Profiles

KERNELS = ("spline36", "lanczos", "bicubic")
DITHERS = ("error_diffusion", "ordered", "none")

# Deband level -> (range in pixels, threshold on the 8-bit scale). 2 is neo_f3kdb's default.
DEBAND = {0: None, 1: (15, 0.75), 2: (15, 1.0), 3: (20, 1.5), 4: (24, 2.0)}

CONTENT_DEBAND = {
    "modern-film": 1, "grenli-film": 1, "eski-film": 1, "animasyon-2d": 3, "animasyon-3d": 3,
    "dizi": 1, "yayin": 1, "icerik-4-3": 1, "telefon": 1, "kamera": 1, "eski-kamera": 1,
    "ekran-kaydi": 2,
}  # fmt: skip
# Big screens show every band, CRTs and small screens hide them.
VIEWING_DEBAND = {"projeksiyon": +1, "crt": -1, "tasinabilir": -1}


@dataclass(frozen=True)
class Preprocess:
    deband: int = 1
    dither: str = "error_diffusion"
    kernel: str = "spline36"
    source: dict[str, str] | None = None  # which layer set each value, for the UI

    @property
    def deband_args(self) -> tuple[int, float] | None:
        return DEBAND[self.deband]


def resolve(profiles: Profiles, overrides: dict[str, Any]) -> Preprocess:
    deband = CONTENT_DEBAND.get(profiles.content, 1)
    origin = {"deband": f"content:{profiles.content}"}
    shift = VIEWING_DEBAND.get(profiles.viewing, 0)
    if shift:
        deband = min(4, max(0, deband + shift))
        origin["deband"] = f"viewing:{profiles.viewing}"
    dither, kernel = "error_diffusion", "spline36"
    origin |= {"dither": "default", "kernel": "default"}
    if "deband" in overrides:
        deband, origin["deband"] = int(overrides["deband"]), "override"
        if deband not in DEBAND:
            raise ValueError(f"deband must be 0..4, not {deband}")
    if "dither" in overrides:
        dither, origin["dither"] = str(overrides["dither"]), "override"
        if dither not in DITHERS:
            raise ValueError(f"dither must be one of {', '.join(DITHERS)}")
    if "kernel" in overrides:
        kernel, origin["kernel"] = str(overrides["kernel"]), "override"
        if kernel not in KERNELS:
            raise ValueError(f"kernel must be one of {', '.join(KERNELS)}")
    return Preprocess(deband, dither, kernel, origin)
