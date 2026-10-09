"""TMDB (The Movie Database): match a film, read its Turkish title and overview, and fetch
backdrops, logos and posters for the menus.

The API key is the user's own (themoviedb.org account, free); it is kept in the user settings,
never in a project file. Requests go only to api.themoviedb.org and image.tmdb.org. Images are
cached under %LOCALAPPDATA%\\DVD Studyo\\tmdb\\<id>\\ (DVD_CACHE_DIR overrides it), so a build
works offline once they are chosen.
"""

from __future__ import annotations

import json
import os
import re
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

API = "https://api.themoviedb.org/3"
IMAGES = "https://image.tmdb.org/t/p"
Fetch = Callable[[str], bytes]


class TmdbError(Exception):
    pass


@dataclass(frozen=True)
class Match:
    id: int
    title: str
    original_title: str
    year: int | None
    overview: str


@dataclass
class Film:
    id: int
    title: str  # Turkish title when TMDB has one
    original_title: str
    year: int | None
    overview: str
    backdrops: list[str] = field(default_factory=list)  # image paths on TMDB, best first
    logos: list[str] = field(default_factory=list)
    posters: list[str] = field(default_factory=list)


def _http(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"Accept": "application/json",
                                                   "User-Agent": "DVD-Studyo"})  # fmt: skip
    with urllib.request.urlopen(request, timeout=20) as response:  # noqa: S310 (fixed hosts)
        return response.read()


def guess_title(path: Path) -> tuple[str, int | None]:
    """Film name and year from a file name: 'Interstellar (2014).mkv',
    'Interstellar.2014.1080p.BluRay.x264.mkv', 'Yol_1982.mkv'."""
    stem = re.sub(r"[._]+", " ", path.stem)
    m = re.search(r"[\[(]?\b(19[2-9]\d|20[0-4]\d)\b[\])]?", stem)
    if m:
        name, year = stem[: m.start()], int(m.group(1))
    else:
        name, year = re.split(r"\b(?:\d{3,4}p|bluray|web|remux|x26[45]|hevc)\b", stem,
                              flags=re.IGNORECASE)[0], None  # fmt: skip
    return re.sub(r"\s+", " ", name).strip(" -[]()") or path.stem, year


class Client:
    def __init__(self, key: str, fetch: Fetch = _http, language: str = "tr-TR") -> None:
        if not key:
            raise TmdbError("a TMDB API key is needed (themoviedb.org, account settings)")
        self.key, self.fetch, self.language = key.strip(), fetch, language

    def _get(self, path: str, **params) -> dict:
        query = {"api_key": self.key, "language": self.language, **params}
        url = f"{API}{path}?{urllib.parse.urlencode(query)}"
        try:
            return json.loads(self.fetch(url))
        except (OSError, ValueError) as exc:
            raise TmdbError(f"TMDB request failed: {exc}") from None

    def search(self, title: str, year: int | None = None) -> list[Match]:
        params = {"query": title, "include_adult": "false"}
        if year:
            params["year"] = str(year)
        results = self._get("/search/movie", **params).get("results") or []
        if not results and year:  # release years differ between countries
            results = self._get("/search/movie", query=title).get("results") or []
        return [Match(r["id"], r.get("title") or r.get("original_title", ""),
                      r.get("original_title", ""), _year(r.get("release_date")),
                      r.get("overview") or "") for r in results]  # fmt: skip

    def film(self, film_id: int) -> Film:
        return self._details("movie", film_id)

    def search_tv(self, name: str, year: int | None = None) -> list[Match]:
        params = {"query": name, "include_adult": "false"}
        if year:
            params["first_air_date_year"] = str(year)
        results = self._get("/search/tv", **params).get("results") or []
        if not results and year:
            results = self._get("/search/tv", query=name).get("results") or []
        return [Match(r["id"], r.get("name") or r.get("original_name", ""),
                      r.get("original_name", ""), _year(r.get("first_air_date")),
                      r.get("overview") or "") for r in results]  # fmt: skip

    def show(self, tv_id: int) -> Film:
        """A TV series with its pictures (title = the series name)."""
        return self._details("tv", tv_id)

    def season(self, tv_id: int, number: int) -> dict[int, str]:
        """Episode number -> episode name (Turkish when TMDB has it; empty names left out)."""
        d = self._get(f"/tv/{tv_id}/season/{number}")
        return {e["episode_number"]: e["name"].strip() for e in d.get("episodes") or []
                if e.get("name") and "episode_number" in e}  # fmt: skip

    def _details(self, kind: str, item_id: int) -> Film:
        d = self._get(f"/{kind}/{item_id}", append_to_response="images",
                      include_image_language="tr,en,null")  # fmt: skip
        images = d.get("images") or {}

        def paths(kind: str, prefer: tuple[str | None, ...]) -> list[str]:
            items = images.get(kind) or []
            rank = {lang: i for i, lang in enumerate(prefer)}
            items = sorted(items, key=lambda i: (rank.get(i.get("iso_639_1"), len(rank)),
                                                 -(i.get("vote_average") or 0)))  # fmt: skip
            return [i["file_path"] for i in items if i.get("file_path")]

        title = d.get("title") or d.get("name") or d.get("original_title") or d.get("original_name")
        original = d.get("original_title") or d.get("original_name") or ""
        return Film(
            d["id"], title or "", original,
            _year(d.get("release_date") or d.get("first_air_date")), d.get("overview") or "",
            # Backdrops without text suit a menu best; logos and posters in Turkish first.
            backdrops=paths("backdrops", (None, "tr", "en")),
            logos=paths("logos", ("tr", "en", None)),
            posters=paths("posters", ("tr", "en", None)),
        )  # fmt: skip

    def image(self, film_id: int | str, path: str, size: str = "original") -> Path:
        """Download one image into the cache (once) and return the local file. `film_id`
        names the cache folder: the film's id, or "tv-<id>" for a series."""
        if not re.fullmatch(r"/[\w-]+\.(?:jpg|png|svg)", path):
            raise TmdbError(f"unexpected TMDB image path {path!r}")
        local = cache_folder() / str(film_id) / f"{size}{path.replace('/', '_')}"
        if not local.is_file():
            local.parent.mkdir(parents=True, exist_ok=True)
            try:
                data = self.fetch(f"{IMAGES}/{size}{path}")
            except OSError as exc:
                raise TmdbError(f"image download failed: {exc}") from None
            local.write_bytes(data)
        return local


def _year(date: str | None) -> int | None:
    return int(date[:4]) if date and date[:4].isdigit() else None


def cache_folder() -> Path:
    if env := os.environ.get("DVD_CACHE_DIR"):
        return Path(env) / "tmdb"
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".cache")
    return base / "DVD Studyo" / "tmdb"
