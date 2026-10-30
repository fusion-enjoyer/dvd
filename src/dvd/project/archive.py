"""A project archive: one .zip with what it takes to make the disc again elsewhere.

Inside: the project file with its paths pointing into the archive, the small files it uses
(subtitle files, intro and hidden videos, menu pictures and logos) under `files/`, the user
template, subtitle styles and profile it names under `user/`, and `manifest.yaml` naming
each source video with its size and a fingerprint (SHA-256 of its size and first and last
MiB), so a copy found on another disk can be recognised. The sources themselves go in only
when asked; they are usually tens of gigabytes.
"""

from __future__ import annotations

import hashlib
import shutil
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import yaml

from dvd import __version__
from dvd.project.io import dumps, load, save
from dvd.project.model import Project

PROJECT_NAME = "project.dvd.yaml"
VIDEO = {".mkv", ".m2ts", ".mts", ".mp4", ".m4v", ".ts", ".mov", ".avi", ".mpg", ".vob"}
CHUNK = 1 << 20


class ArchiveError(ValueError):
    pass


def fingerprint(path: Path) -> str:
    """SHA-256 of the size and the first and last MiB: quick on a 40 GB file, and two
    different videos of the same size practically never share it."""
    size = path.stat().st_size
    h = hashlib.sha256(str(size).encode())
    with path.open("rb") as f:
        h.update(f.read(CHUNK))
        if size > 2 * CHUNK:
            f.seek(size - CHUNK)
            h.update(f.read(CHUNK))
    return h.hexdigest()


def _absolute(project_dir: Path, value: str) -> Path:
    p = Path(value)
    return p if p.is_absolute() else (project_dir / p).resolve()


def _file_fields(project: Project):
    """(object, attribute) of every field naming a file, other than the sources."""
    for title in project.titles:
        for sub in title.subtitles:
            if sub.file:
                yield sub, "file"
    for intro in project.first_play:
        yield intro, "file"
    menus = project.menus
    if menus is not None:
        if menus.logo:
            yield menus, "logo"
        if menus.background.image:
            yield menus.background, "image"
        for page in menus.pages:
            for clip in page.hidden:
                yield clip, "file"
            for layer in page.layers:
                if layer.image:
                    yield layer, "image"


@dataclass
class Restored:
    project: Path
    missing: list[str] = field(default_factory=list)  # sources not found yet
    installed: list[str] = field(default_factory=list)  # user templates/styles/profiles added
    kept: list[str] = field(default_factory=list)  # already there with other contents: kept


def archive(project_file: Path, out: Path, with_sources: bool = False) -> Path:
    project_file = Path(project_file).resolve()
    project = load(project_file)
    base = project_file.parent
    copy = project.model_copy(deep=True)
    entries: dict[str, Path] = {}  # name in the archive -> file on disk
    taken: set[str] = set()

    def place(path: Path, folder: str) -> str:
        name = f"{folder}/{path.name}"
        n = 2
        while name in taken and entries.get(name) != path:
            name = f"{folder}/{path.stem}-{n}{path.suffix}"
            n += 1
        taken.add(name)
        entries[name] = path
        return name

    for obj, attr in _file_fields(copy):
        path = _absolute(base, getattr(obj, attr))
        if not path.is_file():
            raise ArchiveError(f"{getattr(obj, attr)} is missing")
        setattr(obj, attr, place(path, "files"))
        for twin in (".idx", ".sub"):  # a VobSub pair travels together
            other = path.with_suffix(twin)
            if path.suffix.lower() in (".idx", ".sub") and other.is_file():
                place(other, "files")
    sources = []
    for n, title in enumerate(copy.titles, start=1):
        path = _absolute(base, title.source)
        if not path.is_file():
            raise ArchiveError(f"title {n}: source {title.source} is missing")
        sources.append({"title": n, "name": path.name, "size": path.stat().st_size,
                        "fingerprint": fingerprint(path), "was": str(path)})  # fmt: skip
        title.source = place(path, "sources") if with_sources else path.name
    user = _user_files(project)
    manifest = {"made_by": f"DVD Studyo {__version__}", "made": datetime.now().isoformat(
        timespec="seconds"), "sources_included": with_sources, "sources": sources,
        "user": sorted(user)}  # fmt: skip
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".part")
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as z:
            z.writestr(PROJECT_NAME, dumps(copy))
            z.writestr("manifest.yaml", yaml.safe_dump(manifest, allow_unicode=True,
                                                       sort_keys=False))  # fmt: skip
            for name, path in {**entries, **user}.items():
                stored = path.suffix.lower() in VIDEO  # video does not shrink
                z.write(path, name, zipfile.ZIP_STORED if stored else zipfile.ZIP_DEFLATED)
        tmp.replace(out)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return out


def _user_files(project: Project) -> dict[str, Path]:
    """The user's own template, styles and profile the project names."""
    from dvd.menu.templates import TEMPLATES, template_folder
    from dvd.profiles import user_profile_dir
    from dvd.subs.styles import TEMPLATES as STYLES
    from dvd.subs.styles import style_folder

    out: dict[str, Path] = {}
    if project.menus is not None and project.menus.template not in TEMPLATES:
        path = template_folder() / f"{project.menus.template}.yaml"
        if path.is_file():
            out[f"user/templates/{path.name}"] = path
    for title in project.titles:
        for sub in title.subtitles:
            path = style_folder() / f"{sub.style}.yaml"
            if sub.style not in STYLES and path.is_file():
                out[f"user/styles/{path.name}"] = path
    if project.disc.profiles.user:
        path = user_profile_dir() / f"{project.disc.profiles.user}.yaml"
        if path.is_file():
            out[f"user/profiles/{path.name}"] = path
    return out


def restore(zip_path: Path, folder: Path, search: list[Path] | None = None) -> Restored:
    """Unpack into `folder` (a new project folder); install the user files that are not
    there yet; look for sources not in the archive in `search` folders (and the folder they
    came from) by fingerprint."""
    from dvd.menu.templates import template_folder
    from dvd.profiles import user_profile_dir
    from dvd.subs.styles import style_folder

    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as z:
        names = z.namelist()
        if PROJECT_NAME not in names or "manifest.yaml" not in names:
            raise ArchiveError(f"{Path(zip_path).name} is not a project archive")
        manifest = yaml.safe_load(z.read("manifest.yaml")) or {}
        homes = {"user/templates/": template_folder(), "user/styles/": style_folder(),
                 "user/profiles/": user_profile_dir()}  # fmt: skip
        done = Restored(folder / PROJECT_NAME)
        for name in names:
            if Path(name).is_absolute() or ".." in Path(name).parts:
                raise ArchiveError(f"unsafe name in the archive: {name}")
            home = next((h for prefix, h in homes.items() if name.startswith(prefix)), None)
            if home is not None:
                target = home / Path(name).name
                data = z.read(name)
                if not target.exists():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(data)
                    done.installed.append(name)
                elif target.read_bytes() != data:
                    done.kept.append(name)
                continue
            target = folder / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(name) as src, target.open("wb") as dst:
                shutil.copyfileobj(src, dst, CHUNK)
    project = load(done.project)
    by_title = {s["title"]: s for s in manifest.get("sources") or []}
    for n, title in enumerate(project.titles, start=1):
        if (folder / title.source).is_file():
            continue  # inside the archive
        info = by_title.get(n, {})
        where = [*(search or []), *([Path(info["was"]).parent] if info.get("was") else [])]
        found = find_source(info, where)
        if found is not None:
            title.source = str(found)
        else:
            done.missing.append(info.get("name") or title.source)
    save(project, done.project)
    return done


def find_source(info: dict, folders: list[Path]) -> Path | None:
    """A file in `folders` (not their subfolders) with the source's size and fingerprint."""
    size, mark = info.get("size"), info.get("fingerprint")
    if size is None or mark is None:
        return None
    for folder in folders:
        if not folder or not folder.is_dir():
            continue
        candidates = sorted(folder.iterdir(), key=lambda p: p.name != info.get("name"))
        for path in candidates:
            try:
                if path.is_file() and path.stat().st_size == size and fingerprint(path) == mark:
                    return path
            except OSError:
                continue
    return None
