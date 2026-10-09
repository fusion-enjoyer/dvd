import subprocess
from pathlib import Path

import pytest

from dvd import toolchain
from dvd.series import Episode, parse_episode, plan_set, scan_folder

FFMPEG = toolchain.find_executable(["ffmpeg.exe", "ffmpeg"], toolchain.tool_dirs())


@pytest.mark.parametrize(("name", "expected"), [
    ("Dizi.S01E02.1080p.WEB", (1, 2)),
    ("dizi s2e10 final", (2, 10)),
    ("Dizi - 1x05 - Başlık", (1, 5)),
    ("Dizi Sezon 3 Bölüm 7", (3, 7)),
    ("Belgesel Bölüm 4", (None, 4)),
    ("Episode 12", (None, 12)),
    ("Dizi 2019 1080p", None),
])  # fmt: skip
def test_parse_episode(name, expected):
    assert parse_episode(name) == expected


def test_scan_folder_orders_episodes_and_skips_extras(tmp_path: Path):
    for name in ("Dizi.S01E10.mkv", "Dizi.S01E02.mkv", "Dizi.S01E01.mkv", "Dizi.S01E01.sample.mkv",
                 "kapak.jpg", "Dizi.S01E03.srt", "Fragman.mkv"):  # fmt: skip
        (tmp_path / name).write_bytes(b"")
    assert [e.code for e in scan_folder(tmp_path)] == ["S01E01", "S01E02", "S01E10"]
    (tmp_path / "Dizi 1x02.mp4").write_bytes(b"")
    with pytest.raises(ValueError, match="S01E02"):
        scan_folder(tmp_path)


def _season(minutes: list[float]) -> list[Episode]:
    return [Episode(Path(f"e{i}.mkv"), 1, i + 1, m * 60) for i, m in enumerate(minutes)]


def test_plan_uses_the_fewest_discs_that_reach_the_target():
    ten = _season([45] * 10)  # 450 min
    s = plan_set(ten, "dvd9", "iyi", [448])
    assert s.count == 3 and [len(d) for d in s.discs] in ([4, 3, 3], [3, 4, 3], [3, 3, 4])
    assert min(s.video_kbps) >= 5000
    fewer = plan_set(ten, "dvd9", "standart", [448])
    assert fewer.count < s.count and min(fewer.video_kbps) >= 4000
    assert [e.number for d in s.discs for e in d] == list(range(1, 11))  # order kept


def test_plan_balances_unequal_episodes():
    s = plan_set(_season([90, 30, 30, 30, 30, 30, 30, 90]), "dvd9", "yuksek", [448])
    lengths = [sum(e.duration for e in d) / 60 for d in s.discs]
    assert max(lengths) - min(lengths) <= 90  # no disc with one short episode alone


@pytest.mark.skipif(FFMPEG is None, reason="ffmpeg not installed")
def test_series_new_writes_a_project_per_disc(tmp_path: Path):
    from typer.testing import CliRunner

    from dvd.cli import app
    from dvd.project import load

    season = tmp_path / "Dizi S01"
    season.mkdir()
    for n in (1, 2, 3):
        # Episode 2 has its languages in the other order: tracks are matched by language.
        langs = ("tur", "eng") if n != 2 else ("eng", "tur")
        subprocess.run(
            [str(FFMPEG), "-v", "error", "-y", "-f", "lavfi",
             "-i", "testsrc2=size=640x360:rate=25:duration=4",
             "-f", "lavfi", "-i", "sine=duration=4", "-f", "lavfi", "-i", "sine=duration=4",
             "-map", "0", "-map", "1", "-map", "2", "-c:v", "libx264", "-preset", "ultrafast",
             "-c:a", "aac", "-metadata:s:a:0", f"language={langs[0]}",
             "-metadata:s:a:1", f"language={langs[1]}", str(season / f"Dizi.S01E0{n}.mkv")],
            check=True,
        )  # fmt: skip
    runner = CliRunner()
    result = runner.invoke(app, ["series", "plan", str(season)])
    assert result.exit_code == 0, result.output
    assert "disc 1/1: S01E01-S01E03  3 episodes" in result.output
    result = runner.invoke(app, ["series", "new", str(season), "--name", "Dizi S01"])
    assert result.exit_code == 0, result.output
    project = load(season / "Dizi S01.dvd.yaml")
    assert [t.source for t in project.titles] == [f"Dizi.S01E0{n}.mkv" for n in (1, 2, 3)]
    first, second = project.titles[0].audio, project.titles[1].audio
    assert [a.lang for a in first] == [a.lang for a in second] == ["tr", "en"]
    assert [a.track for a in second] == [2, 1]  # English is stream 1 in episode 2
    assert project.series.name == "Dizi S01" and project.titles[1].name == "2. bölüm"
    assert [pg.kind for pg in project.menus.pages] == ["main", "episodes", "languages"]


@pytest.mark.skipif(FFMPEG is None, reason="ffmpeg not installed")
def test_series_disc_builds_with_episode_menu(tmp_path: Path):
    from dvd.build import build
    from dvd.probe import probe
    from dvd.project import load, new_series_project, save
    from dvd.project.model import MenuPage, Menus, SeriesDisc

    infos = []
    for n in (1, 2):
        path = tmp_path / f"Dizi.S01E0{n}.mkv"
        subprocess.run(
            [str(FFMPEG), "-v", "error", "-y", "-f", "lavfi",
             "-i", "testsrc2=size=640x360:rate=25:duration=3",
             "-f", "lavfi", "-i", "sine=duration=3", "-c:v", "libx264", "-preset", "ultrafast",
             "-c:a", "aac", str(path)],
            check=True,
        )  # fmt: skip
        infos.append(probe(path))
    project = new_series_project(infos, tmp_path, "Dizi S01")
    project.series = SeriesDisc(name="Dizi S01", disc=1, discs=2)
    project.menus = Menus(pages=[MenuPage(id="main", kind="main"),
                                 MenuPage(id="episodes", kind="episodes")])  # fmt: skip
    for title in project.titles:
        title.video.overrides = {"encoder": "ffmpeg"}
    project_file = tmp_path / "dizi.dvd.yaml"
    save(project, project_file)
    assert load(project_file).series.discs == 2

    result = build(project_file, make_iso=False)

    xml = next(tmp_path.rglob("dvdauthor.xml")).read_text(encoding="utf-8")
    assert "<post>if (g1 == 1) jump title 2; call menu;</post>" in xml
    assert "g1 = 1; jump title 1;" in xml and "g1 = 0; jump title 2;" in xml
    assert (result.video_ts / "VTS_01_0.VOB").is_file()
