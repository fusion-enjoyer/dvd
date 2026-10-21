"""Menu templates: how a page is laid out and drawn. Layout and drawing read the same
template, so the buttons land where the pictures show them.

Besides the built-in templates, users keep their own in %APPDATA%\\DVD Studyo\\templates
(DVD_TEMPLATE_DIR overrides it): a YAML file naming a built-in `base` and the fields that
differ from it. Exported files carry the same; importing one copies it into the folder.
"""

from __future__ import annotations

import os
import re
from dataclasses import asdict, dataclass, fields, replace
from pathlib import Path
from typing import Any, Literal, get_args, get_type_hints

import yaml

RGB = tuple[int, int, int]


@dataclass(frozen=True)
class Template:
    name: str
    # Layout
    main: Literal["column-left", "row-bottom", "column-center", "panel-left"] = "column-left"
    title_align: Literal["left", "center"] = "left"
    title_y: float = 0.08  # top of the title box, fraction of the frame height
    title_x: float = 0.10
    title_width: float = 0.80  # the title (or logo) box, fraction of the frame width
    # Drawing
    shade: Literal["left", "bottom", "vignette", "panel"] = "left"
    shade_strength: float = 0.62
    tint: RGB | None = None  # colour wash over the background
    title_font: str = "Bricolage Grotesque"
    label_font: str = "Source Sans 3"
    uppercase: bool = False  # labels in capitals
    text: RGB = (226, 221, 212)  # labels: off-white, inside video levels
    title: RGB = (236, 231, 222)
    muted: RGB = (160, 154, 144)
    highlight: RGB = (240, 180, 73)
    select: RGB = (250, 246, 238)
    marker: Literal["bar", "underline", "arrow"] = "bar"
    shadow: bool = False  # soft drop shadow under labels and title
    label_size: float = 0.040  # of the frame height
    title_size: float = 0.070


TEMPLATES = {
    "minimal": Template("minimal"),
    # Film poster feel: picture kept bright, a dark band at the bottom, centred title above a
    # row of capitalised buttons, a thin underline as the cursor.
    "sinematik": Template(
        "sinematik", main="row-bottom", title_align="center", title_y=0.60, shade="bottom",
        shade_strength=0.85, uppercase=True, highlight=(232, 204, 150), marker="underline",
        label_size=0.036, title_size=0.085,
    ),
    # Early-2000s retail disc: blue wash, vignette, centred title on top with a shadow,
    # centred buttons with an arrow in front of the chosen one.
    "2000ler": Template(
        "2000ler", main="column-center", title_align="center", title_y=0.07, shade="vignette",
        shade_strength=0.75, tint=(20, 50, 110), label_font="Source Sans 3",
        text=(214, 226, 240), title=(240, 244, 250), muted=(150, 170, 196),
        highlight=(110, 205, 255), marker="arrow", shadow=True, title_size=0.075,
    ),
    # Series box set: a dark panel on the left holds the title or logo, the disc number and
    # the buttons; the series picture stays bright on the right.
    "dizi": Template(
        "dizi", main="panel-left", title_x=0.07, title_y=0.10, title_width=0.34,
        shade="panel", shade_strength=0.80, highlight=(236, 120, 72), title_size=0.062,
    ),
}  # fmt: skip

PANEL_WIDTH = 0.46  # of the frame, the "dizi" template's left panel


class TemplateError(ValueError):
    pass


def template_folder() -> Path:
    if env := os.environ.get("DVD_TEMPLATE_DIR"):
        return Path(env)
    base = Path(os.environ.get("APPDATA") or Path.home() / ".config")
    return base / "DVD Studyo" / "templates"


def _file(name: str, folder: Path | None) -> Path:
    if not re.fullmatch(r"[\w\- ]{1,40}", name):
        raise TemplateError(f"template name {name!r} may only hold letters, digits, spaces, "
                            "- and _")  # fmt: skip
    return (folder or template_folder()) / f"{name}.yaml"


def choices(field_name: str) -> tuple[str, ...]:
    """The allowed values of a Literal field ("main", "marker", ...); empty for others."""
    return tuple(a for a in get_args(get_type_hints(Template)[field_name]) if isinstance(a, str))


def _clean(values: dict[str, Any]) -> dict[str, Any]:
    out = {}
    known = {f.name: f for f in fields(Template)}
    for key, value in values.items():
        if key not in known or key == "name":
            raise TemplateError(f"unknown template field {key!r}")
        default = getattr(Template("x"), key)
        if key == "tint" or isinstance(default, tuple):
            if value is None and key == "tint":
                out[key] = None
                continue
            value = tuple(int(c) for c in value)
            if len(value) != 3 or not all(0 <= c <= 255 for c in value):
                raise TemplateError(f"{key} must be three values 0-255")
        elif choices(key):
            if value not in choices(key):
                raise TemplateError(f"{key} must be one of {', '.join(choices(key))}")
        elif isinstance(default, bool):
            value = bool(value)
        elif isinstance(default, float):
            value = float(value)
            if not 0 <= value <= 1:
                raise TemplateError(f"{key} must be between 0 and 1")
        else:
            value = str(value)
        out[key] = value
    return out


def _from_data(name: str, data: dict[str, Any]) -> Template:
    data = dict(data)
    base = data.pop("base", "minimal")
    data.pop("name", None)
    if base not in TEMPLATES:
        raise TemplateError(f"unknown base template {base!r}")
    return replace(TEMPLATES[base], name=name, **_clean(data))


def _to_data(tpl: Template, base: str) -> dict[str, Any]:
    ref = TEMPLATES[base]
    changed = {k: (list(v) if isinstance(v, tuple) else v) for k, v in asdict(tpl).items()
               if k != "name" and v != getattr(ref, k)}  # fmt: skip
    return {"base": base, **changed}


def list_templates(folder: Path | None = None) -> list[str]:
    folder = folder or template_folder()
    users = sorted(p.stem for p in folder.glob("*.yaml")) if folder.is_dir() else []
    return [*TEMPLATES, *(u for u in users if u not in TEMPLATES)]


def load_template(name: str, folder: Path | None = None) -> Template:
    if name in TEMPLATES:
        return TEMPLATES[name]
    path = _file(name, folder)
    if not path.is_file():
        raise TemplateError(f"no menu template named {name!r}")
    return _from_data(name, yaml.safe_load(path.read_text(encoding="utf-8")) or {})


def save_template(name: str, tpl: Template, base: str = "minimal",
                  folder: Path | None = None) -> Path:  # fmt: skip
    """Store `tpl` as the user template `name`, written as its differences from `base`."""
    if name in TEMPLATES:
        raise TemplateError(f"{name!r} is a built-in template; save under another name")
    path = _file(name, folder)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = _to_data(replace(tpl, name=name), base)
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


def export_template(name: str, out: Path, folder: Path | None = None) -> Path:
    """A template as a file to give to someone (built-ins too: their base is themselves)."""
    tpl = load_template(name, folder)
    if name in TEMPLATES:
        data = {"base": name}
    else:
        data = yaml.safe_load(_file(name, folder).read_text(encoding="utf-8")) or {}
    _from_data(name, data)  # refuse to write a broken file
    out.write_text(yaml.safe_dump({"name": tpl.name, **data}, allow_unicode=True,
                                  sort_keys=False), encoding="utf-8")  # fmt: skip
    return out


def import_template(path: Path, folder: Path | None = None) -> str:
    """Copy an exported template into the user folder; its name is the file's `name` (or the
    file name), with a number added when it is taken."""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise TemplateError(f"{Path(path).name} is not a menu template")
    wanted = str(data.pop("name", None) or Path(path).stem)
    taken = set(list_templates(folder))
    name, n = wanted, 2
    while name in taken:
        name, n = f"{wanted} {n}", n + 1
    tpl = _from_data(name, data)
    save_template(name, tpl, data.get("base", "minimal"), folder)
    return name


def template(name: str) -> Template:
    """The template a project names; an unknown or broken one falls back to Minimal."""
    try:
        return load_template(name)
    except TemplateError:
        return TEMPLATES["minimal"]
