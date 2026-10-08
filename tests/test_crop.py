import subprocess
from pathlib import Path

import numpy as np
import pytest

from dvd import toolchain
from dvd.probe import probe
from dvd.project.model import Crop
from dvd.video.crop import bars_in_frame, detect_crop

FFMPEG = toolchain.find_executable(["ffmpeg.exe", "ffmpeg"], toolchain.tool_dirs())
needs_ffmpeg = pytest.mark.skipif(FFMPEG is None, reason="ffmpeg not installed")


def make(tmp_path: Path, name: str, graph: str, seconds: int = 4) -> Path:
    out = tmp_path / name
    subprocess.run(
        [str(FFMPEG), "-v", "error", "-y", "-f", "lavfi",
         "-i", f"testsrc2=size=1920x804:rate=25:duration={seconds}",
         "-vf", graph, "-c:v", "libx264", "-preset", "ultrafast", "-crf", "30", str(out)],
        check=True,
    )  # fmt: skip
    return out


def test_bars_in_a_clean_frame():
    luma = np.full((100, 200), 16.0)
    luma[10:90, 20:180] = 120.0
    assert bars_in_frame(luma, 16, 235) == (20, 20, 10, 10)


def test_grain_in_the_bar_still_counts_as_black():
    rng = np.random.default_rng(1)
    luma = 16 + rng.normal(0, 2, (100, 200))
    luma[10:90] = 120.0
    assert bars_in_frame(luma, 16, 235)[2:] == (10, 10)


@needs_ffmpeg
def test_letterboxed_film(tmp_path: Path):
    src = make(tmp_path, "kapsam.mkv", "pad=1920:1080:0:138:black")
    assert detect_crop(src, probe(src).main_video) == Crop(top=138, bottom=138)


@needs_ffmpeg
def test_pillarboxed_4_3(tmp_path: Path):
    src = make(tmp_path, "dort-uc.mkv", "scale=1440:1080,pad=1920:1080:240:0:black")
    assert detect_crop(src, probe(src).main_video) == Crop(left=240, right=240)


@needs_ffmpeg
def test_dark_frames_are_ignored(tmp_path: Path):
    # First half of the film is black: those samples say nothing about the bars.
    src = make(tmp_path, "karanlik.mkv",
               "pad=1920:1080:0:138:black,"
               "drawbox=x=0:y=0:w=iw:h=ih:color=black:t=fill:enable='lt(t,2)'")  # fmt: skip
    assert detect_crop(src, probe(src).main_video) == Crop(top=138, bottom=138)


@needs_ffmpeg
def test_full_frame_picture_has_no_bars(tmp_path: Path):
    src = make(tmp_path, "tam.mkv", "scale=1920:1080")
    assert detect_crop(src, probe(src).main_video) == Crop()


@needs_ffmpeg
def test_black_video_gives_no_answer(tmp_path: Path):
    src = make(tmp_path, "siyah.mkv", "pad=1920:1080:0:138:black,lutyuv=y=16")
    assert detect_crop(src, probe(src).main_video) is None
