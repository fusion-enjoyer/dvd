import subprocess
from pathlib import Path

import pytest

from dvd import toolchain
from dvd.ifo.vm import decode

DIRS = toolchain.tool_dirs()
FFMPEG = toolchain.find_executable(["ffmpeg.exe", "ffmpeg"], DIRS)
READY = all(toolchain.find_executable([n], DIRS) for n in ("dvdauthor.exe", "spumux.exe")) \
    and FFMPEG is not None  # fmt: skip


def assert_vts_ifo_matches(work: Path, video_ts: Path, fps) -> None:
    """Our VTS_01_0.IFO for a titleset without menus equals dvdauthor's, byte for byte."""
    import re

    from dvd.author.ifo_write import (
        AudioAttr,
        SubpictureAttr,
        TitlesetSpec,
        TitleSpec,
        write_vts,
    )
    from dvd.author.vobu import scan_stream
    from dvd.ifo import read_disc

    text = next(work.rglob("dvdauthor.xml")).read_text("utf-8")
    xml_dir = next(work.rglob("dvdauthor.xml")).parent
    vob_in = xml_dir / re.search(r'<vob file="([^"]+)" chapters', text)[1]
    ts = read_disc(video_ts).titlesets[0]
    scan = scan_stream(vob_in, fps)
    pgc = ts.titles[0]
    firsts = {c.first_sector for c in pgc.cells}
    post = re.search(r"<titles>.*?<post>(.*?)</post>", text, re.S)
    title = TitleSpec(scan, [i for i, v in enumerate(scan.vobus) if v.sector in firsts], "",
                      post[1] if post else "",
                      [(y << 16) | (cr << 8) | cb for y, cr, cb in pgc.palette])  # fmt: skip
    audio = [AudioAttr(a.coding, a.language, a.channels, k) for k, a in enumerate(ts.audio)]
    subs = [SubpictureAttr(s.language, k) for k, s in enumerate(ts.subpictures)]
    spec = TitlesetSpec(ts.standard, ts.aspect, [title], audio, subs)
    assert write_vts(spec) == (video_ts / "VTS_01_0.IFO").read_bytes()


def assert_nav_packs_match(work: Path, video_ts: Path, fps) -> None:
    """Our NAV packs for the film title equal the ones dvdauthor wrote, byte for byte."""
    import re

    from dvd.author.nav import CellMap, nav_pack
    from dvd.author.vobu import scan_stream
    from dvd.ifo import read_disc

    xml = next(work.rglob("dvdauthor.xml"))
    vob_in = xml.parent / re.search(r'<vob file="([^"]+)" chapters', xml.read_text("utf-8"))[1]
    ts = read_disc(video_ts).titlesets[0]
    scan = scan_stream(vob_in, fps)
    firsts = {c.first_sector for c in ts.titles[0].cells}
    cells = CellMap([i for i, v in enumerate(scan.vobus) if v.sector in firsts])
    vob = (video_ts / "VTS_01_1.VOB").read_bytes()
    for i, v in enumerate(scan.vobus):
        theirs = vob[v.sector * 2048 : (v.sector + 1) * 2048]
        ours = nav_pack(theirs, scan, cells, i, ts.standard == "pal", len(ts.audio),
                        len(ts.subpictures))  # fmt: skip
        units = scan.subpictures.get(0, [])
        if units and v.end_pts <= units[0][1]:
            # Before the first subpicture dvdauthor reads past its table (findspuidx never
            # says "none"), so its value there changes from run to run; ours says "later".
            theirs = theirs[:0x5A9] + ours[0x5A9:0x5AD] + theirs[0x5AD:]
        assert ours == theirs, f"VOBU {i} differs"


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
    from fractions import Fraction

    assert_nav_packs_match(tmp_path, result.video_ts, Fraction(25))
    from typer.testing import CliRunner

    from dvd.cli import app

    # Our compiler writes the menu's pre program byte for byte as dvdauthor did.
    from dvd.ifo.vmc import compile_program

    xml = next(tmp_path.rglob("dvdauthor.xml")).read_text(encoding="utf-8")
    root_pre = xml.split('<pgc entry="root">')[1].split("<pre>")[1].split("</pre>")[0]
    assert compile_program(root_pre, "vtsm") == film.menus[0].pre

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


@pytest.mark.parametrize(("text", "domain", "raw"), [
    ("g15 = 0", "vtsm", ["7100000f00000000"]),
    ("g14 = g15", "vtsm", ["6100000e000f0000"]),
    ("if (g0 == 0) g0 = 1", "vtsm", ["71a0000000010000"]),
    ("button = 1024", "vtsm", ["5600000004000000"]),
    ("jump title 1", "vtsm", ["3003000000010000"]),
    ("jump title 1 chapter 2", "vtsm", ["3005000200010000"]),
    ("jump title 2", "vmg", ["3002000000020000"]),
    ("jump menu 3", "vtsm", ["2004000000000003"]),
    ("call menu entry root", "title", ["3008000001830000"]),
    ("jump titleset 1 menu", "vmg", ["3006000101830000"]),
    ("exit", "vtsm", ["3001000000000000"]),
])  # fmt: skip
def test_compile_matches_dvdauthor(text, domain, raw):
    from dvd.ifo.vmc import compile_program

    assert [c.hex() for c in compile_program(text, domain)] == raw


def test_compiled_programs_read_back():
    from dvd.ifo.vm import decode
    from dvd.ifo.vmc import CompileError, compile_program

    program = compile_program(
        "g5 += 1; if (g5 == 3) { g5 = 0; g1 = 0; jump title 1; } jump cell 1;", "vtsm"
    )
    assert [decode(c) for c in program] == [
        "g5 += 1",
        "if (g5 != 3) Goto 6",
        "g5 = 0",
        "g1 = 0",
        "JumpVTS_TT 1",
        "LinkCN 1",
    ]
    # A test the command cannot hold becomes a Goto over it.
    assert [decode(c) for c in compile_program("if (audio == 1) button = 2048", "vtsm")] == [
        "if (audio != 1) Goto 3",
        "button = 2048",
    ]
    assert decode(compile_program("g3 = random(5)", "vtsm")[0]) == "g3 = random(5)"
    assert decode(compile_program("subtitle = 65", "vtsm")[0]) == "subtitle = 65"
    with pytest.raises(CompileError):
        compile_program("call menu entry root", "vtsm")
    with pytest.raises(CompileError):
        compile_program("teleport", "vtsm")


@pytest.mark.skipif(not READY, reason="toolchain not installed")
def test_vobu_scan_matches_dvdauthor_nav_packs(tmp_path: Path):
    """Our VOBU boundaries and reference picture ends are what dvdauthor writes into the
    NAV packs, for a film with an NTSC pulldown encode and a subtitle stream."""
    import re
    from fractions import Fraction

    from dvd.author.vobu import read_dsi, scan
    from dvd.build import build
    from dvd.probe import probe
    from dvd.project import new_project, save
    from dvd.project.edit import add_subtitle_file

    src = tmp_path / "film.mkv"
    subprocess.run(
        [str(FFMPEG), "-v", "error", "-y", "-f", "lavfi",
         "-i", "testsrc2=size=1280x720:rate=24000/1001:duration=5", "-f", "lavfi",
         "-i", "sine=duration=5", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "ac3",
         str(src)],
        check=True,
    )  # fmt: skip
    (tmp_path / "film.srt").write_text("1\n00:00:01,000 --> 00:00:03,000\nMerhaba\n", "utf-8")
    project = new_project(probe(src), tmp_path)
    project.disc.standard = "ntsc"
    project.titles[0].video.overrides = {"encoder": "ffmpeg"}
    project.menus = None
    add_subtitle_file(project.titles[0], tmp_path / "film.srt", tmp_path)
    project_file = tmp_path / "vobu.dvd.yaml"
    save(project, project_file)
    result = build(project_file, make_iso=False)

    xml = next(tmp_path.rglob("dvdauthor.xml"))
    vob_in = xml.parent / re.search(r'<vob file="([^"]+)" chapters', xml.read_text("utf-8"))[1]
    ours = scan(vob_in, Fraction(24000, 1001))
    theirs = read_dsi(result.video_ts / "VTS_01_1.VOB")
    assert len(ours) == len(theirs) > 5
    for o, t in zip(ours, theirs, strict=True):
        assert (o.sector, o.last_sector - o.sector, tuple(o.ref_ends)) == (t.lbn, t.end, t.refs)
    assert ours[1].start_pts == ours[0].end_pts  # units follow each other without a gap
    assert_nav_packs_match(tmp_path, result.video_ts, Fraction(24000, 1001))
    assert_vts_ifo_matches(tmp_path, result.video_ts, Fraction(24000, 1001))
    assert_own_disc_matches(tmp_path, result.video_ts, Fraction(24000, 1001), tmp_path / "own")
    # Players' reading code (libdvdread/libdvdnav through FFmpeg) opens our disc.
    out = subprocess.run([str(toolchain.find_executable(["ffprobe.exe", "ffprobe"], DIRS)),
                          "-v", "error", "-f", "dvdvideo", "-show_entries", "format=duration",
                          "-of", "csv=p=0", "-i", str(tmp_path / "own" / "VIDEO_TS")],
                         capture_output=True, text=True)  # fmt: skip
    assert out.returncode == 0 and float(out.stdout) == pytest.approx(5.0, abs=0.3)


def assert_own_disc_matches(work: Path, video_ts: Path, fps, out: Path) -> None:
    """Our own authoring of the same title: IFOs and VOB as dvdauthor wrote them."""
    import re

    from dvd.author import ifo_write
    from dvd.author.ifo_write import AudioAttr, SubpictureAttr, TitlesetSpec, TitleSpec
    from dvd.author.own import author_titles
    from dvd.author.vobu import scan_stream
    from dvd.ifo import read_disc

    text = next(work.rglob("dvdauthor.xml")).read_text("utf-8")
    xml_dir = next(work.rglob("dvdauthor.xml")).parent
    vob_in = xml_dir / re.search(r'<vob file="([^"]+)" chapters', text)[1]
    ts = read_disc(video_ts).titlesets[0]
    scan = scan_stream(vob_in, fps)
    firsts = {c.first_sector for c in ts.titles[0].cells}
    post = re.search(r"<titles>.*?<post>(.*?)</post>", text, re.S)
    title = TitleSpec(scan, [i for i, v in enumerate(scan.vobus) if v.sector in firsts], "",
                      post[1] if post else "")  # fmt: skip
    audio = [AudioAttr(a.coding, a.language, a.channels, k) for k, a in enumerate(ts.audio)]
    subs = [SubpictureAttr(s.language, k) for k, s in enumerate(ts.subpictures)]
    spec = TitlesetSpec(ts.standard, ts.aspect, [title], audio, subs)
    ours = author_titles(spec, [vob_in], out, provider="DVDAuthor 0.7.2+")
    for name in ("VIDEO_TS.IFO", "VIDEO_TS.BUP", "VTS_01_0.IFO", "VTS_01_0.BUP"):
        assert (ours / name).read_bytes() == (video_ts / name).read_bytes(), name
    mine, theirs = (ours / "VTS_01_1.VOB").read_bytes(), (video_ts / "VTS_01_1.VOB").read_bytes()
    assert len(mine) == len(theirs)
    for v in scan.vobus:  # dvdauthor's unstable subpicture field (see assert_nav_packs_match)
        at = v.sector * 2048 + 0x5A9
        if scan.subpictures.get(0) and v.end_pts <= scan.subpictures[0][0][1]:
            theirs = theirs[:at] + mine[at : at + 4] + theirs[at + 4 :]
    assert mine == theirs
    assert ifo_write.PROVIDER == "DVD Studyo"
