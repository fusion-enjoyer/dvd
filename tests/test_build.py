import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from dvd import toolchain
from dvd.author.dvdauthor import AuthorError, AuthorTitle, dvdauthor_xml, timecode
from dvd.build import build, chapter_frames, safe_name
from dvd.probe import probe
from dvd.project import load, new_project, save
from dvd.project.model import ChapterEvery
from dvd.video.compliance import check as check_video

DIRS = toolchain.tool_dirs()
FFMPEG = toolchain.find_executable(["ffmpeg.exe", "ffmpeg"], DIRS)
sys.path.insert(0, str(Path(__file__).parent))
READY = all(
    toolchain.find_executable([p], DIRS)
    for p in ("HCenc_*.exe", "DvdSource.dll", "dvdauthor.exe", "ffmpeg.exe")
)


def test_timecode():
    assert timecode(0) == "0:00:00.000"
    assert timecode(3723.04) == "1:02:03.040"


def test_safe_name():
    assert safe_name('Film: "Bölüm 1/2"?') == "Film_ _Bölüm 1_2__"
    assert safe_name(" . ") == "disc"


def test_xml_for_widescreen_pal_with_two_titles():
    t1 = AuthorTitle("t01.mpg", "16:9", ["tr", "en"], ["0:00:00.000", "0:10:00.000"])
    t2 = AuthorTitle("t02.mpg", "16:9", ["tr", "en"])
    xml = dvdauthor_xml([t1, t2], "pal")
    assert '<video format="pal" aspect="16:9" widescreen="nopanscan"/>' in xml
    assert xml.count("<audio lang=") == 2
    assert 'chapters="0:00:00.000,0:10:00.000"' in xml
    assert "<post>jump title 2;</post>" in xml
    assert xml.count("<post>") == 1


def test_xml_rejects_mixed_aspect():
    with pytest.raises(AuthorError):
        dvdauthor_xml([AuthorTitle("a", "16:9"), AuthorTitle("b", "4:3")], "pal")


def _sample(tmp_path: Path, seconds: int = 12) -> Path:
    (tmp_path / "meta.txt").write_text(
        ";FFMETADATA1\ntitle=Deneme Filmi\n"
        "[CHAPTER]\nTIMEBASE=1/1000\nSTART=0\nEND=5000\ntitle=Açılış\n"
        f"[CHAPTER]\nTIMEBASE=1/1000\nSTART=5005\nEND={seconds * 1000}\ntitle=Son\n",
        encoding="utf-8",
    )
    src = tmp_path / "Deneme Filmi (2026).mkv"
    subprocess.run(
        [
            str(FFMPEG), "-v", "error", "-y",
            "-f", "lavfi", "-i", f"testsrc2=size=1920x804:rate=24000/1001:duration={seconds}",
            "-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=48000:duration={seconds}",
            "-f", "lavfi", "-i", f"sine=frequency=660:sample_rate=48000:duration={seconds}",
            "-i", str(tmp_path / "meta.txt"),
            "-map", "0", "-map", "1", "-map", "2", "-map_metadata", "3", "-map_chapters", "3",
            "-c:v", "libx264", "-preset", "ultrafast", "-colorspace", "bt709",
            "-c:a:0", "ac3", "-ac:a:0", "6", "-c:a:1", "ac3", "-ac:a:1", "2",
            "-metadata:s:a:0", "language=eng", "-metadata:s:a:1", "language=tur",
            "-disposition:a:0", "0", "-disposition:a:1", "default",
            str(src),
        ],
        check=True,
    )  # fmt: skip
    return src


def test_chapter_frames(tmp_path: Path):
    if FFMPEG is None:
        pytest.skip("ffmpeg not installed")
    from dvd.video.pipeline import plan_target

    info = probe(_sample(tmp_path))
    title = new_project(info, tmp_path).titles[0]
    target = plan_target(info.main_video, "pal", title.video)
    frames = 287  # 12 s at 23.976 fps
    assert chapter_frames(title, info, target, frames) == [0, 120]  # 5.005 s * 23.976
    assert chapter_frames(title, info, target, 100) == [0]  # chapter past the end is dropped
    title.chapters = ChapterEvery(every=0.1)  # 6 s at 25 fps = 150 frames
    assert chapter_frames(title, info, target, frames) == [0, 150]
    title.chapters = ["0:00", "0:01.5"]
    assert chapter_frames(title, info, target, frames) == [0, 36]


@pytest.mark.skipif(not READY, reason="toolchain not installed")
def test_build_menuless_pal_disc(tmp_path: Path):
    project_dir = tmp_path / "Proje ğüş"
    project_dir.mkdir()
    src = _sample(project_dir)
    project_file = project_dir / "deneme.dvd.yaml"
    project = new_project(probe(src), project_dir)
    project.menus = None  # menus are on by default; this disc plays the film straight away
    save(project, project_file)
    stages = []

    result = build(project_file, progress=lambda s, f: stages.append(s))

    assert result.video_ts == project_dir / "Deneme Filmi" / "VIDEO_TS"
    names = sorted(p.name for p in result.video_ts.iterdir())
    assert names == ["VIDEO_TS.BUP", "VIDEO_TS.IFO", "VTS_01_0.BUP", "VTS_01_0.IFO",
                     "VTS_01_1.VOB"]  # fmt: skip
    vob = probe(result.video_ts / "VTS_01_1.VOB")
    v = vob.main_video
    assert (v.codec, v.width, v.height, v.fps) == ("mpeg2video", 720, 576, 25)
    assert [(a.codec, a.channels) for a in vob.audio] == [("ac3", 2), ("ac3", 6)]  # default first
    assert vob.duration == pytest.approx(12 * 24000 / 1001 / 25, abs=0.2)
    assert "title 1 video" in stages and stages[-1] == "done"
    assert result.iso == project_dir / "Deneme Filmi" / "Deneme Filmi.iso"
    assert "iso" in stages
    duration = subprocess.run(
        [str(toolchain.find_executable(["ffprobe.exe"], DIRS)), "-v", "quiet", "-f", "dvdvideo",
         "-i", str(result.iso), "-show_entries", "format=duration", "-of", "csv=p=0"],
        capture_output=True, text=True, check=True,
    ).stdout  # fmt: skip
    assert float(duration) == pytest.approx(vob.duration, abs=0.3)
    assert load(project_file).titles[0].audio[1].default


def count_nav_packs(mpg: Path) -> int:
    """NAV packs as dvdauthor detects them: private stream 2 at bytes 38 and 1024 of a pack."""
    data = mpg.read_bytes()
    marker = b"\x00\x00\x01\xbf"
    return sum(
        1
        for i in range(0, len(data) - 2047, 2048)
        if data[i + 38 : i + 42] == marker and data[i + 1024 : i + 1028] == marker
    )


@pytest.mark.skipif(not READY, reason="toolchain not installed")
def test_mux_starts_a_vobu_about_every_half_second(tmp_path: Path):
    from test_frameserver import pattern_clip

    from dvd.author.dvdauthor import mux
    from dvd.video.hcenc import EncodeSettings, encode

    m2v = encode(
        pattern_clip(125),
        tmp_path / "v.m2v",
        EncodeSettings(4000, 8000, "16:9", "pal", profile="fast"),
        tmp_path / "w",
    )
    ac3 = tmp_path / "a.ac3"
    subprocess.run(
        [str(FFMPEG), "-v", "error", "-y", "-f", "lavfi", "-i", "sine=duration=5",
         "-c:a", "ac3", "-ar", "48000", str(ac3)],
        check=True,
    )  # fmt: skip
    navs = count_nav_packs(mux(m2v, [ac3], tmp_path / "out.mpg"))
    assert 5 <= navs <= 13  # 5 s of video, VOBUs of 0.4-1.0 s


def test_xml_with_subtitles_turns_the_first_one_on():
    t = AuthorTitle("t01.mpg", "16:9", ["en"], subtitle_langs=["tr", "en"], subtitles_on=True)
    xml = dvdauthor_xml([t], "pal")
    assert '<subpicture lang="tr"/>' in xml and '<subpicture lang="en"/>' in xml
    assert "<pre>subtitle=64;</pre>" in xml


@pytest.mark.skipif(not READY, reason="toolchain not installed")
def test_build_with_srt_subtitle_file(tmp_path: Path):
    src = _sample(tmp_path, seconds=6)
    (tmp_path / "film.tr.srt").write_bytes(
        "1\n00:00:01,000 --> 00:00:03,000\nTürkçe altyazı: ğüşıöç İ\n".encode("cp1254")
    )
    project = new_project(probe(src), tmp_path)
    from dvd.project.model import Subtitle

    project.titles[0].subtitles = [Subtitle(file="film.tr.srt", lang="tr", default=True)]
    project_file = tmp_path / "film.dvd.yaml"
    save(project, project_file)

    result = build(project_file, make_iso=False)

    vob = probe(result.video_ts / "VTS_01_1.VOB")
    assert [s.codec for s in vob.subtitles] == ["dvd_subtitle"]
    ffprobe = toolchain.find_executable(["ffprobe.exe"], DIRS)
    out = subprocess.run(
        [str(ffprobe), "-v", "quiet", "-f", "dvdvideo", "-i", str(result.video_ts),
         "-show_entries", "stream=codec_name:stream_tags=language", "-of", "csv=p=0"],
        capture_output=True, text=True, check=True,
    ).stdout  # fmt: skip
    assert "dvd_subtitle,tur" in out  # IFO stores "tr"; ffprobe shows ISO 639-2
    xml = (tmp_path / "build" / "Deneme Filmi" / "dvdauthor.xml").read_text(encoding="utf-8")
    assert "subtitle=64" in xml


@pytest.mark.skipif(not READY, reason="toolchain not installed")
def test_letterboxed_source_is_cropped_and_bars_sit_on_macroblock_rows(tmp_path: Path):
    import numpy as np

    src = tmp_path / "kapsam.mkv"
    subprocess.run(
        [str(FFMPEG), "-v", "error", "-y", "-f", "lavfi",
         "-i", "testsrc2=size=1920x804:rate=25:duration=3", "-vf", "pad=1920:1080:0:138:black",
         "-c:v", "libx264", "-preset", "ultrafast", "-crf", "20", str(src)],
        check=True,
    )  # fmt: skip
    project_file = tmp_path / "kapsam.dvd.yaml"
    save(new_project(probe(src), tmp_path), project_file)
    result = build(project_file, make_iso=False)
    raw = subprocess.run(
        [str(FFMPEG), "-v", "error", "-i", str(result.video_ts / "VTS_01_1.VOB"), "-frames:v", "1",
         "-f", "rawvideo", "-pix_fmt", "gray", "-"],
        capture_output=True, check=True,
    ).stdout  # fmt: skip
    rows = np.frombuffer(raw, np.uint8).reshape(576, 720).mean(axis=1)
    picture = np.flatnonzero(rows > 24)
    assert (picture[0], picture[-1]) == (64, 64 + 432 - 1)  # 64 lines above, 80 below


@pytest.mark.skipif(not READY, reason="toolchain not installed")
def test_build_ntsc_film_disc_with_ffmpeg_soft_pulldown(tmp_path: Path):
    src = _sample(tmp_path, seconds=6)
    project = new_project(probe(src), tmp_path)
    project.disc.standard = "ntsc"
    project.titles[0].video.overrides = {"encoder": "ffmpeg"}
    project_file = tmp_path / "ntsc.dvd.yaml"
    save(project, project_file)

    result = build(project_file, make_iso=False)

    vob = probe(result.video_ts / "VTS_01_1.VOB")
    v = vob.main_video
    assert (v.codec, v.width, v.height) == ("mpeg2video", 720, 480)
    # Soft pulldown keeps the original running time: 23.976 film frames, 29.97 playback.
    assert vob.duration == pytest.approx(6, abs=0.2)


@pytest.mark.skipif(not READY, reason="toolchain not installed")
@pytest.mark.parametrize("encoder", ["hcenc", "ffmpeg"])
def test_build_50p_source_as_interlaced_pal(tmp_path: Path, encoder: str):
    src = tmp_path / "telefon.mkv"
    subprocess.run(
        [str(FFMPEG), "-v", "error", "-y",
         "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=50:duration=4",
         "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=4",
         "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(src)],
        check=True,
    )  # fmt: skip
    project = new_project(probe(src), tmp_path)
    assert project.disc.standard == "pal"
    project.titles[0].video.overrides = {"encoder": encoder}
    project_file = tmp_path / "telefon.dvd.yaml"
    save(project, project_file)

    result = build(project_file, make_iso=False)

    m2v = next(tmp_path.rglob("t01.m2v"))
    info = check_video(m2v, "pal").info
    assert len(info.pictures) == 100  # 200 source frames, two per DVD frame
    assert all(not p.progressive and p.tff for p in info.pictures)
    vob = probe(result.video_ts / "VTS_01_1.VOB")
    assert vob.main_video.fps == 25 and vob.main_video.field_order == "tt"
    assert vob.duration == pytest.approx(4, abs=0.2)


@pytest.mark.skipif(not READY, reason="toolchain not installed")
def test_build_variable_frame_rate_and_rotated_phone_video(tmp_path: Path):
    # 30 fps with every 10th frame missing after the first second: timestamps say 4 s,
    # the container says 30 fps. Stored landscape with a 90° display rotation.
    flat = tmp_path / "flat.mkv"
    subprocess.run(
        [str(FFMPEG), "-v", "error", "-y",
         "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30:duration=4",
         "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=4",
         "-vf", r"select='lt(n\,30)+mod(n\,10)'", "-fps_mode", "vfr",
         "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(flat)],
        check=True,
    )  # fmt: skip
    src = tmp_path / "telefon.mp4"
    subprocess.run([str(FFMPEG), "-v", "error", "-y", "-display_rotation", "90", "-i", str(flat),
                    "-c", "copy", str(src)], check=True)  # fmt: skip
    info = probe(src)
    assert info.main_video.portrait
    project = new_project(info, tmp_path)
    assert project.disc.standard == "ntsc" and project.disc.profiles.content == "telefon"
    project_file = tmp_path / "telefon.dvd.yaml"
    save(project, project_file)

    result = build(project_file, make_iso=False)

    vob = probe(result.video_ts / "VTS_01_1.VOB")
    assert vob.main_video.height == 480
    assert vob.duration == pytest.approx(4, abs=0.2)  # 30 -> 29.97 adds 0.1%
    m2v = next(tmp_path.rglob("t01.m2v"))
    assert check_video(m2v, "ntsc").info.aspect_code == 2  # portrait goes in a 4:3 frame
    frame = tmp_path / "frame.gray"
    subprocess.run([str(FFMPEG), "-v", "error", "-y", "-ss", "2", "-i", str(m2v), "-frames:v", "1",
                    "-f", "rawvideo", "-pix_fmt", "gray", str(frame)], check=True)  # fmt: skip
    luma = np.fromfile(frame, dtype=np.uint8).reshape(480, 720)
    assert luma[:, :40].mean() > 30  # side bars carry the blurred picture, not black
    assert luma[:, :40].std() < luma[:, 300:420].std()  # and are smoother than the picture


@pytest.mark.skipif(not READY, reason="toolchain not installed")
def test_audio_offset_in_the_source_is_kept_and_ac3_is_copied(tmp_path: Path):
    src = tmp_path / "kayma.mkv"
    subprocess.run(
        [str(FFMPEG), "-v", "error", "-y",
         "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=25:duration=3",
         "-itsoffset", "0.5", "-f", "lavfi", "-i", "sine=sample_rate=48000:duration=2.5",
         "-f", "lavfi", "-i", "sine=frequency=660:sample_rate=48000:duration=3",
         "-map", "0", "-map", "1", "-map", "2",
         "-c:v", "libx264", "-preset", "ultrafast",
         "-c:a", "ac3", "-ac", "6", "-b:a", "448k", str(src)],
        check=True,
    )  # fmt: skip
    info = probe(src)
    assert info.audio[0].start_time == pytest.approx(0.5, abs=0.05)
    project = new_project(info, tmp_path)
    project_file = tmp_path / "kayma.dvd.yaml"
    save(project, project_file)

    build(project_file, make_iso=False)

    shifted = next(tmp_path.rglob("t01_a0.ac3"))
    assert probe(shifted).duration == pytest.approx(3.0, abs=0.06)  # 0.5 s silence + 2.5 s
    aligned = next(tmp_path.rglob("t01_a1.ac3"))  # starts with the video: copied unchanged
    assert probe(aligned).audio[0].bitrate == 448000
    assert probe(aligned).duration == pytest.approx(3.0, abs=0.06)


@pytest.mark.skipif(not READY, reason="toolchain not installed")
def test_build_disc_with_menus(tmp_path: Path):
    from dvd.project.model import Menus

    src = _sample(tmp_path, seconds=12)
    project = new_project(probe(src), tmp_path)
    project.menus = Menus.model_validate({"background": {"frame": "0:00:06"}})
    project.titles[0].video.overrides = {"encoder": "ffmpeg"}
    project_file = tmp_path / "menulu.dvd.yaml"
    save(project, project_file)

    result = build(project_file)

    names = sorted(p.name for p in result.video_ts.iterdir())
    assert "VTS_01_0.VOB" in names  # the titleset menus
    xml = (next(tmp_path.rglob("dvdauthor.xml"))).read_text(encoding="utf-8")
    assert "jump titleset 1 menu;" in xml and 'entry="root"' in xml and 'entry="ptt"' in xml
    assert "<post>call menu;</post>" in xml
    assert "jump title 1 chapter 2;" in xml  # chapter 2 button of the chapter page
    log = next(tmp_path.rglob("menu01/spumux.log")).read_text(encoding="utf-8")
    assert "ERR" not in log
    menu = probe(result.video_ts / "VTS_01_0.VOB")
    assert [s.codec for s in menu.subtitles] == ["dvd_subtitle"]  # the button highlights
    assert menu.main_video.width == 720
    # The ISO still reads as a DVD and the film is title 1.
    duration = subprocess.run(
        [str(toolchain.find_executable(["ffprobe.exe"], DIRS)), "-v", "quiet", "-f", "dvdvideo",
         "-i", str(result.iso), "-show_entries", "format=duration", "-of", "csv=p=0"],
        capture_output=True, text=True, check=True,
    ).stdout  # fmt: skip
    assert float(duration) == pytest.approx(12 * 24000 / 1001 / 25, abs=0.4)


@pytest.mark.skipif(not READY, reason="toolchain not installed")
def test_intro_plays_before_the_menu(tmp_path: Path):
    from dvd.project.model import Intro

    src = _sample(tmp_path, seconds=6)
    intro = tmp_path / "logo.mkv"
    subprocess.run(
        [str(FFMPEG), "-v", "error", "-y", "-f", "lavfi",
         "-i", "testsrc=size=640x360:rate=25:duration=2",
         "-f", "lavfi", "-i", "sine=frequency=880:sample_rate=48000:duration=2",
         "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(intro)],
        check=True,
    )  # fmt: skip
    project = new_project(probe(src), tmp_path)
    project.first_play = [Intro(file="logo.mkv")]
    project.at_end = "repeat"
    project.titles[0].video.overrides = {"encoder": "ffmpeg"}
    project_file = tmp_path / "giris.dvd.yaml"
    save(project, project_file)
    assert load(project_file).first_play == [Intro(file="logo.mkv")]

    result = build(project_file)

    names = sorted(p.name for p in result.video_ts.iterdir())
    assert "VTS_02_1.VOB" in names  # the intro titleset
    xml = next(tmp_path.rglob("dvdauthor.xml")).read_text(encoding="utf-8")
    assert "<fpc>jump title 2;</fpc>" in xml  # the intro is title 2 on the disc
    assert '<pgc entry="title"><pre>jump titleset 1 menu;</pre>' in xml
    assert "call vmgm menu entry title;" in xml
    assert "<post>jump title 1;</post>" in xml  # at_end: repeat
    intro_vob = probe(result.video_ts / "VTS_02_1.VOB")
    assert intro_vob.duration == pytest.approx(2, abs=0.3)
    assert intro_vob.main_video.width == 720
