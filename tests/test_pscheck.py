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


def test_video_that_arrives_too_early_overflows_the_decoder_buffer(tmp_path: Path):
    from dvd.author.psmux import PACK_TIME, _ts, pack_header

    def video_pack(scr: int, dts: int | None) -> bytes:
        stamp = (_ts(dts, 3) + _ts(dts, 1)) if dts is not None else b""
        flags = 0xC0 if stamp else 0
        body = bytes(2048 - 14 - 9 - len(stamp))
        pes = b"\x00\x00\x01\xe0" + (3 + len(stamp) + len(body)).to_bytes(2, "big") \
            + bytes([0x80, flags, len(stamp)]) + stamp + body  # fmt: skip
        return pack_header(scr) + pes

    # One 300 KB picture, all of it sent long before its decode time 10 s later.
    packs = [video_pack(k * PACK_TIME, 900_000 if k == 0 else None) for k in range(150)]
    path = tmp_path / "early.mpg"
    path.write_bytes(b"".join(packs))
    report = check(path)
    assert report.streams["video"].peak_fill > 290 * 1024
    assert any("decoder buffer holds up to" in e for e in report.errors)


def test_two_streams_one_after_the_other_are_checked_each_on_its_own(tmp_path: Path):
    """Intros and hidden clips are muxed one by one and share a VOB: the clock starts again."""
    one = dvd_mpg(tmp_path, "one.mpg", ["-b:v", "6M", "-maxrate", "8M", "-bufsize", "1835k"])
    single = check(one)
    both = tmp_path / "both.mpg"
    both.write_bytes(one.read_bytes() * 2)
    report = check(both)
    assert report.ok, report.errors
    assert report.peak_bps == single.peak_bps
    assert report.streams["video"].peak_fill == single.streams["video"].peak_fill
