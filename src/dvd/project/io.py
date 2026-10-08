"""Load and save project files."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import yaml
from pydantic import ValidationError

from dvd.project.model import Project, Title


class ProjectError(Exception):
    pass


def _where(loc: tuple) -> str:
    out = ""
    for part in loc:
        if isinstance(part, int):
            out += f"[{part}]"
        elif not (isinstance(part, str) and ("[" in part or part.startswith("function-"))):
            # pydantic adds union-branch names like "list[str]" or "function-after[...]"
            out += f".{part}" if out else str(part)
    return out or "(file)"


def format_errors(exc: ValidationError) -> str:
    seen, lines = set(), []
    for err in exc.errors():
        line = f"{_where(err['loc'])}: {err['msg'].removeprefix('Value error, ')}"
        if line not in seen:
            seen.add(line)
            lines.append(line)
    return "\n".join(lines)


def load(path: Path | str) -> Project:
    path = Path(path)
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ProjectError(f"project file not found: {path}") from None
    except yaml.YAMLError as exc:
        raise ProjectError(f"{path.name} is not valid YAML: {exc}") from None
    if not isinstance(data, dict):
        raise ProjectError(f"{path.name} does not contain a project")
    try:
        return Project.model_validate(data)
    except ValidationError as exc:
        raise ProjectError(f"{path.name} has errors:\n{format_errors(exc)}") from None


def dumps(project: Project) -> str:
    data = project.model_dump(mode="json", exclude_none=True)
    return yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=100)


def save(project: Project, path: Path | str) -> None:
    """Write atomically, so an interrupted autosave never leaves a half-written project."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".yaml")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(dumps(project))
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def source_path(project_file: Path, title: Title) -> Path:
    """Source paths may be relative to the project file's folder."""
    p = Path(title.source)
    return p if p.is_absolute() else (project_file.parent / p).resolve()
