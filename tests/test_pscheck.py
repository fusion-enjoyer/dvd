import subprocess
from pathlib import Path

import pytest

from dvd import toolchain
from dvd.author.pscheck import check

FFMPEG = toolchain.find_executable(["ffmpeg.exe", "ffmpeg"], toolchain.tool_dirs())
pytestmark = pytest.mark.skipif(FFMPEG is None, reason="ffmpeg not installed")


DVD_RATE = ("-muxrate", "10080000")


def dvd_mpg(tmp_path: Path, name: str, video_opts: list[str], mux_opts=DVD_RATE) -> Path:
    out = tmp_path / name
    subprocess.run(
        [str(FFMPEG), "-v", "error", "-y",
         "-f", "lavfi", "-i", "testsrc2=size=720x576:rate=25:duration=4",
         "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=4",
         "-c:v", "mpeg2video", "-g", "12", "-bf", "2", *video_opts,
         "-c:a", "ac3", "-b:a", "448k", *mux_opts, "-f", "dvd", str(out)],
        check=True,
    )  # fmt: skip
    return out


def test_normal_mux_is_ok(tmp_path: Path):
    r = check(dvd_mpg(tmp_path, "a.mpg", ["-b:v", "5M", "-maxrate", "8M", "-bufsize", "1835k"]))
    assert r.ok, r.errors
    assert r.max_mux_rate == 10_080_000
    assert set(r.streams) == {"video", "ac3-0"}
    assert r.duration == pytest.approx(4, abs=0.5)
    assert r.streams["ac3-0"].bytes == pytest.approx(448_000 / 8 * 4, rel=0.1)


def test_too_much_data_arrives_late(tmp_path: Path):
    noisy = ["-vf", "noise=alls=80:allf=t+u", "-q:v", "2", "-maxrate", "15M", "-bufsize", "1835k"]
    r = check(dvd_mpg(tmp_path, "b.mpg", noisy))
    assert any("after their decode time" in e for e in r.errors), r.errors


def test_declared_mux_rate_above_dvd_limit(tmp_path: Path):
    r = check(dvd_mpg(tmp_path, "c.mpg", ["-b:v", "5M"], ["-muxrate", "20000000"]))
    assert any("declared mux rate" in e for e in r.errors), r.errors


def test_not_a_program_stream(tmp_path: Path):
    junk = tmp_path / "d.mpg"
    junk.write_bytes(b"\x00" * 4096)
    assert "do not start with a pack header" in " ".join(check(junk).errors)
