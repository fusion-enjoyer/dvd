"""Phase 1 build: project file -> VIDEO_TS (no menus, no subtitles yet)."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path

from dvd.audio.ac3 import encode_ac3
from dvd.author.dvdauthor import AuthorTitle, author, mux, timecode
from dvd.budget.planner import Plan, plan
from dvd.probe import SourceInfo, probe
from dvd.project import load, source_path
from dvd.project.model import MAX_CHAPTERS, ChapterEvery, Project, Title, parse_timecode
from dvd.video.hcenc import EncodeSettings, encode
from dvd.video.pipeline import Target, build_clip, plan_target

Progress = Callable[[str, float], None]


class BuildError(Exception):
    pass


@dataclass
class BuildResult:
    video_ts: Path
    plan: Plan
    warnings: list[str] = field(default_factory=list)


@dataclass
class _Prepared:
    title: Title
    source: Path
    info: SourceInfo
    target: Target
    frames: int

    @property
    def duration(self) -> float:
        return self.frames / float(self.target.fps)


def safe_name(name: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")
    return cleaned or "disc"


def chapter_frames(title: Title, info: SourceInfo, target: Target, frames: int) -> list[int]:
    """Frame numbers where chapters start. PAL speedup and pulldown keep frame numbers."""
    src_fps = info.main_video.fps
    chapters = title.chapters
    if chapters == "none":
        starts = [0]
    elif chapters == "from-source":
        starts = [round(c.start * src_fps) for c in info.chapters]
    elif isinstance(chapters, ChapterEvery):
        step = max(1, round(chapters.every * 60 * target.fps))
        starts = list(range(0, frames, step))
    else:
        starts = [round(parse_timecode(t) * src_fps) for t in chapters]
    return sorted({0, *(f for f in starts if 0 <= f < frames)})[:MAX_CHAPTERS]


def _prepare(project: Project, project_file: Path) -> list[_Prepared]:
    prepared = []
    for title in project.titles:
        source = source_path(project_file, title)
        info = probe(source)
        if info.main_video is None:
            raise BuildError(f"{source.name} has no video track")
        target = plan_target(info.main_video, project.disc.standard, title.video)
        # Frame count from the decoder is exact; container duration is not.
        frames = build_clip(source, info.main_video, target, title.video).num_frames
        prepared.append(_Prepared(title, source, info, target, frames))
    return prepared


def build(
    project_file: Path,
    out_dir: Path | None = None,
    work_dir: Path | None = None,
    progress: Progress | None = None,
) -> BuildResult:
    project_file = Path(project_file).resolve()
    project = load(project_file)
    name = safe_name(project.disc.name)
    out_dir = out_dir or project_file.parent / name
    work_dir = work_dir or project_file.parent / "build" / name
    work_dir.mkdir(parents=True, exist_ok=True)

    def report(stage: str, fraction: float) -> None:
        if progress:
            progress(stage, fraction)

    warnings = []
    if any(t.subtitles for t in project.titles):
        warnings.append("subtitles are not burned to the disc yet; they will be in a later step")
    if any(t.video.crop == "auto" for t in project.titles):
        warnings.append("automatic black-bar crop comes in Phase 2; bars are encoded as picture")

    prepared = _prepare(project, project_file)
    total = sum(p.duration for p in prepared)
    audio_avg = sum(p.duration * sum(a.bitrate for a in p.title.audio) for p in prepared) / total
    budget = plan(
        project.disc.media,
        total,
        [round(audio_avg)],
        viewing=project.disc.profiles.viewing,
    )
    warnings += budget.warnings
    if not budget.fits or budget.video_kbps <= 0:
        raise BuildError(f"the titles do not fit on {project.disc.media.upper()}")

    author_titles = []
    for n, p in enumerate(prepared, start=1):
        tag = f"t{n:02}"
        # DVD has no default-track flag; players start with the first stream unless their
        # language setting says otherwise, so the default track goes first.
        tracks = sorted(p.title.audio, key=lambda a: not a.default)
        audio_files = []
        for i, a in enumerate(tracks):
            report(f"title {n} audio {i + 1}", 0.0)
            audio_files.append(
                encode_ac3(
                    p.source,
                    a.track,
                    work_dir / f"{tag}_a{i}.ac3",
                    a.channels,
                    a.bitrate,
                    p.target.speedup,
                )  # fmt: skip
            )
        chapters = chapter_frames(p.title, p.info, p.target, p.frames)
        settings = EncodeSettings(
            bitrate=budget.video_kbps,
            maxrate=budget.peak_kbps,
            aspect=p.target.aspect,
            standard=project.disc.standard,
            pulldown=p.target.pulldown,
            chapters=chapters,
        )
        clip = build_clip(p.source, p.info.main_video, p.target, p.title.video)
        m2v = encode(
            clip,
            work_dir / f"{tag}.m2v",
            settings,
            work_dir / f"{tag}_hcenc",
            progress=lambda f, n=n: report(f"title {n} video", f),
        )
        report(f"title {n} mux", 0.0)
        mux(m2v, audio_files, work_dir / f"{tag}.mpg")
        author_titles.append(
            AuthorTitle(
                vob=f"{tag}.mpg",
                aspect=p.target.aspect,
                audio_langs=[a.lang for a in tracks],
                chapters=[timecode(f / Fraction(p.target.fps)) for f in chapters],
            )
        )
    report("authoring", 0.0)
    video_ts = author(author_titles, project.disc.standard, work_dir, out_dir)
    report("done", 1.0)
    return BuildResult(video_ts, budget, warnings)
