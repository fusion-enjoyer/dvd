"""Moving menu backgrounds: a stretch of the film plays behind the page and loops.

The page (title, labels, layers, shading) is drawn without a backdrop and laid over every
frame of the stretch; the result is encoded like a short title, with the film's sound for
the same stretch (faded out at the end), and gets its buttons from spumux like a still menu.
"""

from __future__ import annotations

import subprocess
from fractions import Fraction
from pathlib import Path

import numpy as np
import vapoursynth as vs
from PySide6.QtGui import QImage

from dvd import toolchain
from dvd.author.dvdauthor import AuthorError, mux
from dvd.probe import SourceInfo
from dvd.project.model import Crop
from dvd.video import encoders
from dvd.video.hcenc import EncodeSettings
from dvd.video.pipeline import FILM_RATES, NTSC_RATE, PAL_RATE, open_source, scale_to_sd

core = vs.core
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
VIDEO_KBPS, PEAK_KBPS = 6_000, 8_000


def _close(a: Fraction, b: Fraction) -> bool:
    return abs(a - b) < Fraction(1, 100)


def _cover_crop(width: int, height: int, sar: Fraction, aspect: Fraction, crop: Crop) -> Crop:
    """More crop, so what is left has the menu's display shape (fills it, no bars). Every
    side stays even, as 4:2:0 needs."""
    w = width - crop.left - crop.right
    h = height - crop.top - crop.bottom
    if Fraction(w, h) * sar > aspect:  # wider: cut the sides
        cut = w - int(h * aspect / sar) // 2 * 2
        a = cut // 2 // 2 * 2
        return Crop(left=crop.left + a, right=crop.right + cut - a, top=crop.top,
                    bottom=crop.bottom)  # fmt: skip
    cut = h - int(w * sar / aspect) // 2 * 2
    a = cut // 2 // 2 * 2
    return Crop(left=crop.left, right=crop.right, top=crop.top + a,
                bottom=crop.bottom + cut - a)  # fmt: skip


def _picture_clip(rgba: np.ndarray, matrix: str, length: int, fps: Fraction):
    """The page drawing as a YUV clip and its alpha as a mask, `length` frames long."""
    h, w, _ = rgba.shape
    rgb = core.std.BlankClip(width=w, height=h, format=vs.RGB24, length=1)
    alpha = core.std.BlankClip(width=w, height=h, format=vs.GRAY8, length=1)

    def fill_rgb(n, f):
        out = f.copy()
        for i in range(3):
            np.asarray(out[i])[:] = rgba[:, :, i]
        return out

    def fill_alpha(n, f):
        out = f.copy()
        np.asarray(out[0])[:] = rgba[:, :, 3]
        return out

    rgb = core.std.ModifyFrame(rgb, rgb, fill_rgb)
    alpha = core.std.ModifyFrame(alpha, alpha, fill_alpha)
    yuv = core.resize.Bicubic(rgb, format=vs.YUV420P16, matrix_s=matrix, range_s="limited")
    mask = core.resize.Point(alpha, format=vs.GRAY16)
    loop = lambda c: core.std.AssumeFPS(c * length, fpsnum=fps.numerator,  # noqa: E731
                                        fpsden=fps.denominator)  # fmt: skip
    return loop(yuv), loop(mask)


def motion_clip(source: Path, info: SourceInfo, start: float, seconds: float, standard: str,
                aspect: Fraction, overlay: QImage, crop: Crop | None = None,
                fade_in: bool = False) -> tuple[vs.VideoNode, bool, Fraction]:  # fmt: skip
    """The disc menu video: (clip, pulldown, speedup). Film runs 4 % fast on PAL (speedup)
    and with pulldown flags on NTSC; other rates take the nearest source frame. With
    `fade_in` the page appears gradually over the whole clip (the menu's intro)."""
    v = info.main_video
    if v is None:
        raise AuthorError(f"{source.name} has no video for a moving menu")
    clip = open_source(source, v)
    rate = Fraction(clip.fps_num, clip.fps_den)
    first = max(0, min(clip.num_frames - 1, round(start * rate)))
    piece = clip[first : min(clip.num_frames, first + round(seconds * rate))]
    c = _cover_crop(v.width, v.height, v.sar, aspect, crop or Crop())
    if any((c.left, c.right, c.top, c.bottom)):
        piece = core.std.Crop(piece, c.left, c.right, c.top, c.bottom)
    frame_h = 576 if standard == "pal" else 480
    matrix = "470bg" if standard == "pal" else "170m"
    piece = scale_to_sd(piece, v, 720, frame_h, "spline36", matrix, vs.YUV420P16)

    disc = PAL_RATE if standard == "pal" else NTSC_RATE
    film = any(_close(rate, r) for r in FILM_RATES)
    pulldown, speedup = False, Fraction(1)
    if film and standard == "pal":
        out_rate, speedup = PAL_RATE, PAL_RATE / rate
    elif film:
        out_rate, pulldown = Fraction(24000, 1001), True
    elif _close(rate, disc):
        out_rate = disc
    else:  # nearest source frame for each disc frame
        out_rate = disc
        count = int(piece.num_frames * disc / rate)
        picks = [min(piece.num_frames - 1, round(k * rate / disc)) for k in range(count)]
        piece = core.std.Splice([piece[i] for i in picks])
    piece = core.std.AssumeFPS(piece, fpsnum=out_rate.numerator, fpsden=out_rate.denominator)

    rgba = np.ascontiguousarray(_rgba(overlay))
    if rgba.shape[:2] != (frame_h, 720):
        raise AuthorError("the menu page and the moving background differ in size")
    page, mask = _picture_clip(rgba, matrix, piece.num_frames, out_rate)
    if fade_in:
        n = mask.num_frames
        mask = core.std.Splice([core.std.Expr(mask[k], f"x {(k + 1) / n:.5f} *") for k in range(n)])
    merged = core.std.MaskedMerge(piece, page, mask, first_plane=True)
    return core.resize.Point(merged, format=vs.YUV420P8, dither_type="error_diffusion"), \
        pulldown, speedup  # fmt: skip


def _rgba(image: QImage) -> np.ndarray:
    img = image.convertToFormat(QImage.Format.Format_RGBA8888)
    view = np.frombuffer(img.constBits(), np.uint8).reshape(img.height(), img.bytesPerLine())
    return view[:, : img.width() * 4].reshape(img.height(), img.width(), 4).copy()


def _audio(source: Path | None, info: SourceInfo | None, start: float, seconds: float,
           speedup: Fraction, out: Path, fade_out: bool = True) -> Path:  # fmt: skip
    """The film's sound for the stretch (silence without one), as the video's speed, faded
    out over the last second so the loop does not click (not for an intro, which runs on
    into the loop)."""
    ffmpeg = toolchain.find_executable(["ffmpeg.exe", "ffmpeg"], toolchain.tool_dirs())
    if ffmpeg is None:
        raise AuthorError("ffmpeg not found; run `dvd doctor`")
    length = seconds / float(speedup)
    fade = "afade=t=in:d=0.3"
    if fade_out:
        fade += f",afade=t=out:st={max(0.0, length - 1):.3f}:d=1"
    if source is not None and info is not None and info.audio:
        tempo = f"atempo={float(speedup):.6f}," if speedup != 1 else ""
        args = ["-ss", f"{start:.3f}", "-t", f"{seconds:.3f}", "-i", str(source),
                "-map", f"0:{info.audio[0].index}", "-af", tempo + fade]  # fmt: skip
    else:
        args = ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", f"{length:.3f}"]
    proc = subprocess.run(
        [str(ffmpeg), "-v", "error", "-y", *args, "-vn", "-ac", "2", "-ar", "48000",
         "-c:a", "ac3", "-b:a", "192k", str(out)],
        capture_output=True, creationflags=_NO_WINDOW,
    )  # fmt: skip
    if proc.returncode != 0:
        raise AuthorError("menu sound failed: " + proc.stderr.decode("utf-8", "replace")[-800:])
    return out


def motion_mpg(source: Path, info: SourceInfo, start: float, seconds: float, standard: str,
               aspect: Fraction, overlay: QImage, workdir: Path, name: str,
               encoder: str = "ffmpeg", crop: Crop | None = None,
               intro: bool = False) -> Path:  # fmt: skip
    """The moving background with the page drawn over it, encoded and muxed with sound:
    `workdir`/`name`.mpg, ready for the button subpicture. `intro`: the page fades in and
    the sound runs on (the part played once before the loop)."""
    workdir.mkdir(parents=True, exist_ok=True)
    clip, pulldown, speedup = motion_clip(source, info, start, seconds, standard, aspect,
                                          overlay, crop, fade_in=intro)  # fmt: skip
    settings = EncodeSettings(bitrate=VIDEO_KBPS, maxrate=PEAK_KBPS,
                              aspect="16:9" if aspect > Fraction(3, 2) else "4:3",
                              standard=standard, pulldown=pulldown)  # fmt: skip
    name_enc, _note = encoders.choose(encoder)
    m2v = encoders.encode(name_enc, clip, workdir / f"{name}.m2v", settings,
                          workdir / f"{name}_{name_enc}")  # fmt: skip
    ac3 = _audio(source, info, start, seconds, speedup, workdir / f"{name}.ac3",
                 fade_out=not intro)  # fmt: skip
    return mux(m2v, [ac3], workdir / f"{name}.mpg")


def _nearest_rate(piece: vs.VideoNode, rate: Fraction, disc: Fraction) -> vs.VideoNode:
    """The disc rate by taking the nearest source frame (no speedup, no pulldown)."""
    if not _close(rate, disc):
        count = int(piece.num_frames * disc / rate)
        picks = [min(piece.num_frames - 1, round(k * rate / disc)) for k in range(count)]
        piece = core.std.Splice([piece[i] for i in picks])
    return core.std.AssumeFPS(piece, fpsnum=disc.numerator, fpsden=disc.denominator)


def thumb_rects(page, frame: tuple[int, int, Fraction]) -> list[tuple[int, int, int, int]]:
    """Disc-pixel boxes (x, y, w, h, all even) of the pictures in a page's thumb buttons, as
    `render_page` draws them: 16:9 at display size, squeezed to the disc width."""
    fw, fh, aspect = frame
    dw = round(fh * aspect)
    out = []
    for b in page.buttons:
        if b.thumb is None:
            continue
        x, y, w, _h = b.rect
        width, height = w * fw, w * dw * 9 / 16
        out.append(tuple(int(v) // 2 * 2 for v in (x * fw, y * fh, width, height)))
    return out


def thumbs_mpg(base: QImage, clips: list[tuple[Path, SourceInfo, float, Crop]],
               rects: list[tuple[int, int, int, int]], seconds: float, standard: str,
               aspect: Fraction, workdir: Path, name: str,
               encoder: str = "ffmpeg") -> Path:  # fmt: skip
    """A page whose thumb pictures move: each (source, info, start, crop) plays `seconds`
    inside its box over the still page `base` (disc frame, RGB); silent, ready to loop."""
    workdir.mkdir(parents=True, exist_ok=True)
    frame_h = 576 if standard == "pal" else 480
    matrix = "470bg" if standard == "pal" else "170m"
    disc = PAL_RATE if standard == "pal" else NTSC_RATE
    count = max(1, round(seconds * disc))
    rgba = _rgba(base)
    rgba[:, :, 3] = 255
    out, _mask = _picture_clip(rgba, matrix, count, disc)
    for (source, info, start, crop), (x, y, w, h) in zip(clips, rects, strict=True):
        v = info.main_video
        if v is None or w < 16 or h < 16:
            continue
        clip = open_source(source, v)
        rate = Fraction(clip.fps_num, clip.fps_den)
        first = max(0, min(clip.num_frames - 1, round(start * rate)))
        piece = clip[first : min(clip.num_frames, first + round(seconds * rate) + 1)]
        c = _cover_crop(v.width, v.height, v.sar, Fraction(16, 9), crop)
        if any((c.left, c.right, c.top, c.bottom)):
            piece = core.std.Crop(piece, c.left, c.right, c.top, c.bottom)
        piece = scale_to_sd(piece, v, w, h, "spline36", matrix, vs.YUV420P16)
        piece = _nearest_rate(piece, rate, disc)
        while piece.num_frames < count:  # a short chapter: play it again
            piece = piece + piece
        piece = core.std.AddBorders(piece[:count], left=x, right=720 - x - w, top=y,
                                    bottom=frame_h - y - h)  # fmt: skip
        box = core.std.BlankClip(width=w, height=h, format=vs.GRAY16, color=[65535], length=count)
        mask = core.std.AddBorders(box, left=x, right=720 - x - w, top=y,
                                   bottom=frame_h - y - h, color=[0])  # fmt: skip
        mask = core.std.AssumeFPS(mask, fpsnum=disc.numerator, fpsden=disc.denominator)
        out = core.std.MaskedMerge(out, piece, mask, first_plane=True)
    clip = core.resize.Point(out, format=vs.YUV420P8, dither_type="error_diffusion")
    settings = EncodeSettings(bitrate=VIDEO_KBPS, maxrate=PEAK_KBPS,
                              aspect="16:9" if aspect > Fraction(3, 2) else "4:3",
                              standard=standard)  # fmt: skip
    name_enc, _note = encoders.choose(encoder)
    m2v = encoders.encode(name_enc, clip, workdir / f"{name}.m2v", settings,
                          workdir / f"{name}_{name_enc}")  # fmt: skip
    ac3 = _audio(None, None, 0.0, count / float(disc), Fraction(1), workdir / f"{name}.ac3")
    return mux(m2v, [ac3], workdir / f"{name}.mpg")
