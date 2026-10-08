from fractions import Fraction
from pathlib import Path

import numpy as np
import pytest

from dvd.subs.render import Bitmap, render_cue, save_png
from dvd.subs.srt import Cue, decode, parse, read_srt, retime

SRT = """1
00:00:01,000 --> 00:00:03,500
Merhaba dünya!
<i>İkinci satır: ğüşıöç</i>

2
00:00:04,000 --> 00:00:05,000
<i>Tamamı italik</i>

3
00:00:06,000 --> 00:00:05,000
Bitişi başından önce, atlanır

4
00:00:07.250 --> 00:00:08.000
{\\an8}<font color="#ffff00">Sarı</font> etiketler silinir
"""


def test_parse_cues_tags_and_bad_timing():
    cues = parse(SRT)
    assert [c.start for c in cues] == [1.0, 4.0, 7.25]
    assert cues[0].lines == ("Merhaba dünya!", "İkinci satır: ğüşıöç")
    assert not cues[0].italic and cues[1].italic
    assert cues[2].lines == ("Sarı etiketler silinir",)


@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig", "utf-16", "cp1254", "iso-8859-9"])
def test_turkish_encodings_are_detected(encoding):
    text = "1\n00:00:01,000 --> 00:00:02,000\nĞğ Şş İı Öö Çç Üü\n"
    assert parse(decode(text.encode(encoding)))[0].lines == ("Ğğ Şş İı Öö Çç Üü",)


def test_read_srt_without_cues_fails(tmp_path: Path):
    from dvd.subs.srt import SubtitleError

    (tmp_path / "bos.srt").write_text("bu bir altyazı değil", encoding="utf-8")
    with pytest.raises(SubtitleError):
        read_srt(tmp_path / "bos.srt")


def test_retime_for_pal_speedup():
    cue = retime([Cue(25.0, 50.0, ("a",))], 25 / (24000 / 1001))[0]
    assert cue.start == pytest.approx(23.976, abs=0.001)


def colours(b: Bitmap) -> set[tuple[int, ...]]:
    return {tuple(px) for px in b.rgba.reshape(-1, 4)}


PAL_WIDE = (720, 576, Fraction(16, 9))


def test_render_uses_at_most_four_colours_and_sits_at_the_bottom():
    b = render_cue(Cue(0, 1, ("Merhaba dünya, ğüşıöç İ",)), *PAL_WIDE)
    assert len(colours(b)) <= 4
    assert (235, 235, 235, 255) in colours(b) and (16, 16, 16, 255) in colours(b)
    assert b.x % 2 == 0 and b.y % 2 == 0 and b.width % 2 == 0 and b.height % 2 == 0
    assert b.x + b.width <= 720 and b.y + b.height <= 576
    assert b.y > 576 * 0.75
    assert abs((b.x + b.width / 2) - 360) < 8  # centred


def test_anamorphic_squeeze_in_16_9():
    cue = Cue(0, 1, ("Aynı metin",))
    wide = render_cue(cue, *PAL_WIDE)
    full = render_cue(cue, 720, 576, Fraction(4, 3))
    # 16:9 canvas 1024 -> 720, 4:3 canvas 768 -> 720: wide text is 3/4 as wide on disc.
    assert wide.width / full.width == pytest.approx(0.75, abs=0.05)
    assert wide.height == full.height


def test_long_line_wraps_into_two_lines():
    short = render_cue(Cue(0, 1, ("Kısa",)), *PAL_WIDE)
    long = render_cue(Cue(0, 1, ("çok " * 40,)), *PAL_WIDE)
    assert long.height > 1.8 * short.height
    assert long.width <= 720


def test_turkish_marks_are_drawn():
    plain = render_cue(Cue(0, 1, ("gsi",)), *PAL_WIDE)
    marked = render_cue(Cue(0, 1, ("ğşı",)), *PAL_WIDE)
    assert not np.array_equal(plain.rgba, marked.rgba)


def test_png_round_trip(tmp_path: Path):
    from PySide6.QtGui import QImage

    b = render_cue(Cue(0, 1, ("PNG",)), *PAL_WIDE)
    save_png(b, tmp_path / "a.png")
    img = QImage(str(tmp_path / "a.png"))
    assert (img.width(), img.height()) == (b.width, b.height)
