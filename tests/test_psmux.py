import subprocess
import sys
from fractions import Fraction
from pathlib import Path

import pytest

from dvd import toolchain

DIRS = toolchain.tool_dirs()
FFMPEG = toolchain.find_executable(["ffmpeg.exe", "ffmpeg"], DIRS)
FFPROBE = toolchain.find_executable(["ffprobe.exe", "ffprobe"], DIRS)
READY = all(toolchain.find_executable([n], DIRS) for n in ("dvdauthor.exe", "spumux.exe")) \
    and FFMPEG is not None  # fmt: skip


def _streams(tmp_path: Path, keys: str = "") -> tuple[Path, Path]:
    video, audio = tmp_path / "v.m2v", tmp_path / "a.ac3"
    args = ["-force_key_frames", keys] if keys else []
    subprocess.run(
        [str(FFMPEG), "-v", "error", "-y", "-f", "lavfi",
         "-i", "testsrc=size=720x576:rate=25:duration=6", "-c:v", "mpeg2video", "-b:v", "6M",
         "-maxrate", "9M", "-bufsize", "1835k", "-g", "12", "-bf", "2", "-flags", "+cgop",
         "-sc_threshold", "1000000000", "-pix_fmt", "yuv420p", "-aspect", "4:3", *args,
         str(video)],
        check=True,
    )  # fmt: skip
    subprocess.run(
        [str(FFMPEG), "-v", "error", "-y", "-f", "lavfi",
         "-i", "sine=frequency=440:sample_rate=48000:duration=6", "-ac", "2", "-c:a", "ac3",
         "-b:a", "192k", str(audio)],
        check=True,
    )  # fmt: skip
    return video, audio


@pytest.mark.skipif(FFMPEG is None, reason="ffmpeg not installed")
def test_every_gop_is_a_vobu_and_the_sound_starts_with_the_picture(tmp_path: Path):
    from dvd.author.pscheck import check
    from dvd.author.psmux import mux
    from dvd.author.vobu import scan_stream

    video, audio = _streams(tmp_path)
    out = mux(video, [audio], tmp_path / "own.mpg")

    assert out.stat().st_size % 2048 == 0
    report = check(out)
    assert report.ok, report.errors
    assert all(s.late == 0 for s in report.streams.values())
    scan = scan_stream(out, Fraction(25))
    gops = video.read_bytes().count(b"\x00\x00\x01\xb8")
    assert len(scan.vobus) == gops
    assert sum(v.pictures for v in scan.vobus) == 150
    assert scan.audio[0][0][1] == scan.vobus[0].start_pts == 45_000 + 3600
    for a, b in zip(scan.vobus, scan.vobus[1:], strict=False):
        assert b.start_pts == a.start_pts + a.pictures * 3600
    counts = subprocess.run(
        [str(FFPROBE), "-v", "error", "-count_frames", "-show_entries",
         "stream=codec_name,nb_read_frames", "-of", "csv=p=0", str(out)],
        capture_output=True, text=True, check=True,
    ).stdout.split()  # fmt: skip
    assert "mpeg2video,150," in counts and "ac3,188" in counts


@pytest.mark.skipif(not READY, reason="toolchain not installed")
def test_dvdauthor_takes_our_stream_and_we_author_it_the_same(tmp_path: Path):
    from dvd.author.dvdauthor import AuthorTitle, author
    from dvd.author.own import author_xml
    from dvd.author.psmux import mux

    video, audio = _streams(tmp_path, keys="1.2,3.68")
    mux(video, [audio], tmp_path / "film.mpg")
    title = AuthorTitle(vob="film.mpg", aspect="4:3", audio_langs=["tr"],
                        chapters=["0:00:00.000", "0:00:01.200", "0:00:03.680"])  # fmt: skip
    theirs = author([title], "pal", tmp_path, tmp_path / "dvdauthor")
    log = (tmp_path / "dvdauthor.log").read_text(encoding="utf-8", errors="replace")
    assert not [line for line in log.splitlines() if line.startswith(("ERR", "WARN"))], log
    # Each chapter starts a VOBU on its own frame: 1.2 s = frame 30, 3.68 s = frame 92.
    from dvd.ifo import read_disc

    cells = read_disc(theirs).titlesets[0].titles[0].cells
    assert [c.seconds for c in cells] == [1.2, 2.48, 2.32]
    sys.path.insert(0, str(Path(__file__).parent))
    from own_author import same_files

    ours = author_xml(tmp_path / "dvdauthor.xml", tmp_path / "own", provider="DVDAuthor 0.7.2+")
    assert same_files(ours, theirs) == []


@pytest.mark.skipif(not READY, reason="toolchain not installed")
def test_ntsc_film_with_subtitles_on_our_own_engine(tmp_path: Path):
    from dvd.build import build
    from dvd.probe import probe
    from dvd.project import new_project, save
    from dvd.project.edit import add_subtitle_file

    src = tmp_path / "film.mkv"
    subprocess.run(
        [str(FFMPEG), "-v", "error", "-y", "-f", "lavfi",
         "-i", "testsrc2=size=1280x720:rate=24000/1001:duration=6", "-f", "lavfi",
         "-i", "sine=duration=6", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "ac3",
         str(src)],
        check=True,
    )  # fmt: skip
    (tmp_path / "film.srt").write_text("1\n00:00:01,000 --> 00:00:03,000\nMerhaba\n", "utf-8")
    project = new_project(probe(src), tmp_path)
    project.disc.standard = "ntsc"
    project.titles[0].video.overrides = {"encoder": "ffmpeg"}
    project.titles[0].chapters = ["0:00", "0:02.5"]
    add_subtitle_file(project.titles[0], tmp_path / "film.srt", tmp_path)
    project_file = tmp_path / "ntsc.dvd.yaml"
    save(project, project_file)

    result = build(project_file, make_iso=False, authoring="own")

    problems = [w for w in result.warnings if w.startswith(("disc check", "disc rules"))]
    assert not problems, problems
    vob = probe(result.video_ts / "VTS_01_1.VOB")
    assert [s.codec for s in vob.subtitles] == ["dvd_subtitle"]
    out = subprocess.run([str(FFPROBE), "-v", "error", "-f", "dvdvideo", "-show_entries",
                          "format=duration", "-of", "csv=p=0", "-i", str(result.video_ts)],
                         capture_output=True, text=True)  # fmt: skip
    assert out.returncode == 0 and float(out.stdout) == pytest.approx(6.0, abs=0.3)
