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
    assert (f.disc.width(), f.disc.height()) == (720, 576)  # stored pixels, drawn at 16:9
    # The source keeps about its own resolution: 804 picture lines instead of 432.
    assert f.source.height() > 1000
    assert f.source.width() / f.source.height() == pytest.approx(16 / 9, abs=0.01)
    assert f.detected is not None and f.detected.top == 138
    for image in (f.source, f.disc):
        w, h = image.width(), image.height()
        assert image.pixelColor(w // 2, h * 30 // 576).value() < 20  # top bar
        assert image.pixelColor(w // 2, h * 300 // 576).value() > 40  # picture
    assert f.frame == 25 and f.seconds == pytest.approx(1.0)
    g = preview_frames(src, probe(src), Title(source=src.name), "pal", frame=26)
    assert g.frame == 26 and g.seconds == pytest.approx(26 / 25)


@pytest.mark.skipif(FFMPEG is None, reason="ffmpeg not installed")
def test_pro_editor_changes_crop_and_preprocessing(app, tmp_path: Path):
    from dvd.project.model import Crop

    src = tmp_path / "duzen.mkv"
    subprocess.run(
        [str(FFMPEG), "-v", "error", "-y", "-f", "lavfi",
         "-i", "testsrc2=size=1920x804:rate=25:duration=2", "-vf", "pad=1920:1080:0:138:black",
         "-c:v", "libx264", "-preset", "ultrafast", str(src)],
        check=True,
    )  # fmt: skip
    w = MainWindow(mode="pro")
    w._loaded(w._load(src))
    QThreadPool.globalInstance().waitForDone(60000)
    app.processEvents()
    editor, project_file = w.picture_page.editor, tmp_path / "duzen.dvd.yaml"
    assert "138" in editor.crop_hint.text()  # detected bars shown under "Otomatik"

    editor.crop_mode.setCurrentIndex(editor.crop_mode.findData("manual"))
    assert load(project_file).titles[0].video.crop == Crop(top=138, bottom=138)
    editor.spins["left"].setValue(20)
    editor.timer.timeout.emit()  # skip the debounce
    assert load(project_file).titles[0].video.crop == Crop(top=138, bottom=138, left=20)

    kernel = editor.combos["kernel"]
    kernel.setCurrentIndex(kernel.findData("lanczos"))
    deband = editor.combos["deband"]
    deband.setCurrentIndex(deband.findData(3))
    assert load(project_file).titles[0].video.overrides == {"kernel": "lanczos", "deband": 3}
    kernel.setCurrentIndex(0)  # back to the profile value
    assert load(project_file).titles[0].video.overrides == {"deband": 3}
    assert deband.itemText(0) == t("pro.from_profile_value", value="1")
    QThreadPool.globalInstance().waitForDone(60000)
    app.processEvents()
    assert w.picture_page.well.image is not None


@pytest.mark.skipif(FFMPEG is None, reason="ffmpeg not installed")
def test_frame_step_and_zoom(app, tmp_path: Path):
    src = tmp_path / "adim.mkv"
    subprocess.run(
        [str(FFMPEG), "-v", "error", "-y", "-f", "lavfi",
         "-i", "testsrc2=size=1280x720:rate=25:duration=2",
         "-c:v", "libx264", "-preset", "ultrafast", str(src)],
        check=True,
    )  # fmt: skip
    w = MainWindow(mode="pro")
    w.resize(1280, 800)
    w._loaded(w._load(src))
    QThreadPool.globalInstance().waitForDone(60000)
    app.processEvents()
    first = w.preview_frame
    assert first == 20  # 40% of 50 frames
    w.step_frame(1)
    w.step_frame(1)  # the first request's result is dropped when it lands late
    QThreadPool.globalInstance().waitForDone(60000)
    app.processEvents()
    assert w.preview_frame == 21  # each step starts from the last shown frame
    assert "kare 21" in w.picture_page.timecode.text()

    well = w.picture_page.well
    assert (well.image.width(), well.image.height()) == (720, 576)
    well.set_zoom(2)
    target = well._target()
    assert target.height() == 2 * 576 and target.width() == pytest.approx(2 * 576 * 16 / 9)
    assert target.top() <= 0 and target.bottom() >= well.height()  # covers the well


@pytest.mark.skipif(FFMPEG is None, reason="ffmpeg not installed")
def test_chapters_page_edits_and_shows_frames(app, tmp_path: Path):
    from dvd.project.model import ChapterEvery

    meta = tmp_path / "meta.txt"
    chapter = "[CHAPTER]\nTIMEBASE=1/1000\nSTART={}\nEND={}\n"
    meta.write_text(";FFMETADATA1\n" + chapter.format(0, 4000) + chapter.format(4000, 8000),
                    encoding="utf-8")  # fmt: skip
    src = tmp_path / "bolum.mkv"
    subprocess.run(
        [str(FFMPEG), "-v", "error", "-y", "-f", "lavfi",
         "-i", "testsrc2=size=1280x720:rate=25:duration=8", "-i", str(meta),
         "-map", "0", "-map_chapters", "1", "-c:v", "libx264", "-preset", "ultrafast", str(src)],
        check=True,
    )  # fmt: skip
    w = MainWindow(mode="pro")
    w._loaded(w._load(src))
    QThreadPool.globalInstance().waitForDone(60000)
    app.processEvents()
    page, project_file = w.chapters_page, tmp_path / "bolum.dvd.yaml"
    assert page.mode.currentData() == "from-source" and page.grid.rowCount() >= 2
    assert page.thumbs  # frames for the chapter list arrived

    page.mode.setCurrentIndex(page.mode.findData("manual"))
    assert load(project_file).titles[0].chapters == ["0:00:00.000", "0:00:04.000"]
    w.preview_seconds = 6.0
    page._add()
    page._remove(1)
    assert load(project_file).titles[0].chapters == ["0:00:00.000", "0:00:06.000"]
    page.mode.setCurrentIndex(page.mode.findData("every"))
    assert load(project_file).titles[0].chapters == ChapterEvery(every=5)
    QThreadPool.globalInstance().waitForDone(60000)
