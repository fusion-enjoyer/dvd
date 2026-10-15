"""A season folder becomes one project file per disc (used by `dvd series` and the GUI)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

from dvd import series
from dvd.probe import SourceInfo, probe
from dvd.project.create import new_project, new_series_project
from dvd.project.model import PROJECT_SUFFIX, MenuBackground, MenuPage, Project, SeriesDisc
from dvd.series import DiscSet, Episode, SeriesInfo


@dataclass
class Season:
    folder: Path
    episodes: list[Episode]  # with durations
    infos: list[SourceInfo]  # same order as the episodes
    name: str  # guessed from the folder name
    number: int


def read_season(folder: Path, progress: Callable[[int, int], None] | None = None) -> Season:
    """Find and probe the episodes. ValueError when there are none or two share a number."""
    episodes = series.scan_folder(folder)
    if not episodes:
        raise ValueError(f"no episode files (S01E02, 1x02, ...) in {folder}")
    infos = []
    for n, episode in enumerate(episodes):
        if progress:
            progress(n, len(episodes))
        infos.append(probe(episode.path))
    episodes = [replace(e, duration=i.duration or 0) for e, i in zip(episodes, infos, strict=True)]
    name, number = series.name_from_folder(folder.resolve())
    return Season(folder, episodes, infos, name, number or episodes[0].season or 1)


def plan_season(season: Season, media: str = "dvd9", quality: str = "iyi") -> DiscSet:
    """Share the episodes out over discs, with the first episode's tracks as the budget."""
    sample = new_project(season.infos[0], season.folder).titles[0]
    return series.plan_set(season.episodes, media, quality, [a.bitrate for a in sample.audio],
                           len(sample.subtitles))  # fmt: skip


def lookup(season: Season, client) -> SeriesInfo | None:
    """TMDB's names and pictures for the season (TmdbError when TMDB cannot be reached)."""
    return series.from_tmdb(client, season.name, season.number)


def series_name(season: Season, meta: SeriesInfo | None) -> str:
    return f"{meta.name} {season.number}. Sezon" if meta else season.folder.resolve().name


def disc_projects(
    season: Season, plan: DiscSet, name: str = "", meta: SeriesInfo | None = None
) -> list[tuple[Path, Project]]:
    """One project per disc, named "<name> - Disk n" (just the name for a single disc), with
    the series menu: main page, episode pages, languages. Files are not written."""
    name = name or series_name(season, meta)
    by_path = {i.path: i for i in season.infos}
    out = []
    for n, disc in enumerate(plan.discs, start=1):
        label = f"{name} - Disk {n}" if plan.count > 1 else name
        project = new_series_project([by_path[e.path] for e in disc], season.folder, label)
        project.disc.media = plan.media
        project.series = SeriesDisc(name=name[:64], disc=n, discs=plan.count)
        for title, episode in zip(project.titles, disc, strict=True):
            known = meta.episode_names.get(episode.number) if meta else None
            title.name = (f"{episode.number}. {known}" if known else
                          f"{episode.number}. bölüm")[:80]  # fmt: skip
        if project.menus is not None:
            update: dict = {"template": "dizi", "pages": [
                MenuPage(id="main", kind="main"), MenuPage(id="episodes", kind="episodes"),
                MenuPage(id="languages", kind="languages")]}  # fmt: skip
            if meta is not None:
                if meta.backdrop is not None:
                    update["background"] = MenuBackground(image=meta.backdrop.as_posix())
                update["logo"] = meta.logo.as_posix() if meta.logo else None
            project.menus = project.menus.model_copy(update=update)
        out.append((season.folder / f"{label}{PROJECT_SUFFIX}", project))
    return out
