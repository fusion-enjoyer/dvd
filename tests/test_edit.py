from pathlib import Path

import pytest
from test_project import bluray_info

from dvd.project import new_project
from dvd.project.edit import (
    add_subtitle_file,
    guess_language,
    remove_subtitle_file,
    set_audio_included,
    set_default_audio,
    set_default_subtitle,
    set_subtitle_included,
)


@pytest.fixture
def setup(tmp_path: Path):
    info = bluray_info(tmp_path / "x.mkv")
    return new_project(info, tmp_path).titles[0], info, tmp_path


def test_remove_and_re_add_audio_keeps_source_order(setup):
    title, info, _ = setup
    set_audio_included(title, info, 1, False)
    assert [a.track for a in title.audio] == [2]
    set_audio_included(title, info, 1, True)
    assert [a.track for a in title.audio] == [1, 2]
    assert title.audio[0].channels == "5.1" and title.audio[0].bitrate == 448


def test_removing_the_default_audio_moves_default(setup):
    title, info, _ = setup
    set_default_audio(title, 2)
    set_audio_included(title, info, 2, False)
    assert title.audio[0].default


def test_subtitle_include_and_default(setup):
    title, _, _ = setup
    set_subtitle_included(title, 3, "tur", False)
    assert title.subtitles == []
    set_subtitle_included(title, 3, "tur", True)
    set_default_subtitle(title, 3)
    assert title.subtitles[0].lang == "tr" and title.subtitles[0].default
    set_default_subtitle(title, None)
    assert not title.subtitles[0].default


@pytest.mark.parametrize(
    ("name", "lang"),
    [("Film.tr.srt", "tr"), ("film_eng.srt", "en"), ("Film Türkçe.srt", "tr"),
     ("film.German.srt", "de"), ("altyazi.srt", "tr")],
)  # fmt: skip
def test_guess_language(name, lang):
    assert guess_language(Path(name)) == lang


def test_add_and_remove_srt_file(setup):
    title, _, project_dir = setup
    sub = add_subtitle_file(title, project_dir / "alt" / "film.en.srt", project_dir)
    assert sub.file == "alt/film.en.srt" and sub.lang == "en"
    set_default_subtitle(title, "alt/film.en.srt")
    assert sub.default
    remove_subtitle_file(title, "alt/film.en.srt")
    assert all(s.file is None for s in title.subtitles)
