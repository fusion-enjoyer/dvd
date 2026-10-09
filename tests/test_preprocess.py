import subprocess
from pathlib import Path

import numpy as np
import pytest

from dvd import toolchain
from dvd.probe import probe
from dvd.project.model import Profiles, Video
from dvd.video.pipeline import build_clip, plan_target
from dvd.video.preprocess import Preprocess, resolve

FFMPEG = toolchain.find_executable(["ffmpeg.exe", "ffmpeg"], toolchain.tool_dirs())


def test_content_profile_sets_deband():
    assert resolve(Profiles(content="modern-film"), {}).deband == 1
    assert resolve(Profiles(content="animasyon-2d"), {}).deband == 3


def test_viewing_profile_shifts_deband():
    p = resolve(Profiles(content="animasyon-2d", viewing="projeksiyon"), {})
    assert p.deband == 4 and p.source["deband"] == "viewing:projeksiyon"
    assert resolve(Profiles(content="modern-film", viewing="crt"), {}).deband == 0


def test_overrides_win_and_are_validated():
    p = resolve(Profiles(), {"deband": 0, "dither": "ordered", "kernel": "lanczos"})
    assert (p.deband, p.dither, p.kernel) == (0, "ordered", "lanczos")
    assert {k: p.source[k] for k in ("deband", "dither", "kernel")} == dict.fromkeys(
        ("deband", "dither", "kernel"), "override"
    )
    assert p.side_fill == "black" and p.source["side_fill"] == "default"
    with pytest.raises(ValueError):
        resolve(Profiles(), {"deband": 9})
    with pytest.raises(ValueError):
        resolve(Profiles(), {"kernel": "nearest"})


def mean_flat_run(row: np.ndarray) -> float:
    """Average length of runs of identical neighbouring values: long runs are visible bands."""
    changes = np.flatnonzero(np.diff(row.astype(int)) != 0)
    return len(row) / (len(changes) + 1)


@pytest.mark.skipif(FFMPEG is None, reason="ffmpeg not installed")
def test_deband_and_dither_break_up_a_banded_gradient(tmp_path: Path):
    src = tmp_path / "bant.mkv"
    # A dark, shallow gradient: 16 code values over 1920 pixels, 120-pixel steps.
    subprocess.run(
        [str(FFMPEG), "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=black:s=1920x1080:d=1",
         "-vf", "format=yuv420p,geq=lum='40+16*X/W':cb=128:cr=128", "-c:v", "ffv1", str(src)],
        check=True,
    )  # fmt: skip
    v = probe(src).main_video
    target = plan_target(v, "pal", Video(crop="none"))

    def middle_row(pre: Preprocess) -> np.ndarray:
        clip = build_clip(src, v, target, Video(crop="none"), pre)
        with clip.get_frame(0) as f:
            return np.asarray(f[0])[288, 40:680].copy()

    banded = middle_row(Preprocess(deband=0, dither="none"))
    smooth = middle_row(Preprocess(deband=2, dither="error_diffusion"))
    assert mean_flat_run(banded) > 25  # wide flat steps
    assert mean_flat_run(smooth) < 5  # steps broken into fine noise
    assert abs(float(smooth.mean()) - float(banded.mean())) < 1.0  # brightness unchanged
