import subprocess
from fractions import Fraction
from pathlib import Path

import pytest

from dvd import toolchain
from dvd.audio.ac3 import encode_ac3, ffmpeg_args
from dvd.probe import probe

FFMPEG = toolchain.find_executable(["ffmpeg.exe", "ffmpeg"], toolchain.tool_dirs())
PAL_SPEEDUP = Fraction(25025, 24000)


def test_args_for_pal_speedup_keep_pitch():
    args = ffmpeg_args(Path("in.mkv"), 2, Path("o.ac3"), "5.1", 448, PAL_SPEEDUP)
    assert args[args.index("-map") + 1] == "0:2"
    assert args[args.index("-ac") + 1] == "6"
    assert args[args.index("-ar") + 1] == "48000"
    assert args[args.index("-af") + 1].startswith("atempo=1.04270833")


def test_args_without_speedup_have_no_filter():
    args = ffmpeg_args(Path("in.mkv"), 1, Path("o.ac3"), "2.0", 192)
    assert "-af" not in args and args[args.index("-b:a") + 1] == "192k"


@pytest.mark.skipif(FFMPEG is None, reason="ffmpeg not installed")
def test_71_source_to_51_ac3_with_pal_speedup(tmp_path: Path):
    src = tmp_path / "ses kaynağı.mkv"
    subprocess.run(
        [
            str(FFMPEG), "-v", "error", "-y", "-f", "lavfi",
            "-i", "sine=frequency=440:sample_rate=44100:duration=10.01",
            "-ac", "8", "-c:a", "flac", str(src),
        ],
        check=True,
    )  # fmt: skip
    out = encode_ac3(src, 0, tmp_path / "ses.ac3", "5.1", 448, PAL_SPEEDUP)
    a = probe(out).audio[0]
    assert (a.codec, a.channels, a.sample_rate) == ("ac3", 6, 48000)
    assert probe(out).duration == pytest.approx(10.01 / float(PAL_SPEEDUP), abs=0.1)
