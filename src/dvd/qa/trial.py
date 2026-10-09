"""Trial encode: one stretch of a title with the full disc settings, measured and saved as A/B
images, to judge settings before committing hours to the whole film."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import vapoursynth as vs

from dvd.build import disc_clip, estimate, prepare_title
from dvd.probe import probe
from dvd.project import load, source_path
from dvd.qa.metrics import Measurement, measure
from dvd.video.hcenc import EncodeSettings, encode

core = vs.core


@dataclass
class TrialResult:
    m2v: Path
    measurement: Measurement
    start: int
    frames: int
    video_kbps: int
    peak_kbps: int
    worst_frame: int  # within the trial
    reference_png: Path
    encoded_png: Path


def save_frame(clip: vs.VideoNode, n: int, path: Path, aspect: float, standard: str) -> Path:
    """Frame `n` as RGB PNG at its display shape (16:9 frames are widened to 1024x576)."""
    from PySide6.QtGui import QImage

    matrix = "470bg" if standard == "pal" else "170m"
    width = round(clip.height * aspect / 2) * 2
    rgb = core.resize.Spline36(clip, width=width, format=vs.RGB24, matrix_in_s=matrix)
    with rgb.get_frame(n) as f:
        pixels = np.ascontiguousarray(np.dstack([np.asarray(f[i]) for i in range(3)]))
    h, w, _ = pixels.shape
    if not QImage(pixels.data, w, h, w * 3, QImage.Format.Format_RGB888).save(str(path)):
        raise OSError(f"cannot write {path}")
    return path


def trial_encode(
    project_file: Path,
    at: float,
    seconds: float = 20.0,
    title: int = 1,
    out_dir: Path | None = None,
    progress: Callable[[str, float], None] | None = None,
    video_kbps: int | None = None,
) -> TrialResult:
    """Encode `seconds` from `at` (playback seconds) of `title`; `video_kbps` overrides the
    planned average, to compare bit rates on the same stretch."""
    project_file = Path(project_file).resolve()
    project = load(project_file)
    out_dir = out_dir or project_file.parent / "build" / "trial"
    out_dir.mkdir(parents=True, exist_ok=True)
    p = prepare_title(project, project_file, title)
    clip = disc_clip(project, p)
    fps = p.target.fps
    start = max(0, min(clip.num_frames - 1, round(at * fps)))
    count = max(1, min(clip.num_frames - start, round(seconds * fps)))
    piece = clip[start : start + count]

    infos = [probe(source_path(project_file, t)) for t in project.titles]
    plan = estimate(project, infos)
    bitrate = video_kbps or plan.video_kbps
    settings = EncodeSettings(
        bitrate=bitrate,
        maxrate=plan.peak_kbps,
        aspect=p.target.aspect,
        standard=project.disc.standard,
        pulldown=p.target.pulldown,
    )
    report = (lambda stage: lambda f: progress(stage, f)) if progress else (lambda _s: None)
    m2v = encode(piece, out_dir / "trial.m2v", settings, out_dir / "hcenc", report("encode"))
    result = measure(piece, m2v, project.disc.standard, progress=report("measure"))
    worst = min(result.scores, key=lambda s: s.ssimu2).frame
    aspect = float(p.target.dar)
    encoded = core.std.AssumeFPS(core.bs.VideoSource(str(m2v)), src=piece)
    return TrialResult(
        m2v, result, start, count, bitrate, plan.peak_kbps, worst,
        save_frame(piece, worst, out_dir / "reference.png", aspect, project.disc.standard),
        save_frame(encoded, worst, out_dir / "encoded.png", aspect, project.disc.standard),
    )  # fmt: skip


def measure_build(
    project_file: Path, step: int = 5, progress: Callable[[str, float], None] | None = None
) -> list[Measurement]:
    """Score the titles a previous `dvd build` encoded (t01.m2v, ... in the work folder)."""
    from dvd.build import safe_name

    project_file = Path(project_file).resolve()
    project = load(project_file)
    work = project_file.parent / "build" / safe_name(project.disc.name)
    results = []
    for n in range(1, len(project.titles) + 1):
        m2v = work / f"t{n:02}.m2v"
        if not m2v.is_file():
            raise FileNotFoundError(f"{m2v} not found; run `dvd build` first")
        p = prepare_title(project, project_file, n)
        stage = f"title {n} measure"
        results.append(
            measure(
                disc_clip(project, p),
                m2v,
                project.disc.standard,
                step,
                (lambda f, s=stage: progress(s, f)) if progress else None,
            )  # fmt: skip
        )
    return results
