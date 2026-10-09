import sys
from pathlib import Path

import pytest

from dvd import toolchain
from dvd.video import encoders
from dvd.video.compliance import check
from dvd.video.ffmpeg_enc import encode, ffmpeg_args
from dvd.video.hcenc import EncodeSettings

sys.path.insert(0, str(Path(__file__).parent))
FFMPEG = toolchain.find_executable(["ffmpeg.exe", "ffmpeg"], toolchain.tool_dirs())


def test_args_set_dvd_flags_and_chapter_keyframes():
    s = EncodeSettings(6000, 9000, "16:9", "pal", chapters=[0, 50])
    args = ffmpeg_args(s, 25.0, Path("log"), 2)
    assert args[args.index("-flags") + 1] == "+ildct+cgop"  # progressive_sequence = 0
    assert args[args.index("-g") + 1] == "15" and args[args.index("-bf") + 1] == "2"
    assert args[args.index("-force_key_frames") + 1] == "2.000000"


def test_ntsc_film_is_encoded_progressive_with_short_gops():
    s = EncodeSettings(6000, 8000, "16:9", "ntsc", pulldown=True)
    args = ffmpeg_args(s, 24000 / 1001, Path("log"), 1)
    assert args[args.index("-flags") + 1] == "+cgop"
    assert args[args.index("-g") + 1] == "12"


def test_choose_falls_back_and_explains(monkeypatch):
    monkeypatch.setattr(encoders, "hcenc_available", lambda: False)
    assert encoders.choose("hcenc") == (
        "ffmpeg",
        "HCEnc is not installed; encoded with FFmpeg",
    )
    monkeypatch.setattr(encoders, "hcenc_available", lambda: True)
    assert encoders.choose("ffmpeg") == ("ffmpeg", None)


@pytest.mark.skipif(FFMPEG is None, reason="ffmpeg not installed")
def test_ffmpeg_output_is_dvd_compliant_with_chapter_keyframe(tmp_path: Path):
    from test_frameserver import pattern_clip

    settings = EncodeSettings(6000, 9000, "16:9", "pal", chapters=[37])
    out = encode(pattern_clip(100), tmp_path / "v.m2v", settings, tmp_path / "w")
    report = check(out, "pal")
    assert report.ok, report.errors
    assert report.info.progressive_sequence == 0
    assert report.info.colour == (5, 5, 5) and not report.warnings
    assert len(report.info.pictures) == 100
    # Chapter frame 37 opens a GOP: the GOPs before it add up to 37 pictures.
    sizes, total = report.info.gops, 0
    starts = [total := total + g for g in sizes[:-1]]
    assert 37 in [0, *starts]


@pytest.mark.skipif(FFMPEG is None, reason="ffmpeg not installed")
def test_ntsc_film_gets_soft_pulldown(tmp_path: Path):
    from fractions import Fraction

    import vapoursynth as vs
    from test_frameserver import pattern_clip

    clip = vs.core.resize.Point(pattern_clip(96), 720, 480)
    clip = vs.core.std.AssumeFPS(clip, fpsnum=24000, fpsden=1001)
    settings = EncodeSettings(6000, 8000, "16:9", "ntsc", pulldown=True, chapters=[48])
    out = encode(clip, tmp_path / "v.m2v", settings, tmp_path / "w")
    report = check(out, "ntsc")
    assert report.ok, report.errors
    info = report.info
    assert info.frame_rate == Fraction(30000, 1001) and info.progressive_sequence == 0
    assert info.colour == (6, 6, 6)
    # 96 film frames play as 240 fields = 120 video frames, 2:3 cadence.
    assert len(info.pictures) == 96 and sum(p.fields for p in info.pictures) == 240
    assert max(info.gop_fields) <= 36


def test_interlaced_args_use_field_coding_and_tff():
    s = EncodeSettings(6000, 9000, "16:9", "pal", interlaced=True)
    args = ffmpeg_args(s, 25.0, Path("log"), 2)
    assert args[args.index("-flags") + 1] == "+ildct+ilme+cgop"
    assert "field_mode=tff" in args[args.index("-vf") + 1]
