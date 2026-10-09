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


class Project(Strict):
    version: Literal[1] = 1
    disc: Disc
    titles: list[Title] = Field(min_length=1, max_length=MAX_TITLES)
    # Not modelled until Phase 4; kept so hand-written files round-trip.
    menus: dict[str, Any] | None = None
    first_play: list[Any] | None = None
