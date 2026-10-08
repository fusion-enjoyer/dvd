"""Bitrate planner v0: share the disc between video, audio and subtitles (docs/kalite.md §4)."""

from __future__ import annotations

from dataclasses import dataclass, field

CAPACITY = {"dvd5": 4_700_372_992, "dvd9": 8_543_666_176}  # bytes
OVERHEAD = 0.03  # mux packs, navigation, IFOs, file system
MUX_LIMIT = 10_080  # kbit/s, all streams together
VIDEO_LIMIT = 9_800  # kbit/s
SUBTITLE_KBPS = 10  # rough average for a subpicture stream
AVERAGE_HEADROOM = 1_000  # VBR needs room between average and peak
LOW_QUALITY_BELOW = 4_000  # kbit/s average video
# Peak video bitrate by viewing profile (docs/profiller.md); older players dislike high peaks.
PEAK_BY_VIEWING = {
    "modern-tv": 9_000, "projeksiyon": 9_000, "crt": 9_000, "bilgisayar": 9_500,
    "konsol": 8_000, "tasinabilir": 7_500, "evrensel": 8_000,
}  # fmt: skip


@dataclass(frozen=True)
class Plan:
    media: str
    duration: float  # seconds of playback, after PAL speedup
    video_kbps: int
    peak_kbps: int
    audio_kbps: int
    subtitle_kbps: int
    capacity_bytes: int
    estimated_bytes: int
    warnings: list[str] = field(default_factory=list)

    @property
    def fits(self) -> bool:
        return self.estimated_bytes <= self.capacity_bytes


def plan(
    media: str,
    duration: float,
    audio_kbps: list[int],
    subtitle_tracks: int = 0,
    viewing: str = "modern-tv",
) -> Plan:
    if duration <= 0:
        raise ValueError("duration must be positive")
    capacity = CAPACITY[media]
    audio = sum(audio_kbps)
    subs = subtitle_tracks * SUBTITLE_KBPS
    total = capacity * 8 * (1 - OVERHEAD) / duration / 1000
    peak = min(PEAK_BY_VIEWING.get(viewing, 9_000), VIDEO_LIMIT, MUX_LIMIT - audio - subs)
    video = int(min(total - audio - subs, peak - AVERAGE_HEADROOM))

    warnings = []
    if video < LOW_QUALITY_BELOW:
        warnings.append(
            f"average video bitrate {video / 1000:.1f} Mbps is low; "
            + ("use fewer or smaller audio tracks" if media == "dvd9" else "consider DVD-9")
        )
    estimated = int((video + audio + subs) * 1000 * duration / 8 / (1 - OVERHEAD))
    if video <= 0:
        warnings.append("audio and subtitles alone do not fit on the disc")
    return Plan(media, duration, video, peak, audio, subs, capacity, estimated, warnings)
