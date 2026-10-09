"""Menu templates: how a page is laid out and drawn. Layout and drawing read the same
template, so the buttons land where the pictures show them."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

RGB = tuple[int, int, int]


@dataclass(frozen=True)
class Template:
    name: str
    # Layout
    main: Literal["column-left", "row-bottom", "column-center"] = "column-left"
    title_align: Literal["left", "center"] = "left"
    title_y: float = 0.08  # top of the title box, fraction of the frame height
    # Drawing
    shade: Literal["left", "bottom", "vignette"] = "left"
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
}  # fmt: skip


def template(name: str) -> Template:
    return TEMPLATES.get(name, TEMPLATES["minimal"])
