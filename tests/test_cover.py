import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from dvd import toolchain
from dvd.cli import app
from dvd.output.cover import CoverError, CoverInfo, preview, write_cover

FFMPEG = toolchain.find_executable(["ffmpeg.exe", "ffmpeg"], toolchain.tool_dirs())


def test_cover_layout_and_label_cut_lines():
    from PySide6.QtGui import QColor, QImage

    picture = QImage(400, 200, QImage.Format.Format_RGB32)
    picture.fill(QColor("#4080C0"))
    info = CoverInfo("Film", "Disk 1 / 2", ["Süre: 1 sa 40 dk"], picture)
    case = preview(info, "case", dpmm=4)
    assert (case.width(), case.height()) == (297 * 4, 210 * 4)  # A4 landscape
    assert case.pixelColor(5, 5).name() == "#ffffff"  # outside the bleed: paper
    x0 = (297 - 273) / 2
    spine = case.pixelColor(round((x0 + 129.5 + 7) * 4), round(30 * 4))
    front = case.pixelColor(round((x0 + 200) * 4), round(40 * 4))
    assert spine.lightness() < 40 and front.blue() > 150  # dark spine, the picture in front
    label = preview(info, "label", dpmm=4)
    assert label.pixelColor(105 * 4, 85 * 4).name() == "#ffffff"  # the hub stays clear
    assert label.pixelColor(105 * 4, round((85 + 40) * 4)).name() != "#ffffff"
    with pytest.raises(CoverError):
        write_cover(info, Path("x.pdf"), "box")


@pytest.mark.skipif(FFMPEG is None, reason="ffmpeg not installed")
def test_cover_command_writes_both_pdfs(tmp_path: Path):
    from dvd.probe import probe
    from dvd.project import new_project, save

    src = tmp_path / "film.mkv"
    subprocess.run(
        [str(FFMPEG), "-v", "error", "-y", "-f", "lavfi",
         "-i", "testsrc2=size=1280x720:rate=25:duration=3", "-f", "lavfi", "-i", "sine=duration=3",
         "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "ac3", str(src)],
        check=True,
    )  # fmt: skip
    project = new_project(probe(src), tmp_path)
    project.disc.name = "Kapak Denemesi"
    path = tmp_path / "kapak.dvd.yaml"
    save(project, path)
    result = CliRunner().invoke(app, ["cover", str(path), "--slim"])
    assert result.exit_code == 0, result.output
    folder = tmp_path / "Kapak Denemesi"
    for name in ("Kapak Denemesi - kapak.pdf", "Kapak Denemesi - etiket.pdf"):
        data = (folder / name).read_bytes()
        assert data.startswith(b"%PDF") and b"/MediaBox" in data and len(data) > 20_000
