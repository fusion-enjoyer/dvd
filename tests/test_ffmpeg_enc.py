import sys
from pathlib import Path

import pytest

from dvd import toolchain
from dvd.video import encoders
from dvd.video.compliance import check
from dvd.video.ffmpeg_enc import encode, ffmpeg_args
from dvd.video.hcenc import EncodeError, EncodeSettings

sys.path.insert(0, str(Path(__file__).parent))
FFMPEG = toolchain.find_executable(["ffmpeg.exe", "ffmpeg"], toolchain.tool_dirs())


def test_args_set_dvd_flags_and_chapter_keyframes():
    s = EncodeSettings(6000, 9000, "16:9", "pal", chapters=[0, 50])
    args = ffmpeg_args(s, 25.0, Path("log"), 2)
    assert args[args.index("-flags") + 1] == "+ildct+cgop"  # progressive_sequence = 0
    assert args[args.index("-g") + 1] == "15" and args[args.index("-bf") + 1] == "2"
    assert args[args.index("-force_key_frames") + 1] == "2.000000"


def test_ntsc_film_is_refused():
    s = EncodeSettings(6000, 8000, "16:9", "ntsc", pulldown=True)
    with pytest.raises(EncodeError, match="pulldown"):
        encode(None, Path("x.m2v"), s, Path("."))


def test_choose_falls_back_and_explains(monkeypatch):
    monkeypatch.setattr(encoders, "hcenc_available", lambda: False)
    assert encoders.choose("hcenc", False) == (
        "ffmpeg",
        "HCEnc is not installed; encoded with FFmpeg",
    )
    with pytest.raises(EncodeError):
        encoders.choose("hcenc", True)
    monkeypatch.setattr(encoders, "hcenc_available", lambda: True)
    assert encoders.choose("ffmpeg", True)[0] == "hcenc"
    assert encoders.choose("ffmpeg", False) == ("ffmpeg", None)


@pytest.mark.skipif(FFMPEG is None, reason="ffmpeg not installed")
def test_ffmpeg_output_is_dvd_compliant_with_chapter_keyframe(tmp_path: Path):
    from test_frameserver import pattern_clip

    settings = EncodeSettings(6000, 9000, "16:9", "pal", chapters=[37])
    out = encode(pattern_clip(100), tmp_path / "v.m2v", settings, tmp_path / "w")
    report = check(out, "pal")
    assert report.ok, report.errors
    assert report.info.progressive_sequence == 0
    assert len(report.info.pictures) == 100
    # Chapter frame 37 opens a GOP: the GOPs before it add up to 37 pictures.
    sizes, total = report.info.gops, 0
    starts = [total := total + g for g in sizes[:-1]]
    assert 37 in [0, *starts]
