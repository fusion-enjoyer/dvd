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


def test_args_for_pal_speedup_raise_pitch():
    args = ffmpeg_args(Path("in.mkv"), 1, Path("o.ac3"), "2.0", 192, PAL_SPEEDUP, "raise")
    assert args[args.index("-af") + 1] == "aresample=48000,asetrate=50050.0000,aresample=48000"


def _main_frequency(ac3: Path) -> float:
    import numpy as np

    pcm = subprocess.run(
        [str(FFMPEG), "-v", "error", "-i", str(ac3), "-ac", "1", "-f", "f32le", "-"],
        capture_output=True, check=True,
    ).stdout  # fmt: skip
    x = np.frombuffer(pcm, dtype=np.float32)[48000:96000]  # one second from the middle
    spectrum = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    return float(np.argmax(spectrum)) * 48000 / len(x)


@pytest.mark.skipif(FFMPEG is None, reason="ffmpeg not installed")
@pytest.mark.parametrize(("pitch", "hz"), [("keep", 440.0), ("raise", 440.0 * 25025 / 24000)])
def test_pal_speedup_pitch(tmp_path: Path, pitch: str, hz: float):
    src = tmp_path / "ton.flac"
    subprocess.run(
        [str(FFMPEG), "-v", "error", "-y", "-f", "lavfi",
         "-i", "sine=frequency=440:sample_rate=44100:duration=4", str(src)],
        check=True,
    )  # fmt: skip
    out = encode_ac3(src, 0, tmp_path / "ton.ac3", "2.0", 192, PAL_SPEEDUP, pitch)
    assert probe(out).duration == pytest.approx(4 / float(PAL_SPEEDUP), abs=0.1)
    assert _main_frequency(out) == pytest.approx(hz, abs=2)


def _track(**kw):
    from dvd.probe import AudioTrack

    base = {"index": 1, "codec": "ac3", "channels": 6, "sample_rate": 48000, "bitrate": 448000}
    return AudioTrack(**{**base, **kw})


def test_dvd_ready_ac3_is_copied_only_when_nothing_changes():
    from dvd.audio.ac3 import can_copy

    assert can_copy(_track(), "5.1")
    assert not can_copy(_track(bitrate=640000), "5.1")  # Blu-ray AC-3 is above the DVD limit
    assert not can_copy(_track(codec="eac3"), "5.1")
    assert not can_copy(_track(), "2.0")  # needs a downmix
    assert not can_copy(_track(), "5.1", speedup=PAL_SPEEDUP)
    assert not can_copy(_track(), "5.1", delay_ms=120)
    assert not can_copy(_track(), "5.1", night=True)
    assert can_copy(_track(channels=2, bitrate=192000), "2.0")


def test_args_for_downmix_night_and_delay():
    args = ffmpeg_args(Path("i.mkv"), 1, Path("o.ac3"), "2.0", 192, delay_ms=250, night=True,
                       source_channels=6)  # fmt: skip
    af = args[args.index("-af") + 1]
    assert af.startswith("adelay=delays=250:all=1,")
    assert "matrix_encoding=dplii" in af and "acompressor" in af
    assert args[args.index("-dsur_mode") + 1] == "on"
    cut = ffmpeg_args(Path("i.mkv"), 1, Path("o.ac3"), "5.1", 448, delay_ms=-1500)
    assert cut[cut.index("-af") + 1] == "atrim=start=1.500,asetpts=PTS-STARTPTS"
    copy = ffmpeg_args(Path("i.mkv"), 1, Path("o.ac3"), "5.1", 448, copy=True)
    assert copy[copy.index("-c:a") + 1] == "copy" and "-af" not in copy


@pytest.mark.skipif(FFMPEG is None, reason="ffmpeg not installed")
def test_copied_track_is_bit_identical(tmp_path: Path):
    src = tmp_path / "ac3.mkv"
    subprocess.run(
        [str(FFMPEG), "-v", "error", "-y", "-f", "lavfi",
         "-i", "sine=frequency=440:sample_rate=48000:duration=3",
         "-ac", "6", "-c:a", "ac3", "-b:a", "448k", str(src)],
        check=True,
    )  # fmt: skip
    out = encode_ac3(src, 0, tmp_path / "out.ac3", "5.1", 448, copy=True)
    ref = tmp_path / "ref.ac3"
    subprocess.run([str(FFMPEG), "-v", "error", "-y", "-i", str(src), "-c", "copy", str(ref)],
                   check=True)  # fmt: skip
    assert out.read_bytes() == ref.read_bytes()


@pytest.mark.skipif(FFMPEG is None, reason="ffmpeg not installed")
def test_positive_delay_adds_silence_in_front(tmp_path: Path):
    src = tmp_path / "ton.flac"
    subprocess.run(
        [str(FFMPEG), "-v", "error", "-y", "-f", "lavfi",
         "-i", "sine=frequency=440:sample_rate=48000:duration=2", str(src)],
        check=True,
    )  # fmt: skip
    out = encode_ac3(src, 0, tmp_path / "ton.ac3", "2.0", 192, delay_ms=500)
    assert probe(out).duration == pytest.approx(2.5, abs=0.06)
