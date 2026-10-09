import os
import subprocess
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QThreadPool  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from dvd import toolchain  # noqa: E402
from dvd.gui.i18n import TEXTS, t  # noqa: E402
from dvd.gui.main_window import NAV, MainWindow  # noqa: E402
from dvd.gui.theme import load_fonts  # noqa: E402
from dvd.project import load  # noqa: E402

FFMPEG = toolchain.find_executable(["ffmpeg.exe", "ffmpeg"], toolchain.tool_dirs())


@pytest.fixture(scope="module")
def app():
    application = QApplication.instance() or QApplication([])
    load_fonts()
    return application


def test_every_label_key_has_turkish_text():
    keys = {k for steps in NAV.values() for _, k in steps}
    assert keys <= TEXTS["tr"].keys()
    assert t("missing.key") == "missing.key"


def test_empty_window_and_mode_switch(app):
    w = MainWindow()
    assert not w.build_button.isEnabled()
    assert [b.text() for b in w.nav_buttons.values()][0] == "1   Video"
    w.set_mode("pro")
    app.processEvents()
    visible = [b for b in w.nav.findChildren(type(w.build_button)) if b.isVisible()]
    assert len(w.nav_buttons) == 8 and all(b in w.nav_buttons.values() for b in visible)
    assert w.build_button.text() == "Build"


@pytest.mark.skipif(FFMPEG is None, reason="ffmpeg not installed")
def test_open_video_creates_project_and_updates_budget(app, tmp_path: Path):
    src = tmp_path / "Örnek Film.mkv"
    subprocess.run(
        [str(FFMPEG), "-v", "error", "-y", "-f", "lavfi",
         "-i", "testsrc2=size=1280x720:rate=24000/1001:duration=3",
         "-f", "lavfi", "-i", "sine=duration=3", "-map", "0", "-map", "1",
         "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "ac3", "-ac", "6", str(src)],
        check=True,
    )  # fmt: skip
    w = MainWindow()
    w._loaded(w._load(src))
    QThreadPool.globalInstance().waitForDone(60000)
    app.processEvents()
    project_file = tmp_path / "Örnek Film.dvd.yaml"
    assert project_file.is_file()
    assert w.current == "picture" and w.build_button.isEnabled()
    assert w.budget_label.text() == t("budget.fits")
    assert w.picture_page.well.image is not None  # preview frame arrived
    combo = w.picture_page.combos["viewing"]
    combo.setCurrentIndex(combo.findData("tasinabilir"))
    assert load(project_file).disc.profiles.viewing == "tasinabilir"
    assert w.plan.peak_kbps == 7_500


@pytest.mark.skipif(FFMPEG is None, reason="ffmpeg not installed")
def test_preview_source_and_disc_share_geometry(app, tmp_path: Path):
    from dvd.gui.preview import preview_frames
    from dvd.probe import probe
    from dvd.project.model import Title

    src = tmp_path / "kapsam.mkv"
    subprocess.run(
        [str(FFMPEG), "-v", "error", "-y", "-f", "lavfi",
         "-i", "testsrc2=size=1920x804:rate=25:duration=2", "-vf", "pad=1920:1080:0:138:black",
         "-c:v", "libx264", "-preset", "ultrafast", str(src)],
        check=True,
    )  # fmt: skip
    f = preview_frames(src, probe(src), Title(source=src.name), "pal", position=0.5)
    assert (f.source.width(), f.source.height()) == (1024, 576)
    assert (f.disc.width(), f.disc.height()) == (1024, 576)
    assert f.detected is not None and f.detected.top == 138
    for image in (f.source, f.disc):
        assert image.pixelColor(512, 30).value() < 20  # top bar
        assert image.pixelColor(512, 300).value() > 40  # picture
    assert f.frame == 25 and f.seconds == pytest.approx(1.0)
