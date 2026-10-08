"""Human-readable and JSON views of a SourceInfo."""

from __future__ import annotations

import dataclasses
from fractions import Fraction
from pathlib import Path
from typing import Any

from dvd.probe.source import AudioTrack, SourceInfo, SubtitleTrack, VideoTrack


def timecode(seconds: float | None) -> str:
    if seconds is None:
        return "?"
    s = int(seconds)
    return f"{s // 3600}:{s % 3600 // 60:02}:{s % 60:02}"


def fps_text(fps: Fraction | None) -> str:
    if fps is None:
        return "? fps"
    return f"{float(fps):.3f}".rstrip("0").rstrip(".") + " fps"


def size_text(size: int | None) -> str:
    if size is None:
        return "?"
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return "?"


def _ratio(r: Fraction) -> str:
    for name, value in (("16:9", Fraction(16, 9)), ("4:3", Fraction(4, 3))):
        if abs(r - value) < Fraction(1, 100):
            return name
    return f"{float(r):.2f}:1"


def _video_line(v: VideoTrack) -> str:
    parts = [
        f"#{v.index}", v.codec, f"{v.width}x{v.height}", _ratio(v.dar), fps_text(v.fps),
        "interlaced" if v.interlaced else (v.field_order or "scan ?"),
        v.color_matrix or "matrix ?", f"{v.bit_depth}-bit",
    ]  # fmt: skip
    if v.hdr:
        parts.append("Dolby Vision" if v.dolby_vision else f"HDR ({v.color_transfer})")
    return " ".join(parts)


def _audio_line(a: AudioTrack) -> str:
    codec = f"{a.codec} ({a.profile})" if a.profile else a.codec
    parts = [f"#{a.index}", codec, f"{a.channels}ch"]
    if a.channel_layout:
        parts.append(a.channel_layout)
    if a.sample_rate:
        parts.append(f"{a.sample_rate / 1000:g} kHz")
    parts.append(a.language or "und")
    if a.title:
        parts.append(f'"{a.title}"')
    parts += [flag for flag, on in (("default", a.default), ("forced", a.forced)) if on]
    return " ".join(parts)


def _subtitle_line(s: SubtitleTrack) -> str:
    parts = [f"#{s.index}", s.codec, s.kind, s.language or "und"]
    if s.title:
        parts.append(f'"{s.title}"')
    parts += [flag for flag, on in (("default", s.default), ("forced", s.forced)) if on]
    return " ".join(parts)


def notes(info: SourceInfo) -> list[str]:
    """Things about the source that change how it must be converted."""
    v = info.main_video
    if v is None:
        return ["no video track"]
    out = []
    if v.hdr:
        out.append("HDR source: needs tone mapping to SDR")
    if v.interlaced:
        out.append("interlaced: deinterlace or encode interlaced")
    if v.maybe_vfr:
        out.append("frame rate may be variable: check timestamps, convert to constant")
    if v.portrait:
        out.append("portrait video: needs a layout choice (blurred or black sides)")
    if v.bit_depth > 8:
        out.append(f"{v.bit_depth}-bit source: dither down to 8-bit")
    return out


def summary(info: SourceInfo) -> str:
    head = (
        f"{info.path.name}  ({info.container}, {timecode(info.duration)}, {size_text(info.size)})"
    )
    if info.title:
        head += f'  "{info.title}"'
    lines = [head]

    def section(label: str, items: list[str]) -> None:
        for i, item in enumerate(items):
            lines.append(f"{label if i == 0 else '':<9}{item}")

    section("Video", [_video_line(v) for v in info.video] or ["-"])
    section("Audio", [_audio_line(a) for a in info.audio] or ["-"])
    section("Subs", [_subtitle_line(s) for s in info.subtitles] or ["-"])
    section(
        "Chapters",
        [f"{timecode(c.start)} {c.title or ''}".rstrip() for c in info.chapters] or ["-"],
    )
    section("Notes", notes(info))
    return "\n".join(lines)


def _jsonable(value: Any) -> Any:
    if isinstance(value, Fraction):
        return f"{value.numerator}/{value.denominator}"
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    return value


def to_json(info: SourceInfo) -> dict[str, Any]:
    return _jsonable(dataclasses.asdict(info))
