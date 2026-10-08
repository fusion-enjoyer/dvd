import subprocess
from fractions import Fraction
from pathlib import Path

import pytest

from dvd import toolchain
from dvd.probe import VideoTrack, probe
from dvd.project.model import Crop, Video
from dvd.video.pipeline import UnsupportedSource, build_clip, check_supported, plan_target

FFMPEG = toolchain.find_executable(["ffmpeg.exe", "ffmpeg"], toolchain.tool_dirs())
FILM = Fraction(24000, 1001)


def track(width=1920, height=1080, fps=FILM, sar=Fraction(1), **kw):
    return VideoTrack(0, "h264", width, height, sar, fps, fps, **kw)


def test_hd_film_to_pal_16_9_fills_the_frame():
    t = plan_target(track(), "pal", Video())
    assert (t.width, t.height, t.aspect) == (720, 576, "16:9")
    assert (t.active_width, t.active_height) == (720, 576)
    assert t.fps == 25 and not t.pulldown
    assert t.speedup == Fraction(25025, 24000)


def test_scope_film_gets_letterbox_bars():
    t = plan_target(track(height=804), "pal", Video())
    assert (t.active_width, t.active_height) == (720, 428)


def test_crop_is_applied_before_framing():
    t = plan_target(track(), "pal", Video(crop=Crop(top=138, bottom=138)))
    assert t.active_height == 428


def test_flat_1_85_film():
    assert plan_target(track(height=1038), "pal", Video()).active_height == 554


def test_4_3_source_gets_4_3_frame():
    t = plan_target(track(width=1440), "pal", Video())
    assert t.aspect == "4:3"
    assert (t.active_width, t.active_height) == (720, 576)


def test_4_3_source_forced_into_16_9_frame_is_pillarboxed():
    t = plan_target(track(width=1440), "pal", Video(aspect="16:9"))
    assert (t.active_width, t.active_height) == (540, 576)


def test_portrait_phone_video_is_pillarboxed_in_4_3():
    t = plan_target(track(width=1080, height=1920, fps=Fraction(25)), "pal", Video())
    assert t.aspect == "4:3"
    assert (t.active_width, t.active_height) == (304, 576)


def test_ntsc_film_uses_pulldown():
    t = plan_target(track(), "ntsc", Video())
    assert (t.width, t.height, t.fps, t.pulldown) == (720, 480, FILM, True)
    assert t.speedup == 1


def test_anamorphic_pal_dvd_source():
    t = plan_target(track(720, 576, Fraction(25), sar=Fraction(64, 45)), "pal", Video())
    assert (t.aspect, t.active_width, t.active_height) == ("16:9", 720, 576)


def test_frame_rate_conversion_not_supported_yet():
    with pytest.raises(UnsupportedSource):
        plan_target(track(fps=Fraction(30000, 1001)), "pal", Video())
    with pytest.raises(UnsupportedSource):
        plan_target(track(fps=Fraction(25)), "ntsc", Video())


def test_hdr_and_interlaced_are_rejected_for_now():
    with pytest.raises(UnsupportedSource, match="HDR"):
        check_supported(track(color_transfer="smpte2084"))
    with pytest.raises(UnsupportedSource, match="interlaced"):
        check_supported(track(field_order="tt"))


@pytest.mark.skipif(FFMPEG is None, reason="ffmpeg not installed")
def test_build_clip_from_scope_hd_film(tmp_path: Path):
    src = tmp_path / "kapsam filmi.mkv"
    subprocess.run(
        [
            str(FFMPEG), "-v", "error", "-y", "-f", "lavfi",
            "-i", "testsrc2=size=1920x804:rate=24000/1001:duration=1",
            "-c:v", "libx264", "-preset", "ultrafast", "-colorspace", "bt709", str(src),
        ],
        check=True,
    )  # fmt: skip
    v = probe(src).main_video
    target = plan_target(v, "pal", Video())
    clip = build_clip(src, v, target, Video())
    assert (clip.width, clip.height, clip.fps) == (720, 576, Fraction(25))
    assert clip.num_frames == 24
    with clip.get_frame(0) as f:
        top_left = memoryview(f[0])[0, 0]
        middle = memoryview(f[0])[288, 360]
    assert top_left == 16  # black bar
    assert middle != 16
