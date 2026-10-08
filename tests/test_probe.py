import subprocess
from fractions import Fraction
from pathlib import Path

import pytest

from dvd import toolchain
from dvd.probe import ProbeError, parse, probe

FFMPEG = toolchain.find_executable(["ffmpeg.exe", "ffmpeg"], toolchain.tool_dirs())
needs_ffmpeg = pytest.mark.skipif(FFMPEG is None, reason="ffmpeg not installed")


def video_stream(**over):
    s = {
        "index": 0,
        "codec_type": "video",
        "codec_name": "h264",
        "width": 1920,
        "height": 1080,
        "sample_aspect_ratio": "1:1",
        "r_frame_rate": "24000/1001",
        "avg_frame_rate": "24000/1001",
        "pix_fmt": "yuv420p",
        "field_order": "progressive",
        "color_space": "bt709",
        "color_transfer": "bt709",
        "color_primaries": "bt709",
        "color_range": "tv",
    }
    s.update(over)
    return s


def info_of(*streams, chapters=(), fmt=None):
    return parse(
        {
            "format": fmt or {"format_name": "matroska,webm", "duration": "7200.5", "size": "1"},
            "streams": list(streams),
            "chapters": list(chapters),
        },
        Path("film.mkv"),
    )


def test_bluray_remux_like_source():
    info = info_of(
        video_stream(),
        {
            "index": 1, "codec_type": "audio", "codec_name": "truehd", "channels": 8,
            "channel_layout": "7.1", "sample_rate": "48000", "tags": {"language": "eng"},
            "disposition": {"default": 1},
        },
        {
            "index": 2, "codec_type": "audio", "codec_name": "dts", "profile": "DTS-HD MA",
            "channels": 6, "sample_rate": "48000", "tags": {"language": "tur", "title": "Türkçe"},
        },
        {
            "index": 3, "codec_type": "subtitle", "codec_name": "hdmv_pgs_subtitle",
            "tags": {"language": "tur"}, "disposition": {"forced": 1},
        },
        {"index": 4, "codec_type": "subtitle", "codec_name": "subrip", "tags": {"language": "und"}},
    )  # fmt: skip
    v = info.main_video
    assert v.fps == Fraction(24000, 1001)
    assert v.dar == Fraction(16, 9)
    assert not v.interlaced and not v.hdr and not v.maybe_vfr
    assert info.duration == 7200.5
    assert [a.codec for a in info.audio] == ["truehd", "dts"]
    assert info.audio[0].default and info.audio[0].language == "eng"
    assert info.audio[1].profile == "DTS-HD MA" and info.audio[1].title == "Türkçe"
    assert info.subtitles[0].kind == "bitmap" and info.subtitles[0].forced
    assert info.subtitles[1].kind == "text" and info.subtitles[1].language is None


def test_cover_art_is_not_a_video_track():
    cover = video_stream(index=1, codec_name="mjpeg", disposition={"attached_pic": 1})
    info = info_of(video_stream(), cover)
    assert len(info.video) == 1


def test_anamorphic_pal_dv():
    v = info_of(video_stream(width=720, height=576, sample_aspect_ratio="64:45")).main_video
    assert v.dar == Fraction(16, 9)


def test_interlaced_broadcast():
    v = info_of(video_stream(field_order="tt", r_frame_rate="25/1", avg_frame_rate="25/1"))
    assert v.main_video.interlaced


def test_hdr10_and_dolby_vision():
    hdr10 = info_of(video_stream(color_transfer="smpte2084", pix_fmt="yuv420p10le")).main_video
    assert hdr10.hdr and hdr10.bit_depth == 10
    dv = info_of(
        video_stream(side_data_list=[{"side_data_type": "DOVI configuration record"}])
    ).main_video
    assert dv.dolby_vision and dv.hdr


def test_phone_video_portrait_and_variable_frame_rate():
    v = info_of(
        video_stream(width=1080, height=1920, r_frame_rate="30/1", avg_frame_rate="29871/1000")
    ).main_video
    assert v.portrait
    assert v.maybe_vfr


def test_missing_values_do_not_crash():
    info = parse({"format": {}, "streams": [{"index": 0, "codec_type": "video"}]}, Path("x"))
    v = info.main_video
    assert v.fps is None and v.sar == 1 and not v.maybe_vfr
    assert info.duration is None


def test_missing_file_raises(tmp_path: Path):
    with pytest.raises(ProbeError):
        probe(tmp_path / "yok.mkv")


@pytest.fixture(scope="module")
def sample_mkv(tmp_path_factory) -> Path:
    d = tmp_path_factory.mktemp("kaynak")
    (d / "alt.srt").write_text(
        "1\n00:00:00,500 --> 00:00:01,500\nMerhaba dünya, ğüşıöç İ\n", encoding="utf-8"
    )
    (d / "meta.txt").write_text(
        ";FFMETADATA1\ntitle=Deneme Filmi\n"
        "[CHAPTER]\nTIMEBASE=1/1000\nSTART=0\nEND=1000\ntitle=Açılış\n"
        "[CHAPTER]\nTIMEBASE=1/1000\nSTART=1000\nEND=2000\ntitle=Son\n",
        encoding="utf-8",
    )
    out = d / "Türkçe örnek ğİ.mkv"
    subprocess.run(
        [
            str(FFMPEG), "-v", "error", "-y",
            "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=24000/1001:duration=2",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=2",
            "-i", str(d / "alt.srt"), "-i", str(d / "meta.txt"),
            "-map", "0", "-map", "1", "-map", "1", "-map", "2",
            "-map_metadata", "3", "-map_chapters", "3",
            "-c:v", "libx264", "-preset", "ultrafast",
            "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709",
            "-c:a:0", "ac3", "-ac:a:0", "6", "-c:a:1", "aac", "-ac:a:1", "2", "-c:s", "srt",
            "-metadata:s:a:0", "language=eng",
            "-metadata:s:a:1", "language=tur", "-metadata:s:a:1", "title=Türkçe yorum",
            "-metadata:s:s:0", "language=tur",
            "-disposition:a:0", "default", "-disposition:a:1", "0", "-disposition:s:0", "forced",
            str(out),
        ],
        check=True,
    )  # fmt: skip
    return out


@needs_ffmpeg
def test_probe_real_file_with_turkish_names(sample_mkv: Path):
    info = probe(sample_mkv)
    assert info.path == sample_mkv
    assert info.title == "Deneme Filmi"
    assert info.container.startswith("matroska")
    v = info.main_video
    assert (v.codec, v.width, v.height) == ("h264", 640, 360)
    assert v.fps == Fraction(24000, 1001)
    assert v.color_matrix == "bt709"
    assert [(a.codec, a.channels, a.language) for a in info.audio] == [
        ("ac3", 6, "eng"),
        ("aac", 2, "tur"),
    ]
    assert info.audio[0].default and not info.audio[1].default
    assert info.audio[1].title == "Türkçe yorum"
    assert info.subtitles[0].codec == "subrip" and info.subtitles[0].forced
    assert [c.title for c in info.chapters] == ["Açılış", "Son"]
    assert info.chapters[1].start == pytest.approx(1.0)


@needs_ffmpeg
def test_probe_interlaced_mpeg2(tmp_path: Path):
    out = tmp_path / "yayin.ts"
    subprocess.run(
        [
            str(FFMPEG), "-v", "error", "-y",
            "-f", "lavfi", "-i", "testsrc2=size=720x576:rate=25:duration=1",
            "-vf", "setfield=tff", "-c:v", "mpeg2video", "-flags", "+ilme+ildct", str(out),
        ],
        check=True,
    )  # fmt: skip
    v = probe(out).main_video
    assert v.codec == "mpeg2video"
    assert v.interlaced


def test_summary_lists_tracks_and_conversion_notes():
    from dvd.probe import report

    info = info_of(
        video_stream(color_transfer="smpte2084", pix_fmt="yuv420p10le"),
        {"index": 1, "codec_type": "audio", "codec_name": "ac3", "channels": 6,
         "sample_rate": "48000", "tags": {"language": "tur", "title": "Türkçe"}},
        chapters=[{"start_time": "0.0", "end_time": "60", "tags": {"title": "Açılış"}}],
    )  # fmt: skip
    text = report.summary(info)
    assert "1920x1080 16:9 23.976 fps" in text
    assert '#1 ac3 6ch 48 kHz tur "Türkçe"' in text
    assert "0:00:00 Açılış" in text
    assert "tone mapping" in text and "10-bit" in text


def test_json_view_is_serialisable():
    import json

    from dvd.probe import report

    data = report.to_json(info_of(video_stream()))
    assert json.loads(json.dumps(data))["video"][0]["fps"] == "24000/1001"


@needs_ffmpeg
def test_cli_new_then_check(sample_mkv: Path, tmp_path: Path):
    from typer.testing import CliRunner

    from dvd.cli import app

    out = tmp_path / "proje.dvd.yaml"
    runner = CliRunner()
    result = runner.invoke(app, ["new", str(sample_mkv), "-o", str(out)])
    assert result.exit_code == 0, result.output
    assert "standard PAL" in result.output
    result = runner.invoke(app, ["check", str(out)])
    assert result.exit_code == 0, result.output
    assert "ok: Deneme Filmi | PAL DVD5 | 1 title(s)" in result.output
    assert runner.invoke(app, ["new", str(sample_mkv), "-o", str(out)]).exit_code == 1
