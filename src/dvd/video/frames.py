"""A few frames at a time, fast: FFmpeg seeks to the nearest keyframe and decodes from there.

The full pipeline opens sources with BestSource, which indexes the whole file first (frame
exact, but on a 20 GB Blu-ray that is close to decoding the film once). Previews, crop
detection and menu pictures only need a handful of frames, so they take them this way and
run them through the same VapourSynth steps as the build.
"""

from __future__ import annotations

import subprocess
from fractions import Fraction
from pathlib import Path

import numpy as np
import vapoursynth as vs

from dvd import toolchain
from dvd.probe import VideoTrack

core = vs.core
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class FrameError(RuntimeError):
    pass


def _layout(v: VideoTrack) -> tuple[str, vs.VideoFormat, int]:
    """FFmpeg pixel format, the matching VapourSynth format, bytes per sample."""
    pix = v.pix_fmt or "yuv420p"
    sub = "444" if "444" in pix else "422" if "422" in pix else "420"
    bits = 8 if v.bit_depth <= 8 else 10 if v.bit_depth <= 10 else 16
    ff = f"yuv{sub}p" + ("" if bits == 8 else f"{bits}le")
    ssw, ssh = {"444": (0, 0), "422": (1, 0), "420": (1, 1)}[sub]
    return ff, core.query_video_format(vs.YUV, vs.INTEGER, bits, ssw, ssh), 1 if bits == 8 else 2


def grab(source: Path, v: VideoTrack, at: float, count: int = 1) -> vs.VideoNode:
    """`count` consecutive frames from `at` seconds into the file, as a clip at the source's
    size and rate (rotation applied, as BestSource does)."""
    ffmpeg = toolchain.find_executable(["ffmpeg.exe", "ffmpeg"], toolchain.tool_dirs())
    if ffmpeg is None:
        raise FrameError("ffmpeg not found; run `dvd doctor`")
    pix, fmt, size = _layout(v)
    w, h = v.width, v.height
    planes = [(w, h)] + [(w >> fmt.subsampling_w, h >> fmt.subsampling_h)] * 2
    frame_bytes = sum(pw * ph for pw, ph in planes) * size
    proc = subprocess.run(
        [str(ffmpeg), "-v", "error", "-nostdin", "-ss", f"{max(0.0, at):.3f}", "-i", str(source),
         "-map", f"0:{v.index}", "-frames:v", str(count), "-an", "-sn", "-vf", f"scale={w}:{h}",
         "-f", "rawvideo", "-pix_fmt", pix, "-"],
        capture_output=True, creationflags=_NO_WINDOW,
    )  # fmt: skip
    data = proc.stdout
    got = len(data) // frame_bytes
    if got == 0:
        if at > 1:  # past the end (a container that overstates its length): step back
            return grab(source, v, at - 1, count)
        raise FrameError(proc.stderr.decode("utf-8", "replace").strip() or "no frame decoded")
    dtype = np.uint8 if size == 1 else np.dtype("<u2")
    frames = []
    for k in range(count):
        chunk = data[min(k, got - 1) * frame_bytes : (min(k, got - 1) + 1) * frame_bytes]
        arrays, pos = [], 0
        for pw, ph in planes:
            n = pw * ph * size
            arrays.append(np.frombuffer(chunk[pos : pos + n], dtype).reshape(ph, pw))
            pos += n
        frames.append(arrays)

    def fill(n, f):
        out = f.copy()
        for i, a in enumerate(frames[n]):
            np.asarray(out[i])[:] = a
        return out

    rate = v.playback_fps or v.fps or Fraction(25)
    blank = core.std.BlankClip(width=w, height=h, format=fmt.id, length=count,
                               fpsnum=rate.numerator, fpsden=rate.denominator)  # fmt: skip
    return core.std.ModifyFrame(blank, blank, fill)
