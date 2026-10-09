"""Source analysis with ffprobe: video, audio and subtitle tracks, chapters."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field, replace
from fractions import Fraction
from pathlib import Path
from typing import Any

from dvd import toolchain

INTERLACED_FIELD_ORDERS = {"tt", "bb", "tb", "bt"}
HDR_TRANSFERS = {"smpte2084", "arib-std-b67"}
TEXT_SUBTITLE_CODECS = {"subrip", "srt", "ass", "ssa", "mov_text", "webvtt", "text"}
BITMAP_SUBTITLE_CODECS = {"hdmv_pgs_subtitle", "dvd_subtitle", "dvb_subtitle", "xsub"}


class ProbeError(Exception):
    pass


STANDARD_RATES = tuple(Fraction(n, d) for n, d in (
    (24000, 1001), (24, 1), (25, 1), (30000, 1001), (30, 1), (50, 1), (60000, 1001), (60, 1),
))  # fmt: skip


@dataclass(frozen=True)
class VideoTrack:
    index: int
    codec: str
    width: int
    height: int
    sar: Fraction
    fps: Fraction | None
    avg_fps: Fraction | None
    pix_fmt: str | None = None
    bit_depth: int = 8
    field_order: str | None = None
    color_primaries: str | None = None
    color_transfer: str | None = None
    color_matrix: str | None = None
    color_range: str | None = None
    dolby_vision: bool = False
    rotation: int = 0  # display rotation; width/height above are already the displayed ones
    hdr_peak: float | None = None  # nits: MaxCLL, else mastering display maximum
    start_time: float = 0.0  # seconds

    @property
    def dar(self) -> Fraction:
        return Fraction(self.width, self.height) * self.sar

    @property
    def interlaced(self) -> bool:
        return self.field_order in INTERLACED_FIELD_ORDERS

    @property
    def hdr(self) -> bool:
        return self.color_transfer in HDR_TRANSFERS or self.dolby_vision

    @property
    def portrait(self) -> bool:
        return self.dar < 1

    @property
    def maybe_vfr(self) -> bool:
        """Nominal and average frame rates differ by more than 0.1%: typical of phone videos.

        A real check needs the frame timestamps; this flag only says that one is worth doing.
        """
        if not self.fps or not self.avg_fps:
            return False
        return abs(self.fps - self.avg_fps) / self.fps > Fraction(1, 1000)

    @property
    def playback_fps(self) -> Fraction | None:
        """The constant rate the title is planned at: the nominal rate, or for variable frame
        rate sources the average, snapped to the nearest standard rate within 10%."""
        rate = self.avg_fps if self.maybe_vfr and self.avg_fps else self.fps
        if not rate:
            return None
        nearest = min(STANDARD_RATES, key=lambda r: abs(r - rate) / r)
        return nearest if abs(nearest - rate) / nearest < Fraction(1, 10) else rate


@dataclass(frozen=True)
class AudioTrack:
    index: int
    codec: str
    channels: int
    channel_layout: str | None = None
    sample_rate: int | None = None
    bitrate: int | None = None
    profile: str | None = None
    language: str | None = None
    title: str | None = None
    default: bool = False
    forced: bool = False
    start_time: float = 0.0  # seconds; differs from the video's when the file has an offset


@dataclass(frozen=True)
class SubtitleTrack:
    index: int
    codec: str
    language: str | None = None
    title: str | None = None
    default: bool = False
    forced: bool = False

    @property
    def kind(self) -> str:
        if self.codec in TEXT_SUBTITLE_CODECS:
            return "text"
        if self.codec in BITMAP_SUBTITLE_CODECS:
            return "bitmap"
        return "unknown"


@dataclass(frozen=True)
class Chapter:
    start: float
    end: float
    title: str | None = None


@dataclass(frozen=True)
class SourceInfo:
    path: Path
    container: str
    duration: float | None
    size: int | None
    bitrate: int | None = None
    title: str | None = None
    video: list[VideoTrack] = field(default_factory=list)
    audio: list[AudioTrack] = field(default_factory=list)
    subtitles: list[SubtitleTrack] = field(default_factory=list)
    chapters: list[Chapter] = field(default_factory=list)

    @property
    def main_video(self) -> VideoTrack | None:
        return self.video[0] if self.video else None


def _fraction(value: Any) -> Fraction | None:
    if not value or value in ("N/A", "0/0"):
        return None
    try:
        sep = ":" if ":" in str(value) else "/"
        num, den = (int(x) for x in str(value).split(sep))
    except ValueError:
        return None
    return Fraction(num, den) if num and den else None


def _int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _tag(stream: dict[str, Any], name: str) -> str | None:
    tags = {k.lower(): v for k, v in (stream.get("tags") or {}).items()}
    value = tags.get(name)
    return value if value not in (None, "", "und") else None


def _flag(stream: dict[str, Any], name: str) -> bool:
    return bool((stream.get("disposition") or {}).get(name))


def _bit_depth(stream: dict[str, Any]) -> int:
    depth = _int(stream.get("bits_per_raw_sample"))
    if depth:
        return depth
    pix_fmt = stream.get("pix_fmt") or ""
    for bits in (16, 12, 10):
        if f"p{bits}" in pix_fmt:
            return bits
    return 8


def _rotation(s: dict[str, Any]) -> int:
    for d in s.get("side_data_list") or []:
        if "rotation" in d:
            return round(float(d["rotation"])) % 360
    rotate = (s.get("tags") or {}).get("rotate")
    return round(float(rotate)) % 360 if rotate else 0


def _hdr_peak(side_data: list[dict[str, Any]]) -> float | None:
    cll = next((d.get("max_content") for d in side_data if "max_content" in d), None)
    if cll:
        return float(cll)
    mastering = next((d.get("max_luminance") for d in side_data if "max_luminance" in d), None)
    value = _fraction(mastering) if mastering else None
    return float(value) if value else None


def _video(s: dict[str, Any]) -> VideoTrack:
    side_data = s.get("side_data_list") or []
    width, height = s.get("width", 0), s.get("height", 0)
    sar = _fraction(s.get("sample_aspect_ratio")) or Fraction(1)
    rotation = _rotation(s)
    if rotation in (90, 270):  # phones store portrait video as landscape plus a rotation
        width, height, sar = height, width, 1 / sar
    return VideoTrack(
        index=s["index"],
        codec=s.get("codec_name", "unknown"),
        width=width,
        height=height,
        sar=sar,
        fps=_fraction(s.get("r_frame_rate")),
        avg_fps=_fraction(s.get("avg_frame_rate")),
        pix_fmt=s.get("pix_fmt"),
        bit_depth=_bit_depth(s),
        field_order=s.get("field_order"),
        color_primaries=s.get("color_primaries"),
        color_transfer=s.get("color_transfer"),
        color_matrix=s.get("color_space"),
        color_range=s.get("color_range"),
        dolby_vision=any("DOVI" in (d.get("side_data_type") or "") for d in side_data),
        rotation=rotation,
        hdr_peak=_hdr_peak(side_data),
        start_time=_float(s.get("start_time")) or 0.0,
    )


def _audio(s: dict[str, Any]) -> AudioTrack:
    return AudioTrack(
        index=s["index"],
        codec=s.get("codec_name", "unknown"),
        channels=s.get("channels", 0),
        channel_layout=s.get("channel_layout"),
        sample_rate=_int(s.get("sample_rate")),
        bitrate=_int(s.get("bit_rate")),
        profile=s.get("profile"),
        language=_tag(s, "language"),
        title=_tag(s, "title"),
        default=_flag(s, "default"),
        forced=_flag(s, "forced"),
        start_time=_float(s.get("start_time")) or 0.0,
    )


def _subtitle(s: dict[str, Any]) -> SubtitleTrack:
    return SubtitleTrack(
        index=s["index"],
        codec=s.get("codec_name", "unknown"),
        language=_tag(s, "language"),
        title=_tag(s, "title"),
        default=_flag(s, "default"),
        forced=_flag(s, "forced"),
    )


def parse(data: dict[str, Any], path: Path) -> SourceInfo:
    """Build a SourceInfo from ffprobe's JSON (-show_format -show_streams -show_chapters)."""
    fmt = data.get("format") or {}
    streams = data.get("streams") or []
    video = [
        _video(s)
        for s in streams
        if s.get("codec_type") == "video" and not _flag(s, "attached_pic")
    ]
    return SourceInfo(
        path=path,
        container=fmt.get("format_name", "unknown"),
        duration=_float(fmt.get("duration")),
        size=_int(fmt.get("size")),
        bitrate=_int(fmt.get("bit_rate")),
        title=_tag(fmt, "title"),
        video=video,
        audio=[_audio(s) for s in streams if s.get("codec_type") == "audio"],
        subtitles=[_subtitle(s) for s in streams if s.get("codec_type") == "subtitle"],
        chapters=[
            Chapter(
                start=_float(c.get("start_time")) or 0.0,
                end=_float(c.get("end_time")) or 0.0,
                title=_tag(c, "title"),
            )
            for c in data.get("chapters") or []
        ],
    )


def probe(path: Path | str, ffprobe: Path | None = None) -> SourceInfo:
    path = Path(path)
    if not path.is_file():
        raise ProbeError(f"file not found: {path}")
    ffprobe = ffprobe or toolchain.find_executable(
        ["ffprobe.exe", "ffprobe"], toolchain.tool_dirs()
    )
    if ffprobe is None:
        raise ProbeError("ffprobe not found")
    proc = subprocess.run(
        [
            str(ffprobe),
            "-v", "error",
            "-print_format", "json",
            "-show_format", "-show_streams", "-show_chapters",
            str(path),
        ],
        capture_output=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )  # fmt: skip
    if proc.returncode != 0:
        message = proc.stderr.decode("utf-8", errors="replace").strip()
        raise ProbeError(f"ffprobe failed for {path}: {message}")
    info = parse(json.loads(proc.stdout.decode("utf-8", errors="replace")), path)
    v = info.main_video
    if v is not None and v.hdr and v.hdr_peak is None:
        # HEVC carries MaxCLL and the mastering display in SEI: look at the first frame.
        peak = _first_frame_peak(ffprobe, path, v.index)
        if peak:
            info.video[info.video.index(v)] = replace(v, hdr_peak=peak)
    return info


def _first_frame_peak(ffprobe: Path, path: Path, index: int) -> float | None:
    proc = subprocess.run(
        [str(ffprobe), "-v", "error", "-print_format", "json", "-select_streams", str(index),
         "-read_intervals", "%+#1", "-show_entries", "frame=side_data_list:side_data",
         str(path)],
        capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )  # fmt: skip
    if proc.returncode != 0:
        return None
    data = json.loads(proc.stdout.decode("utf-8", errors="replace"))
    items = data.get("frames") or data.get("packets_and_frames") or []
    frames = [i for i in items if i.get("type", "frame") == "frame"]
    return _hdr_peak(frames[0].get("side_data_list") or []) if frames else None
