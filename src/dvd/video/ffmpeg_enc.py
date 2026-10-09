"""FFmpeg MPEG-2 encode: the second encoder, for when HCEnc is missing and for comparisons.

Frames go from VapourSynth to ffmpeg as y4m on stdin; two passes render the clip twice.
DVD details FFmpeg does not do by default:
  - progressive_sequence must be 0: `+ildct` lets frames use field DCT, which also clears the
    sequence flag, while progressive input keeps progressive_frame = 1;
  - closed GOPs (`+cgop`, which FFmpeg only allows without scene-change detection) and
    forced key frames at chapter frames;
  - VBV: 224 KiB buffer, peak from the plan, GOP 15 (PAL) / 18 (NTSC), at most 2 B-frames.
NTSC film is encoded as 23.976 fps progressive (no field DCT; GOP 12 film frames = 15 video
frames) and gets its soft pulldown flags afterwards from `pulldown.inject`.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

import vapoursynth as vs

from dvd import toolchain
from dvd.video import pulldown
from dvd.video.hcenc import EncodeError, EncodeSettings

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def ffmpeg_args(settings: EncodeSettings, fps: float, passlog: Path, pass_no: int) -> list[str]:
    s = settings
    pal = s.standard == "pal"
    args = [
        "-v", "error", "-y", "-f", "yuv4mpegpipe", "-i", "-",
        "-c:v", "mpeg2video", "-pix_fmt", "yuv420p",
        "-b:v", f"{s.bitrate}k", "-maxrate", f"{s.maxrate}k", "-minrate", "0",
        "-bufsize", "1835k", "-rc_init_occupancy", "1835k",
        "-g", "15" if pal else "12" if s.pulldown else "18", "-bf", "2",
        "-mpv_flags", "+strict_gop", "-sc_threshold", "1000000000",
        # +ildct clears progressive_sequence; pulldown streams stay progressive until inject.
        "-flags", "+cgop" if s.pulldown else "+ildct+cgop",
        "-dc", "10", "-intra_vlc", "1", "-non_linear_quant", "1",
        "-mbd", "rd", "-trellis", "2", "-cmp", "2", "-subcmp", "2", "-qmin", "1", "-qmax", "28",
        "-aspect", s.aspect, "-seq_disp_ext", "1", "-video_format", "1" if pal else "2",
        "-color_primaries", "bt470bg" if pal else "smpte170m",
        "-color_trc", "gamma28" if pal else "smpte170m",
        "-colorspace", "bt470bg" if pal else "smpte170m",
        "-pass", str(pass_no), "-passlogfile", str(passlog),
    ]  # fmt: skip
    chapters = sorted({c for c in s.chapters if c > 0})
    if chapters:
        args += ["-force_key_frames", ",".join(f"{c / fps:.6f}" for c in chapters)]
    return args


def encode(
    clip: vs.VideoNode,
    out: Path,
    settings: EncodeSettings,
    workdir: Path,
    progress: Callable[[float], None] | None = None,
    ffmpeg: Path | None = None,
) -> Path:
    ffmpeg = ffmpeg or toolchain.find_executable(["ffmpeg.exe", "ffmpeg"], toolchain.tool_dirs())
    if ffmpeg is None:
        raise EncodeError("ffmpeg not found")
    workdir.mkdir(parents=True, exist_ok=True)
    out.parent.mkdir(parents=True, exist_ok=True)
    passlog, log = workdir / "ffpass", workdir / "ffmpeg.log"
    fps = float(clip.fps)
    total = 2 * clip.num_frames
    for pass_no, target in ((1, "NUL"), (2, str(out))):
        fmt = ["-f", "null"] if pass_no == 1 else ["-f", "mpeg2video"]
        args = [str(ffmpeg), *ffmpeg_args(settings, fps, passlog, pass_no), *fmt, target]
        with log.open("ab") as err:
            proc = subprocess.Popen(args, stdin=subprocess.PIPE, stderr=err,
                                    creationflags=_NO_WINDOW)  # fmt: skip
            done = (pass_no - 1) * clip.num_frames

            def update(current: int, _total: int, done: int = done) -> None:
                if progress:
                    progress((done + current) / total)

            try:
                clip.output(proc.stdin, y4m=True, progress_update=update)
            except (BrokenPipeError, OSError):
                pass  # ffmpeg exited; its log says why
            finally:
                proc.stdin.close()
            proc.wait()
        if proc.returncode != 0:
            tail = log.read_text(encoding="utf-8", errors="replace")[-1500:]
            raise EncodeError(f"ffmpeg pass {pass_no} failed:\n{tail}")
    if settings.pulldown:
        try:
            pulldown.inject(out)
        except pulldown.PulldownError as e:
            raise EncodeError(f"soft pulldown failed: {e}") from e
    if progress:
        progress(1.0)
    return out
