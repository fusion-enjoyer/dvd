"""Project file model: everything needed to rebuild a disc from its sources.

A project is a YAML file (``*.dvd.yaml``) that people may also edit by hand, so unknown keys are
rejected (a typo should not silently do nothing) and DVD-Video limits are checked on load.
"""

from __future__ import annotations

import re
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    PlainSerializer,
    field_validator,
    model_validator,
)

from dvd.lang import to_dvd_code

PROJECT_SUFFIX = ".dvd.yaml"

# DVD-Video limits
MAX_TITLES = 99
MAX_AUDIO_TRACKS = 8
MAX_SUBTITLE_TRACKS = 32
MAX_CHAPTERS = 99
AC3_BITRATES = (192, 224, 256, 320, 384, 448)  # kbit/s; 448 is the DVD maximum

Standard = Literal["pal", "ntsc"]
Media = Literal["dvd5", "dvd9"]
ContentProfile = Literal[
    "modern-film", "grenli-film", "eski-film", "animasyon-2d", "animasyon-3d", "dizi",
    "yayin", "icerik-4-3", "telefon", "kamera", "eski-kamera", "ekran-kaydi",
]  # fmt: skip
ViewingProfile = Literal[
    "modern-tv", "projeksiyon", "crt", "bilgisayar", "konsol", "tasinabilir", "evrensel"
]
AudioProfile = Literal["tv", "5.1", "gece", "hepsi"]


def _lang(value: Any) -> str:
    code = to_dvd_code(str(value)) if value is not None else None
    if code is None:
        raise ValueError(f"unknown language code {value!r}; use a two-letter code such as 'tr'")
    return code


Lang = Annotated[str, BeforeValidator(_lang)]


def _kbps(value: Any) -> int:
    if isinstance(value, int):
        return value // 1000 if value >= 1000 else value
    m = re.fullmatch(r"\s*(\d+)\s*k?\s*", str(value).lower())
    if not m:
        raise ValueError(f"bitrate {value!r} is not like '448k'")
    return int(m.group(1))


Kbps = Annotated[int, BeforeValidator(_kbps), PlainSerializer(lambda v: f"{v}k", return_type=str)]

_TIMECODE = re.compile(r"^(?:(\d+):)?(\d{1,2}):(\d{1,2})(?:\.(\d{1,3}))?$")


def parse_timecode(text: str) -> float:
    """'1:02:03.5', '02:03' -> seconds."""
    m = _TIMECODE.match(text.strip())
    if not m:
        raise ValueError(f"timecode {text!r} is not like 'h:mm:ss.mmm'")
    h, mnt, s, frac = m.groups()
    if int(mnt) > 59 or int(s) > 59:
        raise ValueError(f"timecode {text!r} has minutes or seconds above 59")
    return (
        int(h or 0) * 3600
        + int(mnt) * 60
        + int(s)
        + (int(frac.ljust(3, "0")) / 1000 if frac else 0)
    )


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class Profiles(Strict):
    content: ContentProfile = "modern-film"
    viewing: ViewingProfile = "modern-tv"
    audio: AudioProfile = "5.1"
    user: str | None = Field(None, description="saved user profile applied on top")


class Disc(Strict):
    name: str = Field(min_length=1, max_length=64)
    standard: Standard
    media: Media = "dvd9"
    profiles: Profiles = Field(default_factory=Profiles)


class Crop(Strict):
    top: int = Field(0, ge=0)
    bottom: int = Field(0, ge=0)
    left: int = Field(0, ge=0)
    right: int = Field(0, ge=0)


class Video(Strict):
    crop: Literal["auto", "none"] | Crop = "auto"
    aspect: Literal["auto", "16:9", "4:3"] = "auto"
    overrides: dict[str, Any] = Field(default_factory=dict)


class Audio(Strict):
    track: int = Field(ge=0, description="stream index in the source file")
    lang: Lang
    codec: Literal["ac3"] = "ac3"
    channels: Literal["2.0", "5.1"] = "5.1"
    bitrate: Kbps = 448
    default: bool = False
    delay: int = Field(0, ge=-10_000, le=10_000, description="ms; positive plays the audio later")

    @field_validator("bitrate")
    @classmethod
    def _ac3_bitrate(cls, v: int) -> int:
        if v not in AC3_BITRATES:
            raise ValueError(
                f"AC-3 bitrate must be one of {', '.join(f'{b}k' for b in AC3_BITRATES)}"
            )
        return v


class Subtitle(Strict):
    file: str | None = None
    track: int | None = Field(None, ge=0, description="stream index of an embedded subtitle")
    lang: Lang
    style: str = "varsayilan"
    default: bool = False
    forced: bool = False

    @model_validator(mode="after")
    def _one_source(self) -> Subtitle:
        if (self.file is None) == (self.track is None):
            raise ValueError("give either 'file' or 'track' for a subtitle, not both")
        return self


class ChapterEvery(Strict):
    every: float = Field(gt=0, description="minutes between chapters")


Chapters = Literal["from-source", "none"] | ChapterEvery | list[str]


class Title(Strict):
    source: str = Field(min_length=1)
    video: Video = Field(default_factory=Video)
    audio: list[Audio] = Field(default_factory=list, max_length=MAX_AUDIO_TRACKS)
    subtitles: list[Subtitle] = Field(default_factory=list, max_length=MAX_SUBTITLE_TRACKS)
    chapters: Chapters = "from-source"

    @field_validator("chapters")
    @classmethod
    def _chapter_list(cls, v: Chapters) -> Chapters:
        if isinstance(v, list):
            if len(v) > MAX_CHAPTERS:
                raise ValueError(f"at most {MAX_CHAPTERS} chapters per title")
            times = [parse_timecode(t) for t in v]
            if times != sorted(set(times)):
                raise ValueError("chapter times must be in increasing order without repeats")
        return v

    @model_validator(mode="after")
    def _single_defaults(self) -> Title:
        if sum(a.default for a in self.audio) > 1:
            raise ValueError("only one audio track can be the default")
        if sum(s.default for s in self.subtitles) > 1:
            raise ValueError("only one subtitle track can be the default")
        return self


MAX_MENU_BUTTONS = 36  # per menu page (DVD-Video)
PageKind = Literal["main", "chapters", "languages", "audio", "subtitles", "custom"]


class MenuAction(Strict):
    """What a button does: play a title (from a chapter), open a menu page, or pick an audio /
    subtitle stream (and return to the page). `stream: null` with `do: subtitle` turns
    subtitles off."""

    do: Literal["play", "page", "audio", "subtitle"]
    title: int = Field(1, ge=1, le=MAX_TITLES)
    chapter: int = Field(1, ge=1, le=MAX_CHAPTERS)
    page: str | None = None
    stream: int | None = Field(None, ge=0, le=MAX_SUBTITLE_TRACKS - 1)

    @model_validator(mode="after")
    def _needed_fields(self) -> MenuAction:
        if self.do == "page" and not self.page:
            raise ValueError("a 'page' action needs the page id")
        if self.do == "audio" and self.stream is None:
            raise ValueError("an 'audio' action needs the stream number")
        return self


class MenuButton(Strict):
    id: str = Field(pattern=r"^[a-z0-9_-]{1,32}$")
    label: str = Field(min_length=1, max_length=60)
    action: MenuAction
    # Position as fractions of the frame (0..1); left out, the template places the button.
    rect: tuple[float, float, float, float] | None = None
    up: str | None = None
    down: str | None = None
    left: str | None = None
    right: str | None = None


class ButtonEdit(Strict):
    """A hand change to a generated button (menu editor): place, text, arrow targets."""

    rect: tuple[float, float, float, float] | None = None
    label: str | None = Field(None, min_length=1, max_length=60)
    up: str | None = None
    down: str | None = None
    left: str | None = None
    right: str | None = None

    @field_validator("rect")
    @classmethod
    def _inside(cls, v):
        if v is not None:
            x, y, w, h = v
            if w <= 0 or h <= 0 or x < 0 or y < 0 or x + w > 1.0001 or y + h > 1.0001:
                raise ValueError("a button must lie inside the frame")
        return v


class MenuPage(Strict):
    id: str = Field(pattern=r"^[a-z0-9_-]{1,32}$")
    kind: PageKind = "custom"
    title: str | None = Field(None, max_length=80)
    # Standard kinds fill their buttons from the project; custom pages list them here.
    buttons: list[MenuButton] = Field(default_factory=list, max_length=MAX_MENU_BUTTONS)
    # Menu editor changes to generated buttons, by button id (also for every chapter page).
    edits: dict[str, ButtonEdit] = Field(default_factory=dict)


class MenuBackground(Strict):
    frame: str | None = None  # timecode of a film frame, else...
    image: str | None = None  # ...a picture file, else a plain colour
    color: str = Field("#141414", pattern=r"^#[0-9a-fA-F]{6}$")

    @field_validator("frame")
    @classmethod
    def _frame(cls, v: str | None) -> str | None:
        if v is not None:
            parse_timecode(v)
        return v


PAGE_ALIASES = {"settings": "languages", "ayarlar": "languages", "ana": "main",
                "bolumler": "chapters"}  # fmt: skip


def _page(value: Any) -> Any:
    """A page may be written as just its kind: `pages: [main, chapters, settings]`."""
    if isinstance(value, str):
        kind = PAGE_ALIASES.get(value, value)
        if kind not in PageKind.__args__ or kind == "custom":
            raise ValueError(f"{value!r} is not a standard page; write custom pages in full")
        return {"id": value, "kind": kind}
    return value


def _standard_pages() -> list[MenuPage]:
    return [MenuPage(id="main", kind="main"), MenuPage(id="chapters", kind="chapters"),
            MenuPage(id="languages", kind="languages")]  # fmt: skip


class Menus(Strict):
    template: Literal["minimal", "sinematik", "2000ler"] = "minimal"
    background: MenuBackground = Field(default_factory=MenuBackground)
    logo: str | None = None  # picture drawn on the main page instead of the title text
    tmdb_id: int | None = None  # the film on themoviedb.org the pictures came from
    pages: list[Annotated[MenuPage, BeforeValidator(_page)]] = Field(
        default_factory=_standard_pages, min_length=1
    )
    first: str = "main"  # the page the disc opens on (and the remote's Menu key)

    @model_validator(mode="after")
    def _links(self) -> Menus:
        ids = [p.id for p in self.pages]
        if len(set(ids)) != len(ids):
            raise ValueError("menu page ids must be unique")
        if self.first not in ids:
            raise ValueError(f"first page {self.first!r} is not one of the pages")
        for page in self.pages:
            buttons = [b.id for b in page.buttons]
            if len(set(buttons)) != len(buttons):
                raise ValueError(f"button ids on page {page.id!r} must be unique")
            for b in page.buttons:
                if b.action.do == "page" and b.action.page not in ids:
                    raise ValueError(f"button {b.id!r} opens unknown page {b.action.page!r}")
                for direction in (b.up, b.down, b.left, b.right):
                    if direction is not None and direction not in buttons:
                        raise ValueError(f"button {b.id!r} points to unknown button {direction!r}")
        return self


class Intro(Strict):
    """A clip played once when the disc starts, before the menu (a logo, a warning)."""

    file: str = Field(min_length=1)


def _intro(value: Any) -> Any:
    """`first_play` may be written as in the docs: `[{intro: logo.mkv}, main_menu]`."""
    if isinstance(value, dict) and "intro" in value:
        return {"file": value["intro"]}
    return value


def _first_play(value: Any) -> Any:
    if isinstance(value, list):  # the menu always follows the intros; its marker is optional
        return [v for v in value if v not in ("main_menu", "menu")]
    return value


FirstPlay = Annotated[list[Annotated[Intro, BeforeValidator(_intro)]], BeforeValidator(_first_play)]


class Project(Strict):
    version: Literal[1] = 1
    disc: Disc
    titles: list[Title] = Field(min_length=1, max_length=MAX_TITLES)
    menus: Menus | None = None  # None: the disc starts playing, no menus
    first_play: FirstPlay = Field(default_factory=list, max_length=8)
    # After the last title: back to the menu (or stop without menus), stop, or play again.
    at_end: Literal["menu", "stop", "repeat"] = "menu"
