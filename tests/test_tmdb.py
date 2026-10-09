import json
import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dvd.meta.tmdb import Client, TmdbError, guess_title  # noqa: E402

PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00"
       b"\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\xcf\xc0\xf0\x1f\x00\x05\x00\x01\xff"
       b"\x89\x99=\x1d\x00\x00\x00\x00IEND\xaeB`\x82")  # fmt: skip


class FakeTmdb:
    """Answers like api.themoviedb.org for one film; records the URLs asked for."""

    def __init__(self) -> None:
        self.urls: list[str] = []

    def __call__(self, url: str) -> bytes:
        self.urls.append(url)
        if "/search/movie" in url:
            results = [] if "year=2015" in url else [
                {"id": 157336, "title": "Yıldızlararası", "original_title": "Interstellar",
                 "release_date": "2014-11-05", "overview": "Bir grup kaşif..."}]  # fmt: skip
            return json.dumps({"results": results}).encode()
        if "/movie/157336" in url:
            return json.dumps({
                "id": 157336, "title": "Yıldızlararası", "original_title": "Interstellar",
                "release_date": "2014-11-05", "overview": "Bir grup kaşif...",
                "images": {
                    "backdrops": [
                        {"file_path": "/text.jpg", "iso_639_1": "en", "vote_average": 9},
                        {"file_path": "/clean.jpg", "iso_639_1": None, "vote_average": 5}],
                    "logos": [
                        {"file_path": "/logo-en.png", "iso_639_1": "en", "vote_average": 9},
                        {"file_path": "/logo-tr.png", "iso_639_1": "tr", "vote_average": 1}],
                    "posters": [],
                },
            }).encode()  # fmt: skip
        if url.startswith("https://image.tmdb.org/"):
            return PNG
        raise OSError(f"unexpected url {url}")


@pytest.mark.parametrize(("name", "title", "year"), [
    ("Interstellar (2014).mkv", "Interstellar", 2014),
    ("Interstellar.2014.1080p.BluRay.x264-GRP.mkv", "Interstellar", 2014),
    ("Yol_1982.mkv", "Yol", 1982),
    ("Babam ve Oğlum 1080p WEB-DL.mp4", "Babam ve Oğlum", None),
])  # fmt: skip
def test_guess_title_from_file_name(name, title, year):
    assert guess_title(Path(name)) == (title, year)


def test_search_and_film_prefer_turkish_and_clean_pictures(tmp_path, monkeypatch):
    monkeypatch.setenv("DVD_CACHE_DIR", str(tmp_path))
    fake = FakeTmdb()
    client = Client("anahtar", fetch=fake)
    matches = client.search("Interstellar", 2015)  # wrong year: searched again without it
    assert [(m.id, m.title, m.year) for m in matches] == [(157336, "Yıldızlararası", 2014)]
    assert "language=tr-TR" in fake.urls[0] and "api_key=anahtar" in fake.urls[0]
    film = client.film(157336)
    assert film.backdrops == ["/clean.jpg", "/text.jpg"]  # no text on the picture first
    assert film.logos == ["/logo-tr.png", "/logo-en.png"]  # Turkish logo first
    local = client.image(157336, "/logo-tr.png", "w500")
    assert local.read_bytes() == PNG and local.parent == tmp_path / "tmdb" / "157336"
    client.image(157336, "/logo-tr.png", "w500")
    assert sum("image.tmdb.org" in u for u in fake.urls) == 1  # cached
    with pytest.raises(TmdbError):
        client.image(157336, "../../etc/passwd", "w500")
    with pytest.raises(TmdbError):
        Client("")


def test_dialog_applies_backdrop_logo_and_name(tmp_path, monkeypatch):
    from PySide6.QtCore import QThreadPool
    from PySide6.QtWidgets import QApplication

    from dvd.gui.tmdb_dialog import TmdbDialog
    from dvd.project.model import Disc, Menus, Project, Title

    monkeypatch.setenv("DVD_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("DVD_SETTINGS", str(tmp_path / "settings.yaml"))
    app = QApplication.instance() or QApplication([])
    project = Project(disc=Disc(name="Interstellar", standard="pal"),
                      titles=[Title(source="Interstellar (2014).mkv")], menus=Menus())  # fmt: skip
    fake = FakeTmdb()
    dialog = TmdbDialog(project, Path("Interstellar (2014).mkv"),
                        client=lambda key: Client(key, fetch=fake))  # fmt: skip
    assert dialog.query.text() == "Interstellar" and dialog.year.text() == "2014"
    dialog.key.setText("anahtar")
    dialog.search()
    for _ in range(3):
        QThreadPool.globalInstance().waitForDone(10000)
        app.processEvents()
    assert dialog.film is not None and dialog.backdrops.count() == 2
    dialog.apply()
    QThreadPool.globalInstance().waitForDone(10000)
    app.processEvents()
    assert project.disc.name == "Yıldızlararası" and project.menus.tmdb_id == 157336
    assert project.menus.background.image.endswith("w1280_clean.jpg")
    assert project.menus.logo.endswith("w500_logo-tr.png")
    assert "tmdb_key: anahtar" in (tmp_path / "settings.yaml").read_text(encoding="utf-8")


def test_logo_replaces_the_title_on_the_main_page():
    import sys
    from fractions import Fraction

    from PySide6.QtGui import QColor, QImage

    sys.path.insert(0, str(Path(__file__).parent))
    from test_menu import expand, project

    from dvd.menu.render import render_page

    p, info = project()
    main = expand(p, info)[0]
    logo = QImage(400, 100, QImage.Format.Format_ARGB32)
    logo.fill(QColor(255, 0, 0))
    plain = render_page(main, (720, 576, Fraction(16, 9)))
    with_logo = render_page(main, (720, 576, Fraction(16, 9)), logo=logo)
    # Inside the title box: red logo with it, the light title text or dark backdrop without.
    logo_px = [with_logo.background.pixelColor(x, 70) for x in range(80, 200, 4)]
    assert all(c.red() > 150 and c.green() < 80 for c in logo_px)
    plain_px = [plain.background.pixelColor(x, 70) for x in range(80, 200, 4)]
    assert not any(c.red() > 150 and c.green() < 80 for c in plain_px)


class FakeTv(FakeTmdb):
    def __call__(self, url: str) -> bytes:
        if "/search/tv" in url:
            self.urls.append(url)
            return json.dumps({"results": [{"id": 1399, "name": "Taht Oyunları",
                                            "original_name": "Game of Thrones",
                                            "first_air_date": "2011-04-17"}]}).encode()  # fmt: skip
        if "/tv/1399/season/1" in url:
            self.urls.append(url)
            episodes = [{"episode_number": 1, "name": "Kış Geliyor"},
                        {"episode_number": 2, "name": "Kral Yolu"},
                        {"episode_number": 3, "name": ""}]  # fmt: skip
            return json.dumps({"episodes": episodes}).encode()
        if "/tv/1399" in url:
            self.urls.append(url)
            return json.dumps({"id": 1399, "name": "Taht Oyunları",
                               "original_name": "Game of Thrones", "first_air_date": "2011-04-17",
                               "images": {"backdrops": [{"file_path": "/bg.jpg"}],
                                          "logos": [{"file_path": "/logo.png",
                                                     "iso_639_1": "en"}]}}).encode()  # fmt: skip
        return super().__call__(url)


def test_series_info_from_tmdb(tmp_path, monkeypatch):
    from dvd.series import from_tmdb, name_from_folder

    monkeypatch.setenv("DVD_CACHE_DIR", str(tmp_path))
    assert name_from_folder(Path("Game.of.Thrones.S01")) == ("Game of Thrones", 1)
    assert name_from_folder(Path("Yalı Çapkını Sezon 2")) == ("Yalı Çapkını", 2)
    assert name_from_folder(Path("Belgesel")) == ("Belgesel", None)
    info = from_tmdb(Client("k", fetch=FakeTv()), "Game of Thrones", 1)
    assert info.name == "Taht Oyunları"
    assert info.episode_names == {1: "Kış Geliyor", 2: "Kral Yolu"}  # empty name left out
    assert info.backdrop.parent.name == "tv-1399" and info.logo.name == "w500_logo.png"
