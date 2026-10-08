from __future__ import annotations

import typer

from dvd import __version__, toolchain

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
            mark = typer.style("YOK ", fg=typer.colors.RED if s.required else typer.colors.YELLOW)
            detail = s.note or ("required" if s.required else "optional")
        typer.echo(f"{mark} {s.name:<{width}}  {s.purpose:<20} {detail}")
    if any(s.required and not s.found for s in statuses):
        raise typer.Exit(1)
