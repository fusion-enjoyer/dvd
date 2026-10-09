"""Track edits shared by the UI and tests: include/exclude, default, external subtitle files."""

from __future__ import annotations

import os
import re
from pathlib import Path

from dvd.lang import to_dvd_code
from dvd.probe import AudioTrack, SourceInfo
from dvd.project.model import MAX_AUDIO_TRACKS, MAX_SUBTITLE_TRACKS, Audio, Subtitle, Title

_LANG_WORDS = {
    "turkce": "tr", "türkçe": "tr", "turkish": "tr", "english": "en", "ingilizce": "en",
    "german": "de", "almanca": "de", "french": "fr", "fransizca": "fr", "fransızca": "fr",
}  # fmt: skip


def audio_from_source(track: AudioTrack, layout: str = "5.1", bitrate: int = 448) -> Audio:
    """A disc track for a source track; `layout`/`bitrate` come from the audio profile and
    only apply to surround sources (stereo and mono stay 2.0 at 192k)."""
    surround = track.channels >= 6 and layout == "5.1"
    return Audio(
        track=track.index,
        lang=to_dvd_code(track.language) or "en",
        channels="5.1" if surround else "2.0",
        bitrate=bitrate if surround else 192,
    )


def apply_audio_profile(title: Title, info: SourceInfo, settings) -> None:
    """Re-shape the chosen tracks for an audio profile: layout, bit rate and the optional
    stereo copy of the main track. Track choice, languages and the default are kept."""
    by_index = {a.index: a for a in info.audio}
    seen, shaped = set(), []
    for a in title.audio:
        if a.track in seen or a.track not in by_index:
            continue  # drop earlier stereo copies; they are re-added below if wanted
        seen.add(a.track)
        new = audio_from_source(by_index[a.track], settings["audio_channels"],
                                settings["audio_bitrate"])  # fmt: skip
        new.lang, new.default = a.lang, a.default
        shaped.append(new)
    main = next((a for a in shaped if a.default), shaped[0] if shaped else None)
    wants_copy = settings["audio_extra_stereo"] and main is not None and main.channels == "5.1"
    if wants_copy and len(shaped) < MAX_AUDIO_TRACKS:
        copy = Audio(track=main.track, lang=main.lang, channels="2.0", bitrate=192)
        shaped.insert(shaped.index(main) + 1, copy)
    title.audio = shaped


def _ensure_one_default(items: list) -> None:
    if items and not any(i.default for i in items):
        items[0].default = True


def set_audio_included(title: Title, info: SourceInfo, index: int, included: bool) -> None:
    current = [a for a in title.audio if a.track != index]
    if included:
        if len(current) >= MAX_AUDIO_TRACKS:
            raise ValueError(f"a DVD title holds at most {MAX_AUDIO_TRACKS} audio tracks")
        source = next(a for a in info.audio if a.index == index)
        current.append(audio_from_source(source))
        order = {a.index: n for n, a in enumerate(info.audio)}
        current.sort(key=lambda a: order.get(a.track, 99))
    _ensure_one_default(current)
    title.audio = current


def set_default_audio(title: Title, index: int) -> None:
    for a in title.audio:
        a.default = a.track == index


def set_subtitle_included(title: Title, index: int, lang: str | None, included: bool) -> None:
    current = [s for s in title.subtitles if s.track != index]
    if included:
        if len(current) >= MAX_SUBTITLE_TRACKS:
            raise ValueError(f"a DVD title holds at most {MAX_SUBTITLE_TRACKS} subtitle tracks")
        current.append(Subtitle(track=index, lang=to_dvd_code(lang) or "tr"))
    title.subtitles = current


def set_default_subtitle(title: Title, key: int | str | None) -> None:
    """`key` is a stream index, a file path as stored, or None for subtitles off."""
    for s in title.subtitles:
        s.default = key is not None and (s.track == key or s.file == key)


def guess_language(path: Path) -> str:
    name = path.stem.lower()
    for word, code in _LANG_WORDS.items():
        if word in name:
            return code
    for token in reversed(re.split(r"[._\- ]+", name)):
        code = to_dvd_code(token) if len(token) in (2, 3) else None
        if code:
            return code
    return "tr"


def add_subtitle_file(title: Title, path: Path, project_dir: Path) -> Subtitle:
    if len(title.subtitles) >= MAX_SUBTITLE_TRACKS:
        raise ValueError(f"a DVD title holds at most {MAX_SUBTITLE_TRACKS} subtitle tracks")
    try:
        stored = Path(os.path.relpath(path.resolve(), project_dir.resolve()))
        stored_text = stored.as_posix() if not str(stored).startswith("..") else path.as_posix()
    except ValueError:  # another drive
        stored_text = path.resolve().as_posix()
    sub = Subtitle(file=stored_text, lang=guess_language(path))
    title.subtitles = [*title.subtitles, sub]
    return sub


def remove_subtitle_file(title: Title, stored: str) -> None:
    title.subtitles = [s for s in title.subtitles if s.file != stored]
