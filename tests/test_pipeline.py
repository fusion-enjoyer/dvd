import subprocess
from fractions import Fraction
from pathlib import Path

import numpy as np
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


def test_scope_film_gets_letterbox_bars_on_macroblock_rows():
    t = plan_target(track(height=804), "pal", Video())
    # 2.39:1 ideally needs 428.9 lines; 432 is the nearest multiple of 16.
    assert (t.active_width, t.active_height) == (720, 432)
    assert t.pad_top == 64  # 144 lines of bars: 64 above, 80 below
    # The source is narrowed by 14 pixels instead of stretching the picture vertically.
    assert (t.crop.left, t.crop.right, t.crop.top, t.crop.bottom) == (6, 8, 0, 0)


def shown_shape(t, v):
    return Fraction(t.active_width, t.width) * t.dar / Fraction(t.active_height, t.height)


def source_shape(v, t):
    c = t.crop
    return Fraction(v.width - c.left - c.right, v.height - c.top - c.bottom) * v.sar


@pytest.mark.parametrize(
    ("width", "height", "aspect"),
    [(1920, 804, "auto"), (1920, 1038, "auto"), (1440, 1080, "16:9"), (1920, 800, "auto"),
     (1998, 1080, "auto"), (720, 576, "auto"), (1080, 1920, "auto")],
)  # fmt: skip
def test_alignment_keeps_the_shape_and_macroblock_grid(width, height, aspect):
    v = track(width=width, height=height, fps=Fraction(25))
    t = plan_target(v, "pal", Video(aspect=aspect))
    assert t.active_width % 16 == 0 and t.active_height % 16 == 0
    assert t.pad_left % 16 == 0 and t.pad_top % 16 == 0
    assert all(x % 2 == 0 for x in (t.crop.left, t.crop.right, t.crop.top, t.crop.bottom))
    assert abs(shown_shape(t, v) / source_shape(v, t) - 1) < Fraction(1, 200)


def test_without_alignment_bars_are_centred():
    t = plan_target(track(height=804), "pal", Video(), align=False)
    assert (t.active_height, t.pad_top) == (428, 74)
    assert t.crop == Crop()


def test_crop_is_applied_before_framing():
    t = plan_target(track(), "pal", Video(crop=Crop(top=138, bottom=138)))
    assert t.active_height == 432 and t.crop.top == 138


def test_detected_crop_is_used_only_for_auto():
    detected = Crop(top=138, bottom=138)
    assert plan_target(track(), "pal", Video(), detected).active_height == 432
    assert plan_target(track(), "pal", Video(crop="none"), detected).active_height == 576


def test_flat_1_85_film():
    assert plan_target(track(height=1038), "pal", Video()).active_height == 560


def test_4_3_source_gets_4_3_frame():
    t = plan_target(track(width=1440), "pal", Video())
    assert t.aspect == "4:3"
    assert (t.active_width, t.active_height) == (720, 576)


def test_4_3_source_forced_into_16_9_frame_is_pillarboxed():
    t = plan_target(track(width=1440), "pal", Video(aspect="16:9"))
    assert (t.active_width, t.active_height) == (544, 576)
    assert t.pad_left == 80


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


@pytest.mark.parametrize(
    ("fps", "standard", "speedup"),
    [(Fraction(50), "pal", 1), (Fraction(60000, 1001), "ntsc", 1),
     (Fraction(60), "ntsc", Fraction(1000, 1001))],
)  # fmt: skip
def test_50_and_60_fps_become_interlaced(fps, standard, speedup):
    t = plan_target(track(1920, 1080, fps), standard, Video())
    assert t.interlaced and not t.pulldown
    assert t.fps == (25 if standard == "pal" else Fraction(30000, 1001))
    assert t.speedup == speedup


def test_30_fps_plays_at_29_97_on_ntsc():
    t = plan_target(track(1920, 1080, Fraction(30)), "ntsc", Video())
    assert not t.interlaced and t.fps == Fraction(30000, 1001)
    assert t.speedup == Fraction(1000, 1001)


def test_interlace_puts_even_frames_on_top_fields():
    import vapoursynth as vs

    from dvd.video.pipeline import interlace

    core = vs.core
    white = core.std.BlankClip(format=vs.YUV444P16, width=64, height=32, length=1,
                               color=[60000, 32768, 32768])  # fmt: skip
    black = core.std.BlankClip(white, color=[4096, 32768, 32768])
    clip = core.std.Interleave([white, black] * 1)  # frame 0 white, frame 1 black
    out = interlace(clip * 2, "none")
    assert out.num_frames == 2 and out.format.id == vs.YUV420P8
    with out.get_frame(0) as f:
        luma = np.asarray(f[0])
        assert f.props["_FieldBased"] == 2
    assert luma[0::2].min() > 200 and luma[1::2].max() < 40  # top lines white, bottom black
