"""A printable DVD case cover and disc label (PDF, A4) made from the project.

The case insert is 273 x 183 mm with a 14 mm spine (a slim case: 267 x 183, 7 mm), laid
out back | spine | front as it wraps the case, with 3 mm of bleed and crop marks. The
disc label is 118 mm across with a 41 mm hub, its cut lines drawn. The picture is the
menu's (a chosen image, else the film frame the menu uses, else a quarter in), the title
the disc name or the menu logo; the back lists what is on the disc. The texts are in the
disc's language (Turkish), like the menus.
"""

from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QImage,
    QLinearGradient,
    QPageLayout,
    QPageSize,
    QPainter,
    QPainterPath,
    QPdfWriter,
    QPen,
)

from dvd import toolchain
from dvd.lang import name_tr
from dvd.project.model import Project

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
U = 10  # drawing units per millimetre
HEIGHT, BLEED = 183, 3
CASES = {"case": (273, 14), "slim": (267, 7)}  # total width, spine
DISC, HUB = 118, 41
DISPLAY, TEXT = "Bricolage Grotesque", "Source Sans 3"


class CoverError(RuntimeError):
    pass


@dataclass
class CoverInfo:
    title: str
    subtitle: str = ""  # "Disk 2 / 4" in a series set
    lines: list[str] = field(default_factory=list)  # what is on the disc, for the back
    picture: QImage | None = None
    logo: QImage | None = None


def _fonts() -> None:
    from dvd.menu.render import _fonts as load

    load()


def _font(family: str, mm: float, weight: int = 400) -> QFont:
    font = QFont(family)
    font.setPixelSize(max(1, round(mm * U)))
    font.setWeight(QFont.Weight(weight))
    return font


def _r(x: float, y: float, w: float, h: float) -> QRectF:
    return QRectF(x * U, y * U, w * U, h * U)


def _minutes(seconds: float) -> str:
    m = round(seconds / 60)
    return f"{m // 60} sa {m % 60} dk" if m >= 60 else f"{m} dk"


def info_from(project: Project, project_file: Path, infos: list) -> CoverInfo:
    from dvd.project import edit, source_path

    title = project.titles[0]
    duration = sum(i.duration or 0 for i in infos)
    audio = ", ".join(f"{name_tr(a.lang)} {a.channels}" for a in edit.disc_audio(title))
    subs = ", ".join(name_tr(s.lang) for s in edit.disc_subtitles(title))
    v = infos[0].main_video if infos else None
    aspect = title.video.aspect if title.video.aspect != "auto" else (
        "16:9" if v is None or v.width / max(1, v.height) > 1.5 else "4:3")  # fmt: skip
    lines = [f"Süre: {_minutes(duration)}", f"Görüntü: {aspect} · {project.disc.standard.upper()}",
             f"Ses: {audio or 'yok'}"]  # fmt: skip
    if subs:
        lines.append(f"Altyazı: {subs}")
    if len(project.titles) > 1:
        lines.append(f"{len(project.titles)} bölüm")
    lines.append(f"{project.disc.media.upper().replace('DVD', 'DVD-')} · Bölge: tümü")
    series = project.series
    info = CoverInfo(series.name if series else project.disc.name,
                     f"Disk {series.disc} / {series.discs}" if series and series.discs > 1
                     else "", lines)  # fmt: skip
    base = project_file.parent
    menus = project.menus
    picture = None
    if menus is not None and menus.background.image:
        picture = QImage(str(_path(base, menus.background.image)))
    if (picture is None or picture.isNull()) and infos:
        at = (infos[0].duration or 0) / 4
        if menus is not None and menus.background.frame:
            from dvd.project.model import parse_timecode

            at = parse_timecode(menus.background.frame)
        picture = film_frame(source_path(project_file, title), at)
    info.picture = picture if picture is not None and not picture.isNull() else None
    if menus is not None and menus.logo:
        logo = QImage(str(_path(base, menus.logo)))
        info.logo = None if logo.isNull() else logo
    return info


def _path(base: Path, value: str) -> Path:
    p = Path(value)
    return p if p.is_absolute() else base / p


def film_frame(source: Path, at: float) -> QImage | None:
    ffmpeg = toolchain.find_executable(["ffmpeg.exe", "ffmpeg"], toolchain.tool_dirs())
    if ffmpeg is None:
        return None
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "frame.png"
        subprocess.run([str(ffmpeg), "-v", "error", "-y", "-ss", f"{at:.3f}", "-i", str(source),
                        "-frames:v", "1", "-vf", "scale='min(1920,iw)':-2", str(out)],
                       capture_output=True, creationflags=_NO_WINDOW, check=False)  # fmt: skip
        image = QImage(str(out))
        return None if image.isNull() else image.copy()


def _fill(p: QPainter, image: QImage | None, target: QRectF, darken: float = 0.0) -> None:
    """`image` covering `target` (cropped to its shape), else the plain dark colour."""
    p.fillRect(target, QColor("#141414"))
    if image is not None:
        scale = max(target.width() / image.width(), target.height() / image.height())
        w, h = target.width() / scale, target.height() / scale
        src = QRectF((image.width() - w) / 2, (image.height() - h) / 2, w, h)
        p.drawImage(target, image, src)
    if darken:
        p.fillRect(target, QColor(0, 0, 0, round(255 * darken)))


def _crop_marks(p: QPainter, x: float, y: float, w: float, h: float) -> None:
    p.setPen(QPen(QColor("#000000"), 0.2 * U))
    for cx in (x, x + w):
        for cy in (y, y + h):
            dx = -1 if cx == x else 1
            dy = -1 if cy == y else 1
            p.drawLine(QPointF(cx * U, (cy + dy * (BLEED + 1)) * U),
                       QPointF(cx * U, (cy + dy * (BLEED + 6)) * U))  # fmt: skip
            p.drawLine(QPointF((cx + dx * (BLEED + 1)) * U, cy * U),
                       QPointF((cx + dx * (BLEED + 6)) * U, cy * U))  # fmt: skip


def _title(p: QPainter, info: CoverInfo, box: QRectF, mm: float) -> None:
    if info.logo is not None:
        scale = min(box.width() / info.logo.width(), box.height() / info.logo.height())
        w, h = info.logo.width() * scale, info.logo.height() * scale
        p.drawImage(QRectF(box.center().x() - w / 2, box.bottom() - h, w, h), info.logo)
        return
    p.setPen(QColor("#F2EEE8"))
    p.setFont(_font(DISPLAY, mm, 600))
    flags = Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom | Qt.TextFlag.TextWordWrap
    p.drawText(box, flags, info.title)


def draw_case(p: QPainter, info: CoverInfo, kind: str, x: float, y: float) -> None:
    """The case insert with its top left trim corner at (x, y) mm."""
    width, spine = CASES[kind]
    panel = (width - spine) / 2
    _fill(p, info.picture, _r(x - BLEED, y - BLEED, width + 2 * BLEED, HEIGHT + 2 * BLEED))
    front = _r(x + panel + spine, y, panel, HEIGHT)
    shade = QLinearGradient(front.topLeft(), front.bottomLeft())
    shade.setColorAt(0.5, QColor(0, 0, 0, 0))
    shade.setColorAt(1.0, QColor(0, 0, 0, 200))
    p.fillRect(_r(x + panel + spine, y - BLEED, panel + BLEED, HEIGHT + 2 * BLEED), QBrush(shade))
    _title(p, info, _r(x + panel + spine + 12, y + HEIGHT - 62, panel - 24, 40), 11)
    if info.subtitle:
        p.setFont(_font(TEXT, 4.5, 600))
        p.setPen(QColor("#D8D2C8"))
        p.drawText(_r(x + panel + spine + 12, y + HEIGHT - 20, panel - 24, 8),
                   Qt.AlignmentFlag.AlignHCenter, info.subtitle)  # fmt: skip
    # Back: darkened, the disc's contents.
    p.fillRect(_r(x - BLEED, y - BLEED, panel + BLEED, HEIGHT + 2 * BLEED), QColor(0, 0, 0, 170))
    p.setPen(QColor("#F2EEE8"))
    p.setFont(_font(DISPLAY, 7, 600))
    p.drawText(_r(x + 12, y + 16, panel - 24, 30), Qt.TextFlag.TextWordWrap, info.title)
    p.setFont(_font(TEXT, 3.6))
    p.setPen(QColor("#D8D2C8"))
    for k, line in enumerate(info.lines):
        p.drawText(_r(x + 12, y + HEIGHT - 20 - 6 * (len(info.lines) - k), panel - 24, 6),
                   Qt.AlignmentFlag.AlignLeft, line)  # fmt: skip
    # Spine: a dark band, the title running top to bottom.
    band = _r(x + panel, y - BLEED, spine, HEIGHT + 2 * BLEED)
    p.fillRect(band, QColor(12, 12, 12, 235))
    p.save()
    p.translate((x + panel + spine / 2) * U, (y + HEIGHT / 2) * U)
    p.rotate(90)
    p.setPen(QColor("#F2EEE8"))
    p.setFont(_font(DISPLAY, min(6.5, spine * 0.45), 600))
    p.drawText(_r(-HEIGHT / 2 + 8, -spine / 2, HEIGHT - 16, spine),
               Qt.AlignmentFlag.AlignCenter, info.title)  # fmt: skip
    p.restore()
    _crop_marks(p, x, y, width, HEIGHT)
    p.setPen(QPen(QColor(255, 255, 255, 90), 0.15 * U, Qt.PenStyle.DashLine))
    for fold in (x + panel, x + panel + spine):  # where the cover folds round the case
        p.drawLine(QPointF(fold * U, (y - BLEED - 6) * U), QPointF(fold * U, (y - BLEED - 1) * U))


def draw_label(p: QPainter, info: CoverInfo, cx: float, cy: float) -> None:
    """The disc label centred at (cx, cy) mm."""
    outer, hub = DISC / 2, HUB / 2
    disc = QPainterPath()
    disc.addEllipse(QPointF(cx * U, cy * U), outer * U, outer * U)
    disc.addEllipse(QPointF(cx * U, cy * U), hub * U, hub * U)  # odd-even: the hole stays out
    p.save()
    p.setClipPath(disc)
    _fill(p, info.picture, _r(cx - outer, cy - outer, DISC, DISC), 0.35)
    # Above the hub, where the disc is wide enough for two lines.
    _title(p, info, _r(cx - 38, cy - hub - 26, 76, 22), 6.5)
    p.setPen(QColor("#D8D2C8"))
    p.setFont(_font(TEXT, 3.2))
    small = " · ".join(x for x in (info.subtitle, info.lines[0] if info.lines else "") if x)
    p.drawText(_r(cx - 40, cy + hub + 8, 80, 8), Qt.AlignmentFlag.AlignHCenter, small)
    p.restore()
    p.setPen(QPen(QColor("#9A948A"), 0.2 * U))
    p.drawEllipse(QPointF(cx * U, cy * U), outer * U, outer * U)
    p.drawEllipse(QPointF(cx * U, cy * U), hub * U, hub * U)


def _writer(path: Path, landscape: bool) -> QPdfWriter:
    w = QPdfWriter(str(path))
    w.setResolution(300)
    w.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
    w.setPageOrientation(QPageLayout.Orientation.Landscape if landscape
                         else QPageLayout.Orientation.Portrait)  # fmt: skip
    w.setPageMargins(QPageLayout().margins())  # none: the layout keeps its own white edge
    w.setTitle(path.stem)
    w.setCreator("DVD Studyo")
    return w


def _paint(device, draw, dpmm: float) -> None:
    p = QPainter(device)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    p.scale(dpmm / U, dpmm / U)
    draw(p)
    p.end()


def write_cover(info: CoverInfo, out: Path, kind: str = "case") -> Path:
    """The case insert on A4 landscape (297 x 210 mm)."""
    if kind not in CASES:
        raise CoverError(f"case: one of {', '.join(CASES)}")
    _fonts()
    width, _spine = CASES[kind]
    x, y = (297 - width) / 2, (210 - HEIGHT) / 2
    _paint(_writer(out, True), lambda p: draw_case(p, info, kind, x, y), 300 / 25.4)
    return out


def write_label(info: CoverInfo, out: Path) -> Path:
    """The disc label on A4 portrait (210 x 297 mm), in the upper half."""
    _fonts()
    _paint(_writer(out, False), lambda p: draw_label(p, info, 105, 85), 300 / 25.4)
    return out


def preview(info: CoverInfo, kind: str = "case", dpmm: float = 4.0) -> QImage:
    """The same drawing as a picture (A4 at `dpmm` dots per millimetre), for a quick look."""
    _fonts()
    landscape = kind != "label"
    w, h = (297, 210) if landscape else (210, 297)
    image = QImage(round(w * dpmm), round(h * dpmm), QImage.Format.Format_RGB32)
    image.fill(QColor("#FFFFFF"))
    if kind == "label":
        _paint(image, lambda p: draw_label(p, info, 105, 85), dpmm)
    else:
        width, _ = CASES[kind]
        _paint(image, lambda p: draw_case(p, info, kind, (297 - width) / 2, (210 - HEIGHT) / 2),
               dpmm)  # fmt: skip
    return image
