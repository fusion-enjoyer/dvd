"""Checks that need the source files: do they exist, do the referenced tracks exist."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from dvd.probe import ProbeError, SourceInfo, probe
from dvd.project.io import source_path
from dvd.project.model import Project


def check_sources(
    project: Project,
    project_file: Path,
    prober: Callable[[Path], SourceInfo] = probe,
) -> list[str]:
    problems = []
    for t, title in enumerate(project.titles):
        where = f"titles[{t}]"
        path = source_path(project_file, title)
        if not path.is_file():
            problems.append(f"{where}.source: file not found: {path}")
            continue
        try:
            info = prober(path)
        except ProbeError as exc:
            problems.append(f"{where}.source: {exc}")
            continue
        if info.main_video is None:
            problems.append(f"{where}.source: no video track in {path.name}")
        audio = {a.index for a in info.audio}
        for i, a in enumerate(title.audio):
            if a.track not in audio:
                problems.append(
                    f"{where}.audio[{i}].track: stream {a.track} is not an audio track "
                    f"(audio tracks: {sorted(audio) or 'none'})"
                )
        subs = {s.index for s in info.subtitles}
        for i, s in enumerate(title.subtitles):
            if s.track is not None and s.track not in subs:
                problems.append(
                    f"{where}.subtitles[{i}].track: stream {s.track} is not a subtitle track "
                    f"(subtitle tracks: {sorted(subs) or 'none'})"
                )
            if s.file is not None:
                sub_path = Path(s.file)
                if not sub_path.is_absolute():
                    sub_path = project_file.parent / sub_path
                if not sub_path.is_file():
                    problems.append(f"{where}.subtitles[{i}].file: file not found: {sub_path}")
        if title.chapters == "from-source" and not info.chapters:
            problems.append(f"{where}.chapters: the source has no chapters")
    return problems
