"""Phase 1 build: project file -> VIDEO_TS (no menus, no subtitles yet)."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path

import vapoursynth as vs

from dvd.audio.ac3 import can_copy, encode_ac3
from dvd.author.dvdauthor import AuthorTitle, author, mux, timecode
from dvd.author.pscheck import check as check_mux
from dvd.budget.planner import Plan, plan
from dvd.output.iso import write_iso
from dvd.probe import SourceInfo, probe
from dvd.profiles import resolve as resolve_profiles
from dvd.project import load, source_path
from dvd.project.edit import disc_audio, disc_subtitles
from dvd.project.model import (
    MAX_CHAPTERS,
    ChapterEvery,
    Project,
    Subtitle,
    Title,
    Video,
    parse_timecode,
)
from dvd.subs.extract import extract_text_track
from dvd.subs.pgs import BitmapCue, extract_pgs
from dvd.subs.render import Placement
from dvd.subs.spumux import add_subtitle_stream
from dvd.subs.srt import Cue, read_srt, retime
from dvd.subs.styles import StyleError, for_viewing, load_style
from dvd.video import encoders
from dvd.video.compliance import check as check_video
from dvd.video.crop import detect_crop
from dvd.video.hcenc import EncodeSettings
from dvd.video.pipeline import (
    Target,
    UnsupportedSource,
    build_clip,
    check_supported,
    plan_target,
)
from dvd.video.preprocess import resolve as resolve_preprocess

Progress = Callable[[str, float], None]


class BuildError(Exception):
    pass


@dataclass
class BuildResult:
    video_ts: Path
    plan: Plan
    warnings: list[str] = field(default_factory=list)
    iso: Path | None = None


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
    """Frame numbers where chapters start. Source times are moved to the disc's clock (PAL
    speedup, 30 -> 29.97) and counted in disc frames (two source frames per interlaced one)."""
    chapters = title.chapters

    def frame(seconds: float) -> int:
        return round(Fraction(seconds) / target.speedup * target.fps)

    if chapters == "none":
        starts = [0]
    elif chapters == "from-source":
        starts = [frame(c.start) for c in info.chapters]
    elif isinstance(chapters, ChapterEvery):
        step = max(1, round(chapters.every * 60 * target.fps))
        starts = list(range(0, frames, step))
    else:
        starts = [frame(parse_timecode(t)) for t in chapters]
    return sorted({0, *(f for f in starts if 0 <= f < frames)})[:MAX_CHAPTERS]


def placement(target: Target) -> Placement:
    c = target.crop
    return Placement((c.left, c.right, c.top, c.bottom), (target.active_width,
                     target.active_height), (target.pad_left, target.pad_top),
                     (target.width, target.height))  # fmt: skip


def _subtitle_cues(
    sub: Subtitle, p: _Prepared, project_file: Path, srt_out: Path
) -> list[Cue | BitmapCue]:
    if sub.file is not None:
        path = Path(sub.file)
        path = path if path.is_absolute() else project_file.parent / path
        if path.suffix.lower() == ".srt":
            return read_srt(path)
        return read_srt(extract_text_track(path, 0, srt_out))  # ASS, SSA, WebVTT: text only
    track = next((s for s in p.info.subtitles if s.index == sub.track), None)
    if track is None:
        raise BuildError(f"{p.source.name} has no subtitle stream {sub.track}")
    if track.codec == "hdmv_pgs_subtitle":
        cues = extract_pgs(p.source, sub.track, srt_out.with_suffix(".sup"))
        if not cues:
            raise BuildError(f"PGS stream {sub.track} has no captions")
        return cues
    if track.kind != "text":
        raise BuildError(f"subtitle stream {sub.track} is {track.codec}, which is not supported")
    return read_srt(extract_text_track(p.source, sub.track, srt_out))


def estimate(project: Project, infos: list[SourceInfo]) -> Plan:
    """Bitrate plan from container durations, without decoding: for the live budget bar."""
    total = audio = 0.0
    for title, info in zip(project.titles, infos, strict=True):
        speedup = 1.0
        if info.main_video is not None:
            try:
                target = plan_target(info.main_video, project.disc.standard, title.video)
                speedup = float(target.speedup)
            except UnsupportedSource:
                pass
        duration = (info.duration or 0) / speedup
        total += duration
        audio += duration * sum(a.bitrate for a in title.audio)
    return plan(
        project.disc.media,
        max(total, 1.0),
        [round(audio / total) if total else 0],
        subtitle_tracks=max(len(t.subtitles) for t in project.titles),
        peak_kbps=resolve_profiles(project.disc.profiles)["peak_kbps"],
    )


def prepare_title(
    project: Project, project_file: Path, n: int, warnings: list[str] | None = None
) -> _Prepared:
    """Probe title `n` (1-based), detect its bars and plan its DVD frame."""
    title = project.titles[n - 1]
    source = source_path(project_file, title)
    info = probe(source)
    if info.main_video is None:
        raise BuildError(f"{source.name} has no video track")
    detected = None
    if title.video.crop == "auto":
        check_supported(info.main_video)
        detected = detect_crop(source, info.main_video)
        if detected is None and warnings is not None:
            warnings.append(f"title {n}: black bars could not be detected; full frame used")
    target = plan_target(info.main_video, project.disc.standard, title.video, detected)
    # Frame count from the decoder is exact; container duration is not.
    frames = build_clip(source, info.main_video, target, title.video).num_frames
    return _Prepared(title, source, info, target, frames)


def disc_clip(project: Project, p: _Prepared) -> vs.VideoNode:
    """The exact picture that is encoded for a title: the reference for quality metrics."""
    pre = resolve_preprocess(project.disc.profiles, p.title.video.overrides)
    return build_clip(p.source, p.info.main_video, p.target, p.title.video, pre)


def _prepare(project: Project, project_file: Path, warnings: list[str]) -> list[_Prepared]:
    return [
        prepare_title(project, project_file, n, warnings) for n in range(1, len(project.titles) + 1)
    ]


def _menus(project: Project, p: _Prepared, project_dir: Path, work_dir: Path,
           warnings: list[str]) -> list:  # fmt: skip
    """Render the menu pages from the first title's picture and author them."""
    from dvd.menu.author import author_menus
    from dvd.menu.layout import expand, overlapping
    from dvd.menu.pictures import background_image, frame_images, logo_image
    from dvd.menu.render import render_page
    from dvd.menu.templates import template

    frame = (p.target.width, p.target.height, p.target.dar)
    display = (round(p.target.height * p.target.dar), p.target.height)
    pages = expand(project, p.info)
    for page in pages:
        for a, b in overlapping({btn.id: btn.rect for btn in page.buttons}):
            warnings.append(f"menu page {page.id}: buttons {a} and {b} overlap")
    try:
        backdrop = background_image(project.menus.background, p.source, p.info, project_dir,
                                    display)  # fmt: skip
    except ValueError as exc:
        raise BuildError(str(exc)) from None
    times = sorted({b.thumb for page in pages for b in page.buttons if b.thumb is not None})
    width = round(0.22 * display[0])
    thumbs = frame_images(p.source, p.info, times, (width, round(width * 9 / 16))) if times else {}
    tpl = template(project.menus.template)
    try:
        logo = logo_image(project.menus.logo, project_dir)
    except ValueError as exc:
        raise BuildError(str(exc)) from None
    rendered = {page.id: render_page(page, frame, backdrop, thumbs, tpl, logo) for page in pages}
    return author_menus(pages, rendered, project.menus.first, project.disc.standard,
                        p.target.dar, work_dir)  # fmt: skip


def _intro_path(project_file: Path, intro) -> Path:
    path = Path(intro.file)
    return path if path.is_absolute() else project_file.parent / path


def _intro_vob(project: Project, info: SourceInfo, film: _Prepared, budget: Plan,
               work_dir: Path, k: int, report: Progress) -> AuthorTitle:  # fmt: skip
    """An intro clip as a disc title: no crop, the film's aspect, first audio track as
    stereo AC-3."""
    v = info.main_video
    if v is None:
        raise BuildError(f"intro {info.path.name} has no video track")
    video = Video(crop="none", aspect=film.target.aspect)
    try:
        target = plan_target(v, project.disc.standard, video)
    except UnsupportedSource as exc:
        raise BuildError(f"intro {info.path.name}: {exc}") from None
    tag = f"i{k:02}"
    report(f"intro {k}", 0.0)
    clip = build_clip(info.path, v, target, video)
    settings = EncodeSettings(
        bitrate=budget.video_kbps, maxrate=budget.peak_kbps, aspect=target.aspect,
        standard=project.disc.standard, pulldown=target.pulldown, interlaced=target.interlaced,
    )  # fmt: skip
    wanted = resolve_profiles(project.disc.profiles)["encoder"]
    encoder, _note = encoders.choose(wanted)
    m2v = encoders.encode(encoder, clip, work_dir / f"{tag}.m2v", settings,
                          work_dir / f"{tag}_{encoder}")  # fmt: skip
    compliance = check_video(m2v, project.disc.standard)
    if not compliance.ok:
        raise BuildError(f"intro {k} video is not DVD compliant: " + "; ".join(compliance.errors))
    audio = []
    if info.audio:
        a = info.audio[0]
        offset = (a.start_time - v.start_time) * 1000
        out = work_dir / f"{tag}_a0.ac3"
        audio.append(encode_ac3(info.path, a.index, out, "2.0", 192, target.speedup,
                                delay_ms=offset, source_channels=a.channels))  # fmt: skip
    mpg = mux(m2v, audio, work_dir / f"{tag}.mpg")
    return AuthorTitle(vob=mpg.name, aspect=target.aspect)


def build(
    project_file: Path,
    out_dir: Path | None = None,
    work_dir: Path | None = None,
    progress: Progress | None = None,
    make_iso: bool = True,
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

    prepared = _prepare(project, project_file, warnings)
    intro_infos = [probe(_intro_path(project_file, i)) for i in project.first_play]
    # Intros are short; they share the films' bit rate, so the plan counts their time too.
    total = sum(p.duration for p in prepared) + sum(i.duration or 0 for i in intro_infos)
    audio_avg = sum(p.duration * sum(a.bitrate for a in p.title.audio) for p in prepared) / total
    budget = plan(
        project.disc.media,
        total,
        [round(audio_avg)],
        subtitle_tracks=max(len(t.subtitles) for t in project.titles),
        peak_kbps=resolve_profiles(project.disc.profiles)["peak_kbps"],
    )
    warnings += budget.warnings
    if not budget.fits or budget.video_kbps <= 0:
        raise BuildError(f"the titles do not fit on {project.disc.media.upper()}")

    disc_settings = resolve_profiles(project.disc.profiles)

    def sub_style(name: str):
        try:
            base = load_style(name)
        except StyleError as exc:
            raise BuildError(str(exc)) from None
        return for_viewing(base, disc_settings["subtitle_size"], disc_settings["safe_area"])

    author_titles = []
    for n, p in enumerate(prepared, start=1):
        tag = f"t{n:02}"
        tracks = disc_audio(p.title)
        audio_files = []
        night = disc_settings["audio_night"]
        for i, a in enumerate(tracks):
            report(f"title {n} audio {i + 1}", 0.0)
            source_track = next(t for t in p.info.audio if t.index == a.track)
            # Disc audio and video both start at 0; keep the file's own offset between them.
            offset = (source_track.start_time - p.info.main_video.start_time) * 1000
            delay = a.delay + offset
            copy = can_copy(source_track, a.channels, p.target.speedup, delay, night)
            audio_files.append(
                encode_ac3(
                    p.source,
                    a.track,
                    work_dir / f"{tag}_a{i}.ac3",
                    a.channels,
                    a.bitrate,
                    p.target.speedup,
                    disc_settings["audio_pitch"],
                    delay_ms=delay,
                    night=night,
                    source_channels=source_track.channels,
                    copy=copy,
                )  # fmt: skip
            )
        chapters = chapter_frames(p.title, p.info, p.target, p.frames)
        settings = EncodeSettings(
            bitrate=budget.video_kbps,
            maxrate=budget.peak_kbps,
            aspect=p.target.aspect,
            standard=project.disc.standard,
            pulldown=p.target.pulldown,
            interlaced=p.target.interlaced,
            chapters=chapters,
        )
        clip = disc_clip(project, p)
        title_settings = resolve_profiles(project.disc.profiles, p.title.video.overrides)
        encoder, note = encoders.choose(title_settings["encoder"])
        if note:
            warnings.append(f"title {n}: {note}")
        m2v = encoders.encode(
            encoder,
            clip,
            work_dir / f"{tag}.m2v",
            settings,
            work_dir / f"{tag}_{encoder}",
            progress=lambda f, n=n: report(f"title {n} video", f),
        )
        report(f"title {n} check", 0.0)
        compliance = check_video(m2v, project.disc.standard)
        if not compliance.ok:
            raise BuildError(
                f"title {n} video is not DVD compliant: " + "; ".join(compliance.errors)
            )
        warnings += [f"title {n}: {w}" for w in compliance.warnings]
        report(f"title {n} mux", 0.0)
        mpg = mux(m2v, audio_files, work_dir / f"{tag}.mpg")
        subs = disc_subtitles(p.title)
        for i, sub in enumerate(subs):
            cues = retime(_subtitle_cues(sub, p, project_file, work_dir / f"{tag}_s{i}.srt"),
                          float(p.target.speedup))  # fmt: skip
            mpg = add_subtitle_stream(
                mpg,
                work_dir / f"{tag}_s{i}.mpg",
                cues,
                i,
                (p.target.width, p.target.height, p.target.dar),
                project.disc.standard,
                work_dir / f"{tag}_subs",
                forced=sub.forced,
                style=sub_style(sub.style),
                progress=lambda f, n=n, i=i: report(f"title {n} subtitles {i + 1}", f),
                placement=placement(p.target),
            )
        muxed = check_mux(mpg)
        if not muxed.ok:
            raise BuildError(f"title {n} program stream is not DVD compliant: "
                             + "; ".join(muxed.errors))  # fmt: skip
        author_titles.append(
            AuthorTitle(
                vob=mpg.name,
                aspect=p.target.aspect,
                audio_langs=[a.lang for a in tracks],
                chapters=[timecode(f / Fraction(p.target.fps)) for f in chapters],
                subtitle_langs=[s.lang for s in subs],
                subtitles_on=bool(subs) and subs[0].default,
            )
        )
    menus = None
    if project.menus is not None:
        report("menus", 0.0)
        menus = _menus(project, prepared[0], project_file.parent, work_dir, warnings)
    intros = [
        _intro_vob(project, info, prepared[0], budget, work_dir, k, report)
        for k, info in enumerate(intro_infos, start=1)
    ]
    if intros:
        from PySide6.QtGui import QColor, QImage

        from dvd.author.dvdauthor import VMGM_STILL
        from dvd.menu.author import still_mpg
        from dvd.subs.render import _qt

        _qt()
        t = prepared[0].target
        black = QImage(t.width, t.height, QImage.Format.Format_RGB888)
        black.fill(QColor(16, 16, 16))
        still_mpg(black, project.disc.standard, t.dar, work_dir / VMGM_STILL)
    report("authoring", 0.0)
    video_ts = author(author_titles, project.disc.standard, work_dir, out_dir, menus=menus,
                      intros=intros, at_end=project.at_end)  # fmt: skip
    iso = None
    if make_iso:
        iso = write_iso(
            video_ts,
            out_dir / f"{name}.iso",
            project.disc.name,
            progress=lambda f: report("iso", f),
        )
    report("done", 1.0)
    return BuildResult(video_ts, budget, warnings, iso)
