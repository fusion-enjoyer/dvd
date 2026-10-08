from __future__ import annotations

import json
from pathlib import Path

import typer

from dvd import __version__, toolchain
from dvd.probe import ProbeError, probe, report

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
