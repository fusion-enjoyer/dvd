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
