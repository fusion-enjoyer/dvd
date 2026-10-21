from __future__ import annotations

import dataclasses
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
    _, reason = project.suggest_standard(info.main_video.playback_fps if info.main_video else None)
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
    authoring: str | None = typer.Option(
        None, "--authoring", help="dvdauthor | own (our own authoring); default: the project's"
    ),
) -> None:
    """Encode and author the disc into a VIDEO_TS folder and a disc image."""
    from dvd.audio.ac3 import AudioError
    from dvd.author.dvdauthor import AuthorError
    from dvd.build import BuildError, build
    from dvd.output.iso import IsoError
    from dvd.video.hcenc import EncodeError
    from dvd.video.pipeline import UnsupportedSource

    if authoring not in (None, "dvdauthor", "own"):
        typer.echo("--authoring must be dvdauthor or own", err=True)
        raise typer.Exit(1)
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
        result = build(path, out_dir=out, progress=show, make_iso=not no_iso, authoring=authoring)
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
def verify(
    m2v: Path = typer.Argument(..., help="Video stream (.m2v) or program stream (.mpg/.vob)"),
    standard: str = typer.Option("pal", "--standard", help="pal or ntsc"),
) -> None:
    """Check an MPEG-2 video stream or a muxed program stream against DVD-Video limits."""
    from dvd.video.compliance import check as check_video

    if m2v.suffix.lower() in (".mpg", ".vob", ".mpeg"):
        _verify_mux(m2v)
        return
    try:
        r = check_video(m2v, standard)
    except (OSError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from None
    i = r.info
    typer.echo(
        f"{i.width}x{i.height} {float(i.frame_rate):.3f} fps | {len(i.pictures)} pictures, "
        f"{len(i.gops)} GOPs (longest {max(i.gops, default=0)}) | average "
        f"{r.average_bps / 1e6:.2f} Mbps, 1 s peak {r.peak_bps / 1e6:.2f} Mbps | "
        f"VBV low {r.vbv_lowest:.0%}"
    )
    for w in r.warnings:
        typer.echo(f"warning: {w}")
    for e in r.errors:
        typer.echo(f"error: {e}", err=True)
    if r.errors:
        raise typer.Exit(1)
    typer.echo("ok: DVD compliant")


def _verify_mux(path: Path) -> None:
    from dvd.author.pscheck import check as check_mux

    try:
        r = check_mux(path)
    except OSError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from None
    rates = ", ".join(f"{name} {s.bytes * 8 / r.duration / 1e3:.0f} kbps"
                      for name, s in sorted(r.streams.items()) if r.duration)  # fmt: skip
    typer.echo(f"{r.packs} packs, {r.duration:.1f} s | mux rate {r.max_mux_rate / 1e6:.2f} Mbps, "
               f"1 s peak {r.peak_bps / 1e6:.2f} Mbps | {rates}")  # fmt: skip
    for e in r.errors:
        typer.echo(f"error: {e}", err=True)
    if r.errors:
        raise typer.Exit(1)
    typer.echo("ok: DVD compliant")


def _print_measurement(m, offset: int = 0) -> None:
    from dvd.qa.metrics import Measurement

    assert isinstance(m, Measurement)
    typer.echo(
        f"SSIMULACRA2 mean {m.mean('ssimu2'):.1f}, 5% low {m.percentile('ssimu2', 5):.1f} | "
        f"XPSNR-Y mean {m.mean('xpsnr'):.2f} dB, 5% low {m.percentile('xpsnr', 5):.2f} dB"
    )
    typer.echo("worst seconds:")
    for scene in m.worst_scenes(5):
        scene = dataclasses.replace(scene, start=scene.start + offset, end=scene.end + offset)
        typer.echo(
            f"  {scene.timecode(m.fps)}  SSIMULACRA2 {scene.ssimu2:5.1f}  "
            f"XPSNR {scene.xpsnr:5.2f} dB"
        )


def _parse_time(text: str) -> float:
    from dvd.project.model import parse_timecode

    return float(text) if text.replace(".", "", 1).isdigit() else parse_timecode(text)


@app.command()
def trial(
    path: Path = typer.Argument(..., help="Project file"),
    at: str = typer.Option("0", "--at", help="Start, as h:mm:ss or seconds of playback"),
    seconds: float = typer.Option(20, "--seconds", help="Length of the trial"),
    title: int = typer.Option(1, "--title", help="Title number"),
    kbps: int | None = typer.Option(None, "--kbps", help="Average video bit rate to try"),
) -> None:
    """Encode a short stretch with the disc settings and score it against the source."""
    from dvd.qa.trial import trial_encode

    r = trial_encode(path, _parse_time(at), seconds, title, video_kbps=kbps)
    typer.echo(f"frames {r.start}-{r.start + r.frames - 1} at {r.video_kbps} kbit/s average")
    _print_measurement(r.measurement, offset=r.start)
    typer.echo(f"A/B of the worst frame: {r.reference_png}  {r.encoded_png}")


@app.command()
def measure(
    path: Path = typer.Argument(..., help="Project file built with `dvd build`"),
    step: int = typer.Option(5, "--step", help="Score every n-th frame"),
) -> None:
    """Score the encoded titles of a build against the pictures that went into the encoder."""
    from dvd.qa.trial import measure_build

    try:
        results = measure_build(path, step)
    except FileNotFoundError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from None
    for n, m in enumerate(results, start=1):
        typer.echo(f"title {n}:")
        _print_measurement(m)


profile_app = typer.Typer(help="Show, save and share profile settings.", no_args_is_help=True)
app.add_typer(profile_app, name="profile")


@profile_app.command("show")
def profile_show(path: Path = typer.Argument(..., help="Project file")) -> None:
    """Print every setting of a project and the layer that set it."""
    from dvd.profiles import ProfileError, resolve

    proj_ = project.load(path)
    try:
        r = resolve(proj_.disc.profiles, proj_.titles[0].video.overrides)
    except ProfileError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from None
    width = max(map(len, r.values))
    for key, value in r.values.items():
        typer.echo(f"{key:<{width}}  {value!s:<16} {r.origin[key]}")


@profile_app.command("save")
def profile_save(
    name: str = typer.Argument(..., help="Profile name, e.g. 'Salon TV'"),
    path: Path = typer.Argument(..., help="Project whose current settings are saved"),
) -> None:
    """Save a project's resolved settings as a user profile."""
    from dvd.profiles import resolve, save_user_profile

    proj_ = project.load(path)
    r = resolve(proj_.disc.profiles, proj_.titles[0].video.overrides)
    typer.echo(f"wrote {save_user_profile(name, r.values)}")


@profile_app.command("list")
def profile_list() -> None:
    """List saved user profiles."""
    from dvd.profiles import list_user_profiles, user_profile_dir

    names = list_user_profiles()
    typer.echo("\n".join(names) if names else f"no profiles in {user_profile_dir()}")


@profile_app.command("export")
def profile_export(name: str, file: Path) -> None:
    """Copy a user profile to a file, to take it to another computer."""
    from dvd.profiles import load_user_profile, save_user_profile

    settings = load_user_profile(name)
    save_user_profile(name, settings, folder=file.parent)
    target = file.parent / f"{name}.yaml"
    if target != file:
        target.replace(file)
    typer.echo(f"wrote {file}")


@profile_app.command("import")
def profile_import(file: Path) -> None:
    """Add a profile file exported on another computer."""
    from dvd.profiles import ProfileError, load_user_profile, save_user_profile

    try:
        settings = load_user_profile(file.stem, folder=file.parent)
    except ProfileError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from None
    typer.echo(f"wrote {save_user_profile(file.stem, settings)}")


@app.command()
def ifo(
    path: Path = typer.Argument(..., help="VIDEO_TS folder (or a disc folder holding one)"),
    commands: bool = typer.Option(False, "--commands", "-c", help="Show the VM commands"),
) -> None:
    """Show what a DVD's IFO files hold: titles, menus, cells, restrictions, commands."""
    from dvd.ifo import IfoError, read_disc
    from dvd.ifo.report import describe

    folder = path / "VIDEO_TS" if (path / "VIDEO_TS").is_dir() else path
    try:
        disc = read_disc(folder)
    except (IfoError, OSError, IndexError) as exc:
        typer.echo(f"cannot read {folder}: {exc}", err=True)
        raise typer.Exit(1) from None
    for line in describe(disc, commands):
        typer.echo(line)


@app.command()
def validate(
    path: Path = typer.Argument(..., help="VIDEO_TS folder (or a disc folder holding one)"),
) -> None:
    """Check a finished DVD-Video folder against the rules players rely on."""
    from dvd.qa.validate import validate as check

    folder = path / "VIDEO_TS" if (path / "VIDEO_TS").is_dir() else path
    found = check(folder)
    for f in found:
        typer.echo(str(f))
    errors = sum(f.level == "error" for f in found)
    typer.echo(f"{errors} errors, {len(found) - errors} warnings")
    if errors:
        raise typer.Exit(1)


template_app = typer.Typer(help="List, export and import menu templates.", no_args_is_help=True)
app.add_typer(template_app, name="template")


@template_app.command("list")
def template_list() -> None:
    """Built-in and user menu templates."""
    from dvd.menu.templates import TEMPLATES, list_templates

    for name in list_templates():
        typer.echo(f"{name}{'' if name not in TEMPLATES else '  (built-in)'}")


@template_app.command("export")
def template_export(
    name: str = typer.Argument(..., help="Template name"),
    out: Path = typer.Argument(..., help="File to write (.yaml)"),
) -> None:
    """Write a template to a file to share."""
    from dvd.menu.templates import TemplateError, export_template

    try:
        typer.echo(f"wrote {export_template(name, out)}")
    except TemplateError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from None


@template_app.command("import")
def template_import(path: Path = typer.Argument(..., help="Exported template file")) -> None:
    """Add a shared template to your templates."""
    from dvd.menu.templates import TemplateError, import_template

    try:
        typer.echo(f"imported as {import_template(path)!r}")
    except (TemplateError, OSError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from None


series_app = typer.Typer(help="Turn a season folder into a set of discs.", no_args_is_help=True)
app.add_typer(series_app, name="series")


def _season(folder: Path):
    from dvd.project.season import read_season

    try:
        return read_season(folder)
    except (OSError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from None


@series_app.command("plan")
def series_plan(
    folder: Path = typer.Argument(..., help="Season folder"),
    media: str = typer.Option("dvd9", help="dvd5 or dvd9"),
    quality: str = typer.Option("iyi", help="standart (4 Mbps), iyi (5) or yuksek (6)"),
) -> None:
    """Show how the episodes would be shared out over discs."""
    from dvd.project.season import plan_season

    s = plan_season(_season(folder), media, quality)
    for n, (disc, kbps) in enumerate(zip(s.discs, s.video_kbps, strict=True), start=1):
        minutes = sum(e.duration for e in disc) / 60
        codes = f"{disc[0].code}-{disc[-1].code}" if len(disc) > 1 else disc[0].code
        typer.echo(f"disc {n}/{s.count}: {codes}  {len(disc)} episodes, {minutes:.0f} min, "
                   f"video {kbps / 1000:.1f} Mbps")  # fmt: skip


@series_app.command("new")
def series_new(
    folder: Path = typer.Argument(..., help="Season folder"),
    media: str = typer.Option("dvd9", help="dvd5 or dvd9"),
    quality: str = typer.Option("iyi", help="standart, iyi or yuksek"),
    name: str = typer.Option("", help="Series name on the discs (default: the folder name)"),
    tmdb: bool = typer.Option(True, help="Episode names and pictures from TMDB (needs a key)"),
) -> None:
    """Write one project file per disc into the season folder."""
    from dvd import settings
    from dvd.meta.tmdb import Client, TmdbError
    from dvd.project import save
    from dvd.project.season import disc_projects, lookup, plan_season

    season = _season(folder)
    s = plan_season(season, media, quality)
    meta = None
    if tmdb and settings.tmdb_key():
        try:
            meta = lookup(season, Client(settings.tmdb_key()))
        except TmdbError as exc:
            typer.echo(f"TMDB: {exc}; going on without it", err=True)
        if meta is None:
            typer.echo(f"TMDB does not know {season.name!r}; episode numbers are used", err=True)
    try:
        projects = disc_projects(season, s, name, meta)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from None
    for (out, disc_project), disc in zip(projects, s.discs, strict=True):
        save(disc_project, out)
        typer.echo(f"wrote {out.name}: {disc[0].code}-{disc[-1].code}")


@app.command()
def gui(path: Path | None = typer.Argument(None, help="Video or project file to open")) -> None:
    """Open the desktop application."""
    from dvd.gui.app import main as gui_main

    raise typer.Exit(gui_main(["dvd", str(path)] if path else ["dvd"]))
