"""AC-3 for one disc audio track, with FFmpeg: 48 kHz, DVD channel layouts, PAL speedup.

What happens to a source track:
  - an AC-3 track that already fits DVD (48 kHz, at most 448 kbit/s, same channel count) and
    needs no retiming, delay or compression is copied bit for bit;
  - otherwise it is re-encoded. Stereo made from a multichannel source uses a Dolby Pro Logic II
    matrix (surrounds in antiphase), so a Pro Logic receiver can still steer them to the rear;
  - night mode compresses the dynamic range so dialogue and explosions sit closer together;
  - a delay (ms) moves the track: positive plays it later (silence in front), negative cuts
    its start. The build adds the source's own audio/video start offset to it.
"""

from __future__ import annotations

import subprocess
from fractions import Fraction
from pathlib import Path

from dvd import toolchain
from dvd.probe import AudioTrack

MAX_AC3_KBPS = 448
NIGHT = "acompressor=threshold=0.1:ratio=4:attack=10:release=250:makeup=2"  # -20 dB knee


class AudioError(Exception):
    pass


def can_copy(
    track: AudioTrack,
    channels: str,
    speedup: Fraction = Fraction(1),
    delay_ms: float = 0.0,
    night: bool = False,
) -> bool:
    """The source track can go on the disc unchanged."""
    return (
        track.codec == "ac3"
        and track.sample_rate == 48000
        and (track.bitrate or 0) <= MAX_AC3_KBPS * 1000
        and track.channels == (6 if channels == "5.1" else 2)
        and speedup == 1
        and abs(delay_ms) < 1
        and not night
    )


def ffmpeg_args(
    source: Path,
    stream_index: int,
    out: Path,
    channels: str,
    bitrate: int,
    speedup: Fraction = Fraction(1),
    pitch: str = "keep",
    *,
    delay_ms: float = 0.0,
    night: bool = False,
    source_channels: int = 0,
    copy: bool = False,
) -> list[str]:
    head = ["-v", "error", "-y", "-i", str(source), "-map", f"0:{stream_index}",
            "-vn", "-sn", "-dn"]  # fmt: skip
    if copy:
        return [*head, "-c:a", "copy", "-f", "ac3", str(out)]
    filters = []
    if delay_ms >= 1:
        filters.append(f"adelay=delays={delay_ms:.0f}:all=1")
    elif delay_ms <= -1:
        filters.append(f"atrim=start={-delay_ms / 1000:.3f},asetpts=PTS-STARTPTS")
    if speedup != 1 and pitch == "keep":
        # Keep the pitch: the film plays 4% faster on PAL but voices should not rise a semitone.
        filters.append(f"atempo={float(speedup):.10f}")
    elif speedup != 1:
        # Like most commercial PAL discs: play the samples faster, pitch rises with the speed.
        # 48000 * 25025/24000 = 50050 exactly; resample to 48 kHz on both sides.
        rate = 48000 * speedup
        filters += ["aresample=48000", f"asetrate={float(rate):.4f}", "aresample=48000"]
    downmix = channels == "2.0" and source_channels > 2
    if downmix:
        filters.append("aresample=matrix_encoding=dplii:ochl=stereo")
    if night:
        filters.append(NIGHT)
    args = [
        *head,
        "-c:a", "ac3", "-b:a", f"{bitrate}k",
        "-ac", "6" if channels == "5.1" else "2",
        "-ar", "48000",
    ]  # fmt: skip
    if downmix:
        args += ["-dsur_mode", "on"]  # tells the receiver the stereo is surround-encoded
    if filters:
        args += ["-af", ",".join(filters)]
    return [*args, str(out)]


def encode_ac3(
    source: Path,
    stream_index: int,
    out: Path,
    channels: str,
    bitrate: int,
    speedup: Fraction = Fraction(1),
    pitch: str = "keep",
    ffmpeg: Path | None = None,
    *,
    delay_ms: float = 0.0,
    night: bool = False,
    source_channels: int = 0,
    copy: bool = False,
) -> Path:
    ffmpeg = ffmpeg or toolchain.find_executable(["ffmpeg.exe", "ffmpeg"], toolchain.tool_dirs())
    if ffmpeg is None:
        raise AudioError("ffmpeg not found")
    out.parent.mkdir(parents=True, exist_ok=True)
    args = ffmpeg_args(source, stream_index, out, channels, bitrate, speedup, pitch,
                       delay_ms=delay_ms, night=night, source_channels=source_channels,
                       copy=copy)  # fmt: skip
    proc = subprocess.run(
        [str(ffmpeg), *args],
        capture_output=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if proc.returncode != 0 or not out.is_file():
        message = proc.stderr.decode("utf-8", errors="replace").strip()
        raise AudioError(f"AC-3 encode of stream {stream_index} failed: {message}")
    return out
