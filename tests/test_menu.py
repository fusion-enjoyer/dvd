from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from dvd.menu.layout import Button, auto_nav, chapter_page_ids, expand
from dvd.probe import Chapter, SourceInfo
from dvd.project.model import Audio, Disc, Menus, Project, Subtitle, Title


def project(chapters: int = 8, audio: int = 2, subs: int = 1, menus: dict | None = None):
    title = Title(
        source="film.mkv",
        audio=[Audio(track=i + 1, lang=("tr", "en")[i % 2], default=i == 1) for i in range(audio)],
        subtitles=[Subtitle(track=10 + i, lang="tr") for i in range(subs)],
    )
    p = Project(disc=Disc(name="Deneme", standard="pal"), titles=[title],
                menus=Menus.model_validate(menus or {}))  # fmt: skip
    marks = [Chapter(i * 400.0, (i + 1) * 400.0) for i in range(chapters)]
    info = SourceInfo(path=Path("film.mkv"), container="matroska", duration=3600.0, size=None,
                      bitrate=None, title=None, chapters=marks)  # fmt: skip
    return p, info


def test_standard_pages_link_to_each_other():
    p, info = project()
    pages = {pg.id: pg for pg in expand(p, info)}
    assert list(pages) == ["main", "chapters", "chapters-2", "languages"]
    main = pages["main"]
    assert [b.label for b in main.buttons] == ["Filmi oynat", "Bölümler", "Dil ayarları"]
    assert main.title == "Deneme"
    first, second = pages["chapters"], pages["chapters-2"]
    assert [b.id for b in first.buttons] == ["ch1", "ch2", "ch3", "ch4", "ch5", "ch6",
                                             "back", "next"]  # fmt: skip
    assert first.buttons[3].action.chapter == 4 and first.buttons[3].thumb == 1200.0
    assert [b.id for b in second.buttons] == ["ch7", "ch8", "prev", "back"]
    assert second.buttons[-2].action.page == "chapters"


def test_languages_follow_disc_stream_order():
    p, info = project()
    langs = next(pg for pg in expand(p, info) if pg.id == "languages")
    labels = {b.id: b.label for b in langs.buttons}
    assert labels["a0"] == "İngilizce  5.1"  # the default track is stream 0 on the disc
    assert labels["a1"] == "Türkçe  5.1"
    assert labels["s-off"] == "Kapalı" and labels["s0"] == "Türkçe"
    off = next(b for b in langs.buttons if b.id == "s-off")
    assert off.action.do == "subtitle" and off.action.stream is None
    assert [h for h, _ in langs.headings] == ["Ses", "Altyazı"]


def test_nothing_to_choose_drops_the_languages_button():
    p, info = project(audio=1, subs=0)
    main = expand(p, info)[0]
    assert [b.label for b in main.buttons] == ["Filmi oynat", "Bölümler"]


def test_auto_nav_moves_along_rows_and_columns():
    p, info = project()
    pages = {pg.id: pg for pg in expand(p, info)}
    nav = {b.id: b.nav for b in pages["chapters"].buttons}
    assert nav["ch1"]["right"] == "ch2" and nav["ch1"]["down"] == "ch4"
    assert nav["ch5"]["up"] == "ch2" and nav["ch4"]["down"] == "back"
    assert "left" not in nav["ch1"] and "up" not in nav["ch1"]  # edges: the highlight stays
    main = {b.id: b.nav for b in pages["main"].buttons}
    assert main["play"]["down"] == "chapters" and main["languages"]["up"] == "chapters"
    langs = {b.id: b.nav for b in pages["languages"].buttons}
    assert langs["a0"]["right"] == "s-off"


def test_hand_set_directions_are_kept():
    from dvd.project.model import MenuAction

    a = Button("a", "A", MenuAction(do="play"), (0.1, 0.1, 0.2, 0.1), {"down": "c"})
    b = Button("b", "B", MenuAction(do="play"), (0.1, 0.3, 0.2, 0.1))
    c = Button("c", "C", MenuAction(do="play"), (0.1, 0.5, 0.2, 0.1))
    auto_nav([a, b, c])
    assert a.nav["down"] == "c" and b.nav["up"] == "a" and c.nav["up"] == "b"


def test_custom_pages_and_validation():
    menus = {"pages": ["main", {"id": "extra", "title": "Ekstralar", "buttons": [
        {"id": "making", "label": "Kamera arkası", "action": {"do": "play", "chapter": 3}},
        {"id": "home", "label": "Geri", "action": {"do": "page", "page": "main"}},
    ]}]}  # fmt: skip
    p, info = project(menus=menus)
    pages = {pg.id: pg for pg in expand(p, info)}
    assert [b.label for b in pages["main"].buttons] == ["Filmi oynat"]  # extra is custom
    assert pages["extra"].buttons[0].nav["down"] == "home"
    with pytest.raises(ValidationError, match="unknown page"):
        Menus.model_validate({"pages": [{"id": "x", "buttons": [
            {"id": "b", "label": "B", "action": {"do": "page", "page": "nowhere"}}]}],
            "first": "x"})  # fmt: skip
    with pytest.raises(ValidationError, match="not a standard page"):
        Menus.model_validate({"pages": ["bilinmeyen"]})
    assert chapter_page_ids("chapters", 13) == ["chapters", "chapters-2", "chapters-3"]


@pytest.mark.parametrize("name", ["minimal", "sinematik", "2000ler"])
@pytest.mark.parametrize(("standard_h", "aspect"), [(576, (16, 9)), (480, (4, 3))])
def test_rendered_pages_fit_dvd_limits(standard_h, aspect, name):
    from fractions import Fraction

    from dvd.menu.render import render_page
    from dvd.menu.templates import template

    p, info = project(menus={"template": name})
    for page in expand(p, info):
        r = render_page(page, (720, standard_h, Fraction(*aspect)), None, None, template(name))
        assert (r.background.width(), r.background.height()) == (720, standard_h)
        boxes = []
        for overlay in (r.highlight, r.select):
            assert overlay.shape == (standard_h, 720, 4)
            assert len({tuple(c) for c in overlay.reshape(-1, 4)}) <= 4
        for b, (x0, y0, x1, y1) in r.buttons:
            assert all(v % 2 == 0 for v in (x0, y0, x1, y1))
            assert 0 <= x0 < x1 <= 720 and 0 <= y0 < y1 <= standard_h
            assert r.highlight[y0:y1, x0:x1, 3].any(), b.id  # every button lights up
            boxes.append((x0, y0, x1, y1))
        for i, a in enumerate(boxes):  # button areas never overlap
            for c in boxes[i + 1 :]:
                assert a[2] <= c[0] or c[2] <= a[0] or a[3] <= c[1] or c[3] <= a[1]
        inside = np.zeros((standard_h, 720), bool)
        for x0, y0, x1, y1 in boxes:
            inside[y0:y1, x0:x1] = True
        assert not r.highlight[~inside, 3].any()  # nothing lights up outside the buttons


def test_background_picture_covers_the_frame(tmp_path):
    from fractions import Fraction

    from PySide6.QtGui import QColor, QImage

    from dvd.menu.pictures import background_image
    from dvd.menu.render import render_page
    from dvd.project.model import MenuBackground

    p, info = project()
    img = QImage(400, 300, QImage.Format.Format_RGB32)
    img.fill(QColor(200, 30, 30))
    img.save(str(tmp_path / "bg.png"))
    bg = background_image(MenuBackground(image="bg.png"), Path("x"), info, tmp_path, (1024, 576))
    r = render_page(expand(p, info)[0], (720, 576, Fraction(16, 9)), bg)
    right = r.background.pixelColor(700, 300)  # far from the shaded text column
    assert right.red() > 100 and right.green() < 60
    plain = background_image(MenuBackground(color="#204060"), Path("x"), info, tmp_path,
                             (64, 36))  # fmt: skip
    assert plain.pixelColor(5, 5) == QColor("#204060")


def test_no_chapter_page_for_a_film_without_chapters():
    p, info = project(chapters=0)
    pages = expand(p, info)
    assert [pg.id for pg in pages] == ["main", "languages"]
    assert [b.label for b in pages[0].buttons] == ["Filmi oynat", "Dil ayarları"]


def test_languages_page_only_shows_columns_with_a_choice():
    p, info = project(audio=2, subs=0)
    langs = next(pg for pg in expand(p, info) if pg.id == "languages")
    assert [h for h, _ in langs.headings] == ["Ses"]
    p, info = project(audio=1, subs=2)
    langs = next(pg for pg in expand(p, info) if pg.id == "languages")
    assert [h for h, _ in langs.headings] == ["Altyazı"]


def test_simulator_walks_the_menus_with_the_disc_commands():
    from dvd.menu.simulator import Simulator

    p, info = project(chapters=8, audio=2, subs=1)
    sim = Simulator(expand(p, info), "main", subtitles_on=False)
    assert sim.page.id == "main" and sim.button.id == "play"
    sim.move("down")
    sim.press()
    assert sim.page.id == "chapters" and sim.button.id == "ch1"
    sim.move("down")  # ch4
    sim.move("down")  # bottom row: Ana menü
    sim.move("right")  # Sonraki ›
    sim.press()
    assert sim.page.id == "chapters-2"
    sim.press()  # ch7 is the first button there
    assert sim.state.playing == (1, 7)

    sim.menu_key()
    assert sim.page.id == "main" and sim.state.playing is None
    sim.move("down")
    sim.move("down")
    sim.press()
    assert sim.page.id == "languages"
    sim.move("down")  # a1: Türkçe
    sim.press()
    assert sim.state.audio == 1 and sim.button.id == "a1"  # cursor stays on the choice
    sim.move("right")  # nearest in the subtitle column
    while sim.button.id != "s0":
        sim.move("down")
    sim.press()
    assert sim.state.subtitle == 0 and sim.button.id == "s0"
    sim.move("up")
    sim.press()
    assert sim.state.subtitle is None and sim.button.id == "s-off"


def test_simulator_rejects_unknown_commands():
    from dvd.menu.simulator import Simulator, SimulatorError

    p, info = project()
    sim = Simulator(expand(p, info), "main")
    with pytest.raises(SimulatorError):
        sim.run("g3 = 1;")
    with pytest.raises(SimulatorError):
        sim.run("jump menu 9;")


def test_templates_place_the_main_buttons():
    p, info = project(menus={"template": "sinematik"})
    main = expand(p, info)[0]
    ys = {round(b.rect[1], 3) for b in main.buttons}
    assert len(ys) == 1  # one row
    xs = [b.rect[0] + b.rect[2] / 2 for b in main.buttons]
    assert sum(xs) / len(xs) == pytest.approx(0.5)  # centred
    assert main.buttons[0].nav["right"] == "chapters" and "down" not in main.buttons[0].nav
    p, info = project(menus={"template": "2000ler"})
    main = expand(p, info)[0]
    assert all(b.rect[0] + b.rect[2] / 2 == pytest.approx(0.5) for b in main.buttons)
    with pytest.raises(ValidationError):
        Menus.model_validate({"template": "yok"})


def test_uppercase_labels_keep_turkish_letters():
    from dvd.menu.render import _case
    from dvd.menu.templates import template

    assert _case("Dil ayarları", template("sinematik")) == "DİL AYARLARI"
    assert _case("Dil ayarları", template("minimal")) == "Dil ayarları"


def test_editor_changes_override_the_generated_buttons():
    menus = {"pages": [{"id": "main", "kind": "main", "edits": {
        "play": {"rect": [0.6, 0.7, 0.3, 0.06], "label": "Başlat"},
        "languages": {"up": "play"},
    }}, "chapters", "languages"]}  # fmt: skip
    p, info = project(menus=menus)
    main = expand(p, info)[0]
    play = main.buttons[0]
    assert play.label == "Başlat" and play.rect == (0.6, 0.7, 0.3, 0.06)
    langs = next(b for b in main.buttons if b.id == "languages")
    assert langs.nav["up"] == "play"  # hand-set, although "chapters" is nearer
    with pytest.raises(ValidationError, match="inside the frame"):
        outside = {"play": {"rect": [0.9, 0.5, 0.3, 0.1]}}
        Menus.model_validate({"pages": [{"id": "main", "kind": "main", "edits": outside}]})
