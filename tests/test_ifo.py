import subprocess
from pathlib import Path

import pytest

from dvd import toolchain
from dvd.ifo.vm import decode

DIRS = toolchain.tool_dirs()
FFMPEG = toolchain.find_executable(["ffmpeg.exe", "ffmpeg"], DIRS)
READY = all(toolchain.find_executable([n], DIRS) for n in ("dvdauthor.exe", "spumux.exe")) \
    and FFMPEG is not None  # fmt: skip


@pytest.mark.parametrize(("raw", "text"), [
    ("3008000001830000", "CallSS VTSM root, resume cell 1"),
    ("3006000101830000", "JumpSS VTSM (vts 1, title 1) root"),
    ("3002000000020000", "JumpTT 2"),
    ("3003000000010000", "JumpVTS_TT 1"),
    ("3005000200010000", "JumpVTS_PTT 1:2"),
    ("2004000000000003", "LinkPGCN 3"),
    ("0001000000000005", "Goto 5"),
    ("7100000f00000000", "g15 = 0"),
    ("6100000e000f0000", "g14 = g15"),
    ("00a1000e00010005", "if (g14 == 1) Goto 5"),
    ("71a0000000010000", "if (g0 == 0) g0 = 1"),
    ("5600000004000000", "button = 1024"),
    ("3001000000000000", "Exit"),
    ("0000000000000000", "Nop"),
])  # fmt: skip
def test_decode_commands(raw, text):
    assert decode(bytes.fromhex(raw)) == text


@pytest.mark.skipif(not READY, reason="toolchain not installed")
def test_read_a_built_disc(tmp_path: Path):
    from dvd.author.uops import NO_SKIP
    from dvd.build import build
    from dvd.ifo import read_disc
    from dvd.ifo.vm import program
    from dvd.probe import probe
    from dvd.project import new_project, save
    from dvd.project.model import Intro

    meta = tmp_path / "meta.txt"
    chapter = "[CHAPTER]\nTIMEBASE=1/1000\nSTART={}\nEND={}\n"
    meta.write_text(";FFMETADATA1\n" + chapter.format(0, 3000) + chapter.format(3000, 6000),
                    encoding="utf-8")  # fmt: skip
    src = tmp_path / "film.mkv"
    subprocess.run(
        [str(FFMPEG), "-v", "error", "-y", "-f", "lavfi",
         "-i", "testsrc2=size=1280x720:rate=25:duration=6", "-f", "lavfi", "-i", "sine=duration=6",
         "-i", str(meta), "-map", "0", "-map", "1", "-map_chapters", "2", "-c:v", "libx264",
         "-preset", "ultrafast", "-c:a", "ac3", "-metadata:s:a:0", "language=tur", str(src)],
        check=True,
    )  # fmt: skip
    logo = tmp_path / "logo.mkv"
    subprocess.run([str(FFMPEG), "-v", "error", "-y", "-f", "lavfi",
                    "-i", "testsrc=size=640x360:rate=25:duration=2", "-c:v", "libx264",
                    "-preset", "ultrafast", str(logo)], check=True)  # fmt: skip
    project = new_project(probe(src), tmp_path)
    project.titles[0].video.overrides = {"encoder": "ffmpeg"}
    project.first_play = [Intro(file="logo.mkv", skippable=False)]
    project_file = tmp_path / "ifo.dvd.yaml"
    save(project, project_file)
    result = build(project_file, make_iso=False)

    disc = read_disc(result.video_ts)
    assert [(t.number, t.titleset, t.chapters) for t in disc.titles] == [(1, 1, 2), (2, 2, 1)]
    assert program(disc.first_play.pre)[0].strip().endswith("JumpTT 2")
    film, intro = disc.titlesets
    assert (film.standard, film.aspect, film.width) == ("pal", "16:9", 720)
    assert [(a.coding, a.language, a.channels) for a in film.audio] == [("ac3", "tr", 2)]
    assert film.chapters == [[(1, 1), (1, 2)]]
    pgc = film.titles[0]
    assert len(pgc.programs) == 2 and sum(c.seconds for c in pgc.cells) == pytest.approx(6, abs=0.2)
    assert any("CallSS VTSM root" in line for line in program(pgc.post))
    assert [m.entry for m in film.menus if m.entry] == ["root", "ptt"]
    assert film.menus[0].cells[0].still == 255  # the menu still waits for a key
    assert pgc.uops == 0 and intro.titles[0].uops == NO_SKIP
    from typer.testing import CliRunner

    from dvd.cli import app

    out = CliRunner().invoke(app, ["ifo", str(result.video_ts.parent), "--commands"])
    assert out.exit_code == 0, out.output
    assert "titleset 2: PAL 16:9" in out.output and "blocked: title_or_time_play" in out.output
    assert "CallSS VTSM root, resume cell 1" in out.output

    from dvd.qa.disc_check import check_disc

    assert check_disc(result.video_ts, [(2, 6.0)], 1, True, "menu", {1: NO_SKIP}) == []
    found = check_disc(result.video_ts, [(3, 9.0)], 0, True, "menu")
    assert "disc check: 2 titles on the disc, 1 expected" in found
    assert "disc check: title 1 has 2 chapters, 3 expected" in found
    assert any("lasts 6.0 s, 9.0 s expected" in f for f in found)
