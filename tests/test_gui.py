import os
import subprocess
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QThreadPool  # noqa: E402
from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402

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
    w.preview_seconds = 3.0

    def buttons(text):
        return [b for b in page.card.findChildren(QPushButton) if b.text() == t(text)]

    QThreadPool.globalInstance().waitForDone(60000)
    app.processEvents()
    buttons("chapters.thumb_here")[0].click()
    assert load(project_file).titles[0].thumbs == {"0:00:00.000": "0:00:03.000"}
    app.processEvents()
    buttons("chapters.thumb_auto")[0].click()
    assert load(project_file).titles[0].thumbs == {}
    QThreadPool.globalInstance().waitForDone(60000)


@pytest.mark.skipif(FFMPEG is None, reason="ffmpeg not installed")
def test_menu_page_toggles_menus_and_previews_pages(app, tmp_path: Path):
    src = tmp_path / "menu.mkv"
    subprocess.run(
        [str(FFMPEG), "-v", "error", "-y", "-f", "lavfi",
         "-i", "testsrc2=size=1280x720:rate=25:duration=8",
         "-f", "lavfi", "-i", "sine=duration=8", "-f", "lavfi", "-i", "sine=duration=8",
         "-map", "0", "-map", "1", "-map", "2", "-c:v", "libx264", "-preset", "ultrafast",
         "-c:a", "ac3", str(src)],
        check=True,
    )  # fmt: skip
    w = MainWindow(mode="pro")
    w.resize(1280, 800)
    w.show()
    w._loaded(w._load(src))
    QThreadPool.globalInstance().waitForDone(60000)
    project_file = tmp_path / "menu.dvd.yaml"
    menus = load(project_file).menus
    assert menus is not None and menus.background.frame.startswith("0:00:02.0")  # a quarter in
    w.show_page("menu")
    app.processEvents()
    QThreadPool.globalInstance().waitForDone(60000)
    app.processEvents()
    page = w.menu_page
    assert page.page_list.count() == 2  # main, languages (no chapters in the source -> one page)
    assert page.well.image is not None
    page.page_checks["chapters"].setChecked(False)
    assert [p.kind for p in load(project_file).menus.pages] == ["main", "languages"]
    page.enabled.setChecked(False)
    assert load(project_file).menus is None
    QThreadPool.globalInstance().waitForDone(60000)
    w.close()


@pytest.mark.skipif(FFMPEG is None, reason="ffmpeg not installed")
def test_menu_page_try_mode_follows_the_keyboard(app, tmp_path: Path):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    meta = tmp_path / "meta.txt"
    chapter = "[CHAPTER]\nTIMEBASE=1/1000\nSTART={}\nEND={}\n"
    meta.write_text(";FFMETADATA1\n" + "".join(chapter.format(s * 1000, s * 1000 + 2000)
                                               for s in (0, 2, 4)), encoding="utf-8")  # fmt: skip
    src = tmp_path / "dene.mkv"
    subprocess.run(
        [str(FFMPEG), "-v", "error", "-y", "-f", "lavfi",
         "-i", "testsrc2=size=1280x720:rate=25:duration=6", "-i", str(meta),
         "-map", "0", "-map_chapters", "1", "-c:v", "libx264", "-preset", "ultrafast", str(src)],
        check=True,
    )  # fmt: skip
    w = MainWindow(mode="pro")
    w.show()
    w._loaded(w._load(src))
    QThreadPool.globalInstance().waitForDone(60000)
    w.show_page("menu")
    app.processEvents()
    QThreadPool.globalInstance().waitForDone(60000)
    app.processEvents()
    page = w.menu_page
    page.lit.changed.emit("try")
    for key in (Qt.Key.Key_Down, Qt.Key.Key_Return, Qt.Key.Key_Right, Qt.Key.Key_Return):
        QTest.keyClick(page, key)
    assert page.sim.state.playing == (1, 2)
    assert "2. bölümden" in page.status.text()
    QTest.keyClick(page, Qt.Key.Key_Escape)
    assert page.sim.page.id == "main"
    w.close()


@pytest.mark.skipif(FFMPEG is None, reason="ffmpeg not installed")
def test_disc_page_edits_disc_settings_and_intros(app, tmp_path: Path):
    from dvd.project.model import Intro

    src = tmp_path / "disk.mkv"
    subprocess.run(
        [str(FFMPEG), "-v", "error", "-y", "-f", "lavfi",
         "-i", "testsrc2=size=1280x720:rate=25:duration=2",
         "-c:v", "libx264", "-preset", "ultrafast", str(src)],
        check=True,
    )  # fmt: skip
    w = MainWindow(mode="pro")
    w._loaded(w._load(src))
    QThreadPool.globalInstance().waitForDone(60000)
    page, project_file = w.disc_page, tmp_path / "disk.dvd.yaml"
    page.name.setText("Yaz Tatili 2026")
    page.name.editingFinished.emit()
    page.at_end.setCurrentIndex(page.at_end.findData("repeat"))
    page.media.setCurrentIndex(page.media.findData("dvd9"))
    page.add_intro(tmp_path / "logo.mkv")
    saved = load(project_file)
    assert saved.disc.name == "Yaz Tatili 2026" and saved.disc.media == "dvd9"
    assert saved.at_end == "repeat" and saved.first_play == [Intro(file="logo.mkv")]
    from PySide6.QtWidgets import QCheckBox

    lock = next(b for b in page.findChildren(QCheckBox) if b.text() == t("disc.intro_locked"))
    lock.setChecked(True)
    assert load(project_file).first_play == [Intro(file="logo.mkv", skippable=False)]
    page._remove(0)
    assert load(project_file).first_play == []
    assert w.name_label.text() == "Yaz Tatili 2026"
    QThreadPool.globalInstance().waitForDone(60000)  # let the preview finish before exit


@pytest.mark.skipif(FFMPEG is None, reason="ffmpeg not installed")
def test_menu_editor_moves_relabels_and_resets_buttons(app, tmp_path: Path):
    from dvd.gui.menu_canvas import overlapping

    assert overlapping({"a": (0, 0, 0.2, 0.1), "b": (0.1, 0.05, 0.2, 0.1),
                        "c": (0.5, 0.5, 0.1, 0.1)}) == [("a", "b")]  # fmt: skip
    src = tmp_path / "duzen.mkv"
    subprocess.run(
        [str(FFMPEG), "-v", "error", "-y", "-f", "lavfi",
         "-i", "testsrc2=size=1280x720:rate=25:duration=3",
         "-f", "lavfi", "-i", "sine=duration=3", "-f", "lavfi", "-i", "sine=duration=3",
         "-map", "0", "-map", "1", "-map", "2", "-c:v", "libx264", "-preset", "ultrafast",
         "-c:a", "ac3", str(src)],
        check=True,
    )  # fmt: skip
    w = MainWindow(mode="pro")
    w.show()
    w._loaded(w._load(src))
    QThreadPool.globalInstance().waitForDone(60000)
    w.show_page("menu")
    app.processEvents()
    QThreadPool.globalInstance().waitForDone(60000)
    app.processEvents()
    page, project_file = w.menu_page, tmp_path / "duzen.dvd.yaml"
    page.lit.changed.emit("edit")
    assert page.canvas.isVisible() and page.canvas.current == "play"
    page.canvas.edited.emit("play", (0.55, 0.7, 0.3, 0.06))
    page.label_edit.setText("Başlat")
    page.label_edit.editingFinished.emit()
    edit = load(project_file).menus.pages[0].edits["play"]
    assert edit.rect == (0.55, 0.7, 0.3, 0.06) and edit.label == "Başlat"
    QThreadPool.globalInstance().waitForDone(60000)
    app.processEvents()
    assert page.canvas.rects["play"] == (0.55, 0.7, 0.3, 0.06)  # re-rendered with the edit
    page._reset_button()
    assert load(project_file).menus.pages[0].edits == {}
    QThreadPool.globalInstance().waitForDone(60000)
    app.processEvents()
    # Arrow targets by hand: "up" from Play wraps round to the last button.
    up = page.nav_combos["up"]
    assert up.itemText(0) == t("menu.edit.nav_auto", target=t("menu.edit.stay"))
    last = page.canvas.buttons[-1]
    up.setCurrentIndex(up.findData(last.id))
    assert load(project_file).menus.pages[0].edits["play"].up == last.id
    QThreadPool.globalInstance().waitForDone(60000)
    app.processEvents()
    play = next(b for b in page.canvas.buttons if b.id == "play")
    assert play.nav["up"] == last.id and page.nav_combos["up"].currentData() == last.id
    page.nav_combos["up"].setCurrentIndex(0)
    assert load(project_file).menus.pages[0].edits["play"].up is None
    QThreadPool.globalInstance().waitForDone(60000)
    app.processEvents()
    # A text layer: added, moved, retyped, removed.
    page._add_layer("text")
    QThreadPool.globalInstance().waitForDone(60000)
    app.processEvents()
    assert page.canvas.current == "layer-0" and "layer-0" in page.canvas.rects
    page.canvas.edited.emit("layer-0", (0.1, 0.1, 0.5, 0.1))
    page.label_edit.setText("Yönetmen kurgusu")
    page.label_edit.editingFinished.emit()
    layer = load(project_file).menus.pages[0].layers[0]
    assert layer.rect == (0.1, 0.1, 0.5, 0.1) and layer.text == "Yönetmen kurgusu"
    QThreadPool.globalInstance().waitForDone(60000)
    app.processEvents()
    assert page.reset.text() == t("menu.layer.remove")
    page._reset_button()
    assert load(project_file).menus.pages[0].layers == []
    QThreadPool.globalInstance().waitForDone(60000)
    w.close()


@pytest.mark.skipif(FFMPEG is None, reason="ffmpeg not installed")
def test_season_folder_becomes_disc_projects(app, tmp_path: Path, monkeypatch):
    import json

    from dvd.gui.series_dialog import SeriesDialog
    from dvd.meta.tmdb import Client
    from dvd.project.season import read_season

    monkeypatch.setenv("DVD_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("DVD_SETTINGS", str(tmp_path / "settings.yaml"))
    monkeypatch.delenv("DVD_TMDB_KEY", raising=False)
    season_dir = tmp_path / "Dizi.S01"
    season_dir.mkdir()
    for n in (1, 2):
        subprocess.run(
            [str(FFMPEG), "-v", "error", "-y", "-f", "lavfi",
             "-i", "testsrc2=size=640x360:rate=25:duration=2", "-f", "lavfi",
             "-i", "sine=duration=2", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac",
             str(season_dir / f"Dizi.S01E0{n}.mkv")],
            check=True,
        )  # fmt: skip

    def fake(url: str) -> bytes:  # TMDB knows the series but has no pictures
        if "/search/tv" in url:
            return json.dumps({"results": [{"id": 7, "name": "Dizi Adı"}]}).encode()
        if "/tv/7/season/1" in url:
            return json.dumps({"episodes": [{"episode_number": 2, "name": "Son"}]}).encode()
        return json.dumps({"id": 7, "name": "Dizi Adı", "images": {}}).encode()

    reported = []
    season = read_season(season_dir, lambda n, count: reported.append((n, count)))
    assert reported == [(0, 2), (1, 2)] and (season.name, season.number) == ("Dizi", 1)
    dialog = SeriesDialog(season, client=lambda key: Client(key, fetch=fake))
    assert dialog.name.text() == "Dizi.S01" and not dialog.tmdb.isChecked()
    assert dialog.discs.count() == 1 and "S01E01 – S01E02 · 2 bölüm" in dialog.discs.item(0).text()
    dialog.key.setText("anahtar")
    assert dialog.tmdb.isChecked()
    dialog.media.setCurrentIndex(dialog.media.findData("dvd5"))
    written = []
    dialog.created.connect(written.append)
    dialog.create()
    QThreadPool.globalInstance().waitForDone(30000)
    app.processEvents()
    assert written == [[season_dir / "Dizi Adı 1. Sezon.dvd.yaml"]]
    project = load(written[0][0])
    assert project.disc.media == "dvd5" and project.menus.template == "dizi"
    assert [t.name for t in project.titles] == ["1. bölüm", "2. Son"]
    assert "tmdb_key: anahtar" in (tmp_path / "settings.yaml").read_text(encoding="utf-8")
    again = SeriesDialog(season)  # the file is there now; the default name is the folder's
    again.name.setText("Dizi Adı 1. Sezon")
    assert again.note.text() == t("series.exists", count=1)


@pytest.mark.skipif(FFMPEG is None, reason="ffmpeg not installed")
def test_text_subtitles_can_go_into_the_band(app, tmp_path: Path):
    from PySide6.QtWidgets import QCheckBox

    from dvd.gui.pages import TracksPage
    from dvd.probe import probe
    from dvd.project import new_project
    from dvd.project.edit import add_subtitle_file

    src = tmp_path / "film.mkv"
    subprocess.run(
        [str(FFMPEG), "-v", "error", "-y", "-f", "lavfi",
         "-i", "testsrc2=size=1920x800:rate=24:duration=1", "-c:v", "libx264",
         "-preset", "ultrafast", str(src)],
        check=True,
    )  # fmt: skip
    (tmp_path / "film.tr.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nA\n", "utf-8")
    (tmp_path / "film.sup").write_bytes(b"")
    info = probe(src)
    project = new_project(info, tmp_path)
    title = project.titles[0]
    add_subtitle_file(title, tmp_path / "film.tr.srt", tmp_path)
    add_subtitle_file(title, tmp_path / "film.sup", tmp_path)
    page = TracksPage("subs")
    page.show_project(project, info, tmp_path, "pro")
    boxes = [b for b in page.findChildren(QCheckBox) if b.text() == t("tracks.band")]
    assert len(boxes) == 1  # the PGS file keeps its own place
    boxes[0].setChecked(True)
    assert title.subtitles[0].band and not title.subtitles[1].band
    keep = [b for b in page.findChildren(QCheckBox) if b.text() == t("tracks.keep_colour")]
    assert len(keep) == 1  # only the PGS file
    keep[0].setChecked(True)
    assert title.subtitles[1].keep_colour and not title.subtitles[0].keep_colour
