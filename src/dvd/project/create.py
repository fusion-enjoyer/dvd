"""A starting project for a source file, with defaults picked from what the source contains."""

from __future__ import annotations

import os
from fractions import Fraction
from pathlib import Path

from dvd.lang import to_dvd_code
from dvd.probe import SourceInfo
from dvd.project.model import (
    MAX_AUDIO_TRACKS,
    Audio,
    Disc,
    MenuBackground,
    Menus,
    Profiles,
    Project,
    Subtitle,
    Title,
)

DVD9_FROM_MINUTES = 100  # K6: long films go on DVD-9


def suggest_standard(fps: Fraction | None) -> tuple[str, str]:
    """PAL or NTSC for a source frame rate, with the reason shown to the user."""
    if fps is None:
        return "pal", "frame rate unknown"
    rate = float(fps)
    if abs(rate - 25) < 0.01 or abs(rate - 50) < 0.01:
        return "pal", f"{rate:g} fps is native PAL"
    if any(abs(rate - r) < 0.01 for r in (29.97, 30, 59.94, 60)):
        return "ntsc", f"{rate:g} fps is native NTSC"
    if abs(rate - 23.976) < 0.01 or abs(rate - 24) < 0.01:
        # PAL gives 576 lines instead of 480 and plays on PAL-region TVs; the film runs 4% faster.
        return "pal", "film rate: PAL speedup, 576 lines"
    return "pal", f"{rate:g} fps has no exact DVD match"


def _relative_source(source: Path, project_dir: Path) -> str:
    try:
        rel = os.path.relpath(source.resolve(), project_dir.resolve())
    except ValueError:  # different drive on Windows
        return source.resolve().as_posix()
    return Path(rel).as_posix() if not rel.startswith("..") else source.resolve().as_posix()


def _audio_tracks(info: SourceInfo) -> list[Audio]:
    from dvd.project.edit import audio_from_source

    tracks = [audio_from_source(a) for a in info.audio[:MAX_AUDIO_TRACKS]]
    if tracks:
        flagged = next((i for i, a in enumerate(info.audio[:MAX_AUDIO_TRACKS]) if a.default), 0)
        tracks[flagged].default = True
    return tracks


def _subtitle_tracks(info: SourceInfo) -> list[Subtitle]:
    return [
        Subtitle(track=s.index, lang=to_dvd_code(s.language) or "tr", forced=s.forced)
        for s in info.subtitles
        if s.usable
    ][:32]


def default_menus(info: SourceInfo) -> Menus:
    """Menus for a new project: the standard pages over a film frame a quarter in."""
    from dvd.project.edit import format_time

    at = (info.duration or 0) * 0.25
    frame = format_time(at) if info.main_video is not None and at > 0 else None
    return Menus(background=MenuBackground(frame=frame))


def new_project(info: SourceInfo, project_dir: Path) -> Project:
    video = info.main_video
    standard, _ = suggest_standard(video.playback_fps if video else None)
    long_film = (info.duration or 0) / 60 >= DVD9_FROM_MINUTES
    audio, subtitles = _audio_tracks(info), _subtitle_tracks(info)
    # A Turkish viewer of a film whose main audio is not Turkish wants Turkish subtitles on.
    main_lang = next((a.lang for a in audio if a.default), None)
    turkish = next((s for s in subtitles if s.lang == "tr" and not s.forced), None)
    if main_lang != "tr" and turkish is not None:
        turkish.default = True
    return Project(
        disc=Disc(
            name=info.title or info.path.stem,
            standard=standard,
            media="dvd9" if long_film else "dvd5",
            # Portrait video is almost always from a phone: blurred side bars, phone settings.
            profiles=Profiles(content="telefon") if video and video.portrait else Profiles(),
        ),
        titles=[
            Title(
                source=_relative_source(info.path, project_dir),
                audio=audio,
                subtitles=subtitles,
                chapters="from-source" if info.chapters else "none",
            )
        ],
        menus=default_menus(info),
    )


def new_series_project(infos: list[SourceInfo], project_dir: Path, name: str) -> Project:
    """One disc of a series: a title per episode. Tracks follow the first episode; the others
    get theirs matched by language, because every title on a DVD titleset shares one track
    layout. An episode missing a language is an error rather than a silent swap."""
    if not infos:
        raise ValueError("no episodes for this disc")
    first = new_project(infos[0], project_dir)
    titles = [first.titles[0]]
    for info in infos[1:]:
        title = new_project(info, project_dir).titles[0]
        title.audio = _match(first.titles[0].audio, info.audio, info.path.name, "audio")
        title.subtitles = _match(first.titles[0].subtitles,
                                 [s for s in info.subtitles if s.usable], info.path.name,
                                 "subtitle")  # fmt: skip
        title.chapters = first.titles[0].chapters if info.chapters else "none"
        titles.append(title)
    first.disc.name = name[:64]
    first.titles = titles
    return first


def _match(wanted: list, tracks: list, file: str, kind: str) -> list:
    """Copies of `wanted` (audio or subtitle entries) pointing at the same-language streams
    of another file, in the same order."""
    out, used = [], set()
    for w in wanted:
        hit = next((t for t in tracks if t.index not in used
                    and (to_dvd_code(t.language) or w.lang) == w.lang), None)  # fmt: skip
        if hit is None:
            raise ValueError(f"{file} has no {kind} track in {w.lang!r} like the first episode")
        used.add(hit.index)
        if kind == "audio" or w.track is not None:
            out.append(w.model_copy(update={"track": hit.index}))
    return out
