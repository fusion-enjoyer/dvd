import subprocess
import sys
from pathlib import Path

import pytest

from dvd import toolchain
from dvd.video.compliance import check, parse

sys.path.insert(0, str(Path(__file__).parent))

DIRS = toolchain.tool_dirs()
FFMPEG = toolchain.find_executable(["ffmpeg.exe", "ffmpeg"], DIRS)
HCENC_READY = all(toolchain.find_executable([p], DIRS) for p in ("HCenc_*.exe", "DvdSource.dll"))
needs_ffmpeg = pytest.mark.skipif(FFMPEG is None, reason="ffmpeg not installed")


def ffmpeg_m2v(tmp_path: Path, name: str, *opts: str, size="720x576", rate="25") -> Path:
    out = tmp_path / name
    subprocess.run(
        [str(FFMPEG), "-v", "error", "-y", "-f", "lavfi",
         "-i", f"testsrc2=size={size}:rate={rate}:duration=4",
         "-c:v", "mpeg2video", "-aspect", "16:9", *opts, "-f", "mpeg2video", str(out)],
        check=True,
    )  # fmt: skip
    return out


@needs_ffmpeg
def test_parses_headers_and_picture_sizes(tmp_path: Path):
    m2v = ffmpeg_m2v(tmp_path, "a.m2v", "-g", "12", "-bf", "2", "-b:v", "5M")
    info = parse(m2v)
    assert (info.width, info.height, info.aspect_code) == (720, 576, 3)
    assert len(info.pictures) == 100
    assert sum(info.gops) == 100 and max(info.gops) <= 12
    assert sum(p.bits for p in info.pictures) == m2v.stat().st_size * 8
    assert info.pictures[0].kind == "I"


@pytest.mark.skipif(not HCENC_READY, reason="HCEnc not installed")
def test_hcenc_output_is_compliant(tmp_path: Path):
    from test_frameserver import pattern_clip

    from dvd.video.hcenc import EncodeSettings, encode

    settings = EncodeSettings(7000, 9000, "16:9", "pal", profile="fast")
    m2v = encode(pattern_clip(100), tmp_path / "v.m2v", settings, tmp_path / "w")
    report = check(m2v, "pal")
    assert report.ok, report.errors
    assert report.peak_bps <= 9_800_000


@needs_ffmpeg
def test_long_gop_and_three_b_frames_are_errors(tmp_path: Path):
    m2v = ffmpeg_m2v(tmp_path, "b.m2v", "-g", "30", "-bf", "3", "-b:v", "5M")
    errors = " | ".join(check(m2v, "pal").errors)
    assert "longer than 15 pictures" in errors
    assert "3 consecutive B-pictures" in errors


@needs_ffmpeg
def test_bitrate_peak_over_one_second_is_an_error(tmp_path: Path):
    m2v = ffmpeg_m2v(tmp_path, "c.m2v", "-vf", "noise=alls=80:allf=t+u", "-g", "12", "-bf", "2",
                     "-q:v", "2", "-maxrate", "15M", "-bufsize", "1835k")  # fmt: skip
    report = check(m2v, "pal")
    errors = " | ".join(report.errors)
    assert "over one second" in errors
    assert report.peak_bps > 9_800_000


def test_vbv_simulation_finds_underflow():
    from fractions import Fraction

    from dvd.video.compliance import Picture, StreamInfo, _vbv

    info = StreamInfo(frame_rate=Fraction(25), bit_rate=9_000_000, vbv_bits=1_835_008)
    # 9 Mbps refills 360 kbit per frame; a run of 1.2 Mbit pictures drains the buffer.
    info.pictures = [Picture("I", 1_200_000, 2) for _ in range(10)]
    lowest, underflows = _vbv(info)
    assert underflows > 0 and lowest < 0.5
    info.pictures = [Picture("P", 300_000, 2) for _ in range(50)]
    assert _vbv(info)[1] == 0


@needs_ffmpeg
def test_wrong_size_and_standard(tmp_path: Path):
    m2v = ffmpeg_m2v(tmp_path, "d.m2v", "-g", "12", "-b:v", "4M", size="640x360")
    errors = " | ".join(check(m2v, "pal").errors)
    assert "640x360 is not a DVD PAL size" in errors
    ntsc = ffmpeg_m2v(tmp_path, "e.m2v", "-g", "12", "-b:v", "4M", rate="25")
    assert "frame rate 25.000 is not 29.970" in " | ".join(check(ntsc, "ntsc").errors)


def test_not_mpeg_video(tmp_path: Path):
    bad = tmp_path / "x.m2v"
    bad.write_bytes(b"\x00" * 4096)
    with pytest.raises(ValueError):
        parse(bad)
