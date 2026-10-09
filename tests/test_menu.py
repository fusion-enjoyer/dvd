from pathlib import Path

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
