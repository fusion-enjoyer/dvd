import zipfile
from pathlib import Path

import pytest
from typer.testing import CliRunner

from dvd.cli import app
from dvd.project import load, save
from dvd.project.archive import ArchiveError, archive, fingerprint, restore
from dvd.project.model import Disc, Intro, Menus, Project, Subtitle, Title


def _project(tmp_path: Path, monkeypatch) -> Path:
    home = tmp_path / "evim"
    (home / "altyazi").mkdir(parents=True)
    film = tmp_path / "videolar" / "film.mkv"
    film.parent.mkdir()
    film.write_bytes(b"video" * 1_000_000)  # 5 MB, more than the two fingerprint MiBs
    (home / "altyazi" / "film.srt").write_text("1\n00:00:01,000 --> 00:00:02,000\nA\n", "utf-8")
    (home / "logo.mkv").write_bytes(b"intro")
    (home / "arka.png").write_bytes(b"png")
    styles = tmp_path / "styles"
    styles.mkdir()
    (styles / "Salon.yaml").write_text("size: 0.06\n", encoding="utf-8")
    monkeypatch.setenv("DVD_STYLE_DIR", str(styles))
    monkeypatch.setenv("DVD_TEMPLATE_DIR", str(tmp_path / "templates"))
    monkeypatch.setenv("DVD_PROFILE_DIR", str(tmp_path / "profiles"))
    title = Title(source=str(film), subtitles=[Subtitle(file="altyazi/film.srt", lang="tr",
                                                        style="Salon")])  # fmt: skip
    menus = Menus.model_validate({"background": {"image": "arka.png"}})
    project = Project(disc=Disc(name="Film", standard="pal"), titles=[title],
                      first_play=[Intro(file="logo.mkv")], menus=menus)  # fmt: skip
    path = home / "film.dvd.yaml"
    save(project, path)
    return path


def test_archive_and_restore_without_the_sources(tmp_path: Path, monkeypatch):
    project_file = _project(tmp_path, monkeypatch)
    out = archive(project_file, tmp_path / "film.zip")
    names = set(zipfile.ZipFile(out).namelist())
    assert {"project.dvd.yaml", "manifest.yaml", "files/film.srt", "files/logo.mkv",
            "files/arka.png", "user/styles/Salon.yaml"} == names  # fmt: skip
    # On another computer: no Salon style yet, the film copied somewhere else.
    other = tmp_path / "baska"
    copies = other / "kopyalar"
    copies.mkdir(parents=True)
    film = tmp_path / "videolar" / "film.mkv"
    (copies / "ayni-film.mkv").write_bytes(film.read_bytes())
    (copies / "baska.mkv").write_bytes(b"x" * film.stat().st_size)  # same size, other bytes
    film.unlink()
    monkeypatch.setenv("DVD_STYLE_DIR", str(other / "styles"))
    done = restore(out, other / "proje", [copies])
    assert done.missing == [] and done.installed == ["user/styles/Salon.yaml"]
    restored = load(done.project)
    assert Path(restored.titles[0].source) == copies / "ayni-film.mkv"
    assert restored.titles[0].subtitles[0].file == "files/film.srt"
    assert (other / "proje" / "files" / "logo.mkv").read_bytes() == b"intro"
    assert (other / "styles" / "Salon.yaml").is_file()
    # Without the copy the source is reported missing.
    (copies / "ayni-film.mkv").unlink()
    assert restore(out, other / "proje2", [copies]).missing == ["film.mkv"]


def test_archive_with_the_sources_and_the_commands(tmp_path: Path, monkeypatch):
    project_file = _project(tmp_path, monkeypatch)
    runner = CliRunner()
    result = runner.invoke(app, ["archive", str(project_file), "--with-sources"])
    assert result.exit_code == 0, result.output
    out = project_file.with_name("film.zip")
    assert "sources/film.mkv" in zipfile.ZipFile(out).namelist()
    result = runner.invoke(app, ["restore", str(out), str(tmp_path / "geri")])
    assert result.exit_code == 0, result.output
    restored = load(tmp_path / "geri" / "project.dvd.yaml")
    assert restored.titles[0].source == "sources/film.mkv"
    assert fingerprint(tmp_path / "geri" / "sources" / "film.mkv") == \
        fingerprint(tmp_path / "videolar" / "film.mkv")  # fmt: skip
    (project_file.parent / "arka.png").unlink()
    with pytest.raises(ArchiveError, match="arka.png is missing"):
        archive(project_file, tmp_path / "x.zip")
