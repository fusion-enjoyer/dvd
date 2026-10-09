"""TV series: a season folder becomes a set of discs.

Episodes are found by their file names (S01E02, 1x02, "Bölüm 3", "Episode 3"), kept in order,
and shared out over as few discs as reach the quality target; the split keeps the discs
about equally long, so no disc is left with a single episode at a much higher bit rate.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from dvd.budget.planner import plan

VIDEO_SUFFIXES = {".mkv", ".mp4", ".m4v", ".mov", ".avi", ".ts", ".m2ts", ".webm", ".mpg"}
# Average video bit rate a disc set aims for (kbit/s).
QUALITY = {"standart": 4_000, "iyi": 5_000, "yuksek": 6_000}
MAX_TITLES_PER_DISC = 99

_PATTERNS = (
    re.compile(r"[Ss](\d{1,2})[ ._-]?[Ee](\d{1,3})"),  # S01E02, s1e2, S01.E02
    re.compile(r"\b(\d{1,2})[xX](\d{1,3})\b"),  # 1x02
    re.compile(r"(?:Sezon|Season)\s*(\d{1,2}).*?(?:B[öo]l[üu]m|Episode|Ep)\s*(\d{1,3})", re.I),
)
_EPISODE_ONLY = re.compile(r"(?:B[öo]l[üu]m|Episode|Ep)[ ._-]*(\d{1,3})", re.I)


@dataclass(frozen=True)
class Episode:
    path: Path
    season: int | None
    number: int
    duration: float = 0.0  # seconds, filled in by probing

    @property
    def code(self) -> str:
        return f"S{self.season or 1:02}E{self.number:02}"


def parse_episode(name: str) -> tuple[int | None, int] | None:
    """(season, episode) from a file name, or None when it carries no episode number."""
    for pattern in _PATTERNS:
        m = pattern.search(name)
        if m:
            return int(m.group(1)), int(m.group(2))
    m = _EPISODE_ONLY.search(name)
    return (None, int(m.group(1))) if m else None


def scan_folder(folder: Path) -> list[Episode]:
    """Episode files in a folder, in season/episode order; files without a number are left
    out. Two files with the same number are an error (a duplicate or a sample clip)."""
    found: dict[tuple[int, int], Episode] = {}
    for path in sorted(folder.iterdir()):
        if path.suffix.lower() not in VIDEO_SUFFIXES or "sample" in path.stem.lower():
            continue
        parsed = parse_episode(path.stem)
        if parsed is None:
            continue
        season, number = parsed
        key = (season or 0, number)
        episode = Episode(path, season, number)
        if key in found:
            raise ValueError(f"{found[key].path.name} and {path.name} are both {episode.code}")
        found[key] = episode
    return [found[k] for k in sorted(found)]


@dataclass(frozen=True)
class DiscSet:
    media: str
    discs: list[list[Episode]]
    video_kbps: list[int]  # average video bit rate each disc gets

    @property
    def count(self) -> int:
        return len(self.discs)


def _video_kbps(media: str, episodes: list[Episode], audio_kbps: list[int], subs: int) -> int:
    seconds = sum(e.duration for e in episodes)
    return plan(media, seconds, audio_kbps, subs).video_kbps if seconds > 0 else 0


def _split(durations: list[float], parts: int) -> list[int]:
    """Cut points that split the list into `parts` runs with the longest run as short as
    possible (episodes stay in order)."""
    n = len(durations)
    prefix = [0.0]
    for d in durations:
        prefix.append(prefix[-1] + d)
    # best[k][i]: smallest longest-run for the first i episodes in k runs.
    inf = float("inf")
    best = [[inf] * (n + 1) for _ in range(parts + 1)]
    cut = [[0] * (n + 1) for _ in range(parts + 1)]
    best[0][0] = 0.0
    for k in range(1, parts + 1):
        for i in range(1, n + 1):
            for j in range(k - 1, i):
                cost = max(best[k - 1][j], prefix[i] - prefix[j])
                if cost < best[k][i]:
                    best[k][i], cut[k][i] = cost, j
    points, i = [], n
    for k in range(parts, 0, -1):
        points.append(i)
        i = cut[k][i]
    return sorted(points)


def plan_set(
    episodes: list[Episode],
    media: str = "dvd9",
    quality: str = "iyi",
    audio_kbps: list[int] | None = None,
    subtitle_tracks: int = 0,
) -> DiscSet:
    """The fewest discs on which every disc reaches the quality target, episodes balanced."""
    if not episodes:
        raise ValueError("no episodes")
    audio_kbps = audio_kbps or [448]
    target = QUALITY[quality]
    durations = [e.duration for e in episodes]
    for count in range(1, len(episodes) + 1):
        ends = _split(durations, count)
        starts = [0, *ends[:-1]]
        discs = [episodes[a:b] for a, b in zip(starts, ends, strict=True)]
        if any(len(d) > MAX_TITLES_PER_DISC for d in discs):
            continue
        rates = [_video_kbps(media, d, audio_kbps, subtitle_tracks) for d in discs]
        if min(rates) >= target:
            return DiscSet(media, discs, rates)
    # Even one episode per disc misses the target: say so through the rates.
    discs = [[e] for e in episodes]
    return DiscSet(
        media, discs, [_video_kbps(media, d, audio_kbps, subtitle_tracks) for d in discs]
    )


def name_from_folder(folder: Path) -> tuple[str, int | None]:
    """Series name and season from a folder name: 'Dizi S01', 'Dizi Sezon 2', 'Dizi Season 3'."""
    text = re.sub(r"[._]+", " ", folder.name)
    m = re.search(r"\b(?:S|Sezon\s*|Season\s*)(\d{1,2})\b", text, re.I)
    if m is None:
        return text.strip(), None
    return text[: m.start()].strip(" -") or text.strip(), int(m.group(1))


@dataclass
class SeriesInfo:
    """What TMDB knows about the season: names and pictures for the discs' menus."""

    name: str
    episode_names: dict[int, str]
    backdrop: Path | None = None
    logo: Path | None = None


def from_tmdb(client, name: str, season: int) -> SeriesInfo | None:
    """The best TMDB match for the series, its season's episode names, and a backdrop and
    logo (downloaded to the cache). None when TMDB does not know the series."""
    matches = client.search_tv(name)
    if not matches:
        return None
    show = client.show(matches[0].id)
    key = f"tv-{show.id}"
    backdrop = client.image(key, show.backdrops[0], "w1280") if show.backdrops else None
    logo = client.image(key, show.logos[0], "w500") if show.logos else None
    return SeriesInfo(show.title, client.season(show.id, season), backdrop, logo)
