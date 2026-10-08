from __future__ import annotations

import json
import sys
from pathlib import Path

import typer

from dvd import __version__, project, toolchain
from dvd.probe import ProbeError, probe, report
from dvd.project.check import check_sources

app = typer.Typer(no_args_is_help=True, add_completion=False)


def _version(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(False, "--version", callback=_version, is_eager=True),
) -> None:
    """DVD-Video authoring tool."""
    # Redirected output would otherwise use the ANSI code page and mangle Turkish names.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


@app.command()
def doctor() -> None:
    """Check that the external tools are installed and report their versions."""
    statuses = toolchain.check_all()
    width = max(len(s.name) for s in statuses)
    for s in statuses:
        if s.found:
            mark = typer.style("ok  ", fg=typer.colors.GREEN)
            detail = f"{s.version or '?':<14} {s.path}"
        else:
            mark = typer.style("miss", fg=typer.colors.RED if s.required else typer.colors.YELLOW)
            detail = s.note or ("required" if s.required else "optional")
        typer.echo(f"{mark} {s.name:<{width}}  {s.purpose:<20} {detail}")
    if any(s.required and not s.found for s in statuses):
        raise typer.Exit(1)


@app.command("probe")
def probe_cmd(
    path: Path = typer.Argument(..., help="Video file to analyse"),
    as_json: bool = typer.Option(False, "--json", help="Print the full analysis as JSON"),
) -> None:
    """Analyse a source file: video, audio and subtitle tracks, chapters."""
    try:
        info = probe(path)
    except ProbeError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from None
    if as_json:
        typer.echo(json.dumps(report.to_json(info), ensure_ascii=False, indent=2))
    else:
        typer.echo(report.summary(info))


@app.command()
def new(
    source: Path = typer.Argument(..., help="Video file to put on the disc"),
    out: Path | None = typer.Option(None, "--out", "-o", help="Project file to write"),
    force: bool = typer.Option(False, "--force", help="Overwrite an existing project file"),
) -> None:
    """Create a project for a source file with defaults chosen from its contents."""
    out = out or Path.cwd() / f"{source.stem}{project.PROJECT_SUFFIX}"
    if out.exists() and not force:
        typer.echo(f"{out} already exists; use --force to overwrite", err=True)
        raise typer.Exit(1)
    try:
        info = probe(source)
    except ProbeError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from None
    proj = project.new_project(info, out.parent)
    project.save(proj, out)
    _, reason = project.suggest_standard(info.main_video.fps if info.main_video else None)
    typer.echo(f"wrote {out}")
    typer.echo(f"standard {proj.disc.standard.upper()} ({reason}), media {proj.disc.media.upper()}")


@app.command()
def check(path: Path = typer.Argument(..., help="Project file")) -> None:
    """Validate a project file and the sources it refers to."""
    try:
        proj = project.load(path)
    except project.ProjectError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from None
    problems = check_sources(proj, path)
    for line in problems:
        typer.echo(line, err=True)
    if problems:
        raise typer.Exit(1)
    d = proj.disc
    typer.echo(
        f"ok: {d.name} | {d.standard.upper()} {d.media.upper()} | {len(proj.titles)} title(s)"
    )


@app.command("build")
def build_cmd(
    path: Path = typer.Argument(..., help="Project file"),
    out: Path | None = typer.Option(None, "--out", "-o", help="Folder for VIDEO_TS and the ISO"),
    no_iso: bool = typer.Option(False, "--no-iso", help="Stop after writing VIDEO_TS"),
) -> None:
    """Encode and author the disc into a VIDEO_TS folder and a disc image."""
    from dvd.audio.ac3 import AudioError
    from dvd.author.dvdauthor import AuthorError
    from dvd.build import BuildError, build
    from dvd.output.iso import IsoError
    from dvd.video.hcenc import EncodeError
    from dvd.video.pipeline import UnsupportedSource

    try:
        problems = check_sources(project.load(path), path)
    except project.ProjectError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from None
    if problems:
        typer.echo("\n".join(problems), err=True)
        raise typer.Exit(1)

    last: dict[str, int] = {}

    def show(stage: str, fraction: float) -> None:
        step = int(fraction * 10)
        if last.get(stage) != step:
            last[stage] = step
            typer.echo(f"{stage:<20} {fraction:>4.0%}")

    errors = (
        BuildError, AudioError, AuthorError, EncodeError, UnsupportedSource, ProbeError, IsoError
    )  # fmt: skip
    try:
        result = build(path, out_dir=out, progress=show, make_iso=not no_iso)
    except errors as exc:
        typer.echo(f"build failed: {exc}", err=True)
        raise typer.Exit(1) from None
    p = result.plan
    for w in result.warnings:
        typer.echo(f"warning: {w}")
    typer.echo(
        f"video {p.video_kbps / 1000:.2f} Mbps avg, {p.peak_kbps / 1000:.1f} peak | "
        f"estimated {p.estimated_bytes / 1e9:.2f} of {p.capacity_bytes / 1e9:.2f} GB"
    )
    typer.echo(f"wrote {result.video_ts}")
    if result.iso:
        typer.echo(f"wrote {result.iso}")


@app.command("iso")
def iso_cmd(
    video_ts: Path = typer.Argument(..., help="VIDEO_TS folder"),
    out: Path | None = typer.Option(None, "--out", "-o", help="Image file to write"),
    label: str | None = typer.Option(None, "--label", help="Volume label (default: folder name)"),
) -> None:
    """Write a DVD-Video disc image (UDF 1.02 + ISO 9660) from a VIDEO_TS folder."""
    from dvd.output.iso import IsoError, volume_label, write_iso

    name = label or video_ts.resolve().parent.name
    out = out or video_ts.resolve().parent / f"{name}.iso"
    try:
        write_iso(video_ts, out, name)
    except (IsoError, OSError) as exc:
        typer.echo(f"iso failed: {exc}", err=True)
        raise typer.Exit(1) from None
    typer.echo(f"wrote {out} (label {volume_label(name)})")


@app.command()
def gui(path: Path | None = typer.Argument(None, help="Video or project file to open")) -> None:
    """Open the desktop application."""
    from dvd.gui.app import main as gui_main

    raise typer.Exit(gui_main(["dvd", str(path)] if path else ["dvd"]))
