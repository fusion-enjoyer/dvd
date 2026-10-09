import os
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dvd.subs.render import DEFAULT_STYLE, render_cue  # noqa: E402
from dvd.subs.srt import Cue  # noqa: E402
from dvd.subs.styles import (  # noqa: E402
    StyleError,
    for_viewing,
    list_styles,
    load_style,
    save_style,
)


def test_builtin_templates():
    assert load_style("varsayilan") == DEFAULT_STYLE
    assert load_style("sari").fill == (240, 220, 60)
    assert load_style("buyuk").size > DEFAULT_STYLE.size
    with pytest.raises(StyleError):
        load_style("yok-boyle-bir-stil")


def test_user_style_round_trip(tmp_path: Path):
    from dataclasses import replace

    mine = replace(DEFAULT_STYLE, fill=(255, 200, 0), size=0.07, family="Arial")
    path = save_style("Salon TV", mine, tmp_path)
    assert "fill" in path.read_text(encoding="utf-8")
    assert "outline" not in path.read_text(encoding="utf-8")  # only what differs is stored
    assert load_style("Salon TV", tmp_path) == mine
    assert list_styles(tmp_path)[-1] == "Salon TV"
    with pytest.raises(StyleError):
        save_style("sari", mine, tmp_path)  # built-in names are taken
    with pytest.raises(StyleError):
        save_style("../kaçış", mine, tmp_path)


def test_viewing_profile_scales_any_style():
    s = for_viewing(load_style("buyuk"), 1.2, 0.875)
    assert s.size == pytest.approx(load_style("buyuk").size * 1.2)
    assert s.bottom >= (1 - 0.875) / 2


def test_yellow_style_draws_yellow_text():
    bitmap = render_cue(Cue(0, 1, ("Sarı",)), 720, 576, 16 / 9, load_style("sari"))
    colours = {tuple(p) for p in bitmap.rgba.reshape(-1, 4) if p[3] == 255}
    assert (240, 220, 60, 255) in colours


def test_style_editor_saves_and_previews(tmp_path: Path, monkeypatch):
    from PySide6.QtWidgets import QApplication

    monkeypatch.setenv("DVD_STYLE_DIR", str(tmp_path))
    QApplication.instance() or QApplication([])
    from dvd.gui.style_editor import StyleEditor, preview_image

    image = preview_image(load_style("sari"))
    assert image.width() == 512 and image.height() == 288
    pixels = np.frombuffer(image.convertToFormat(image.Format.Format_RGB888).constBits(),
                           np.uint8)  # fmt: skip
    assert pixels.size > 0
    editor = StyleEditor("buyuk")
    editor.size.setValue(7.5)
    editor.name.setText("sari")
    editor._save()
    assert "hazır" in editor.message.text()  # built-in name refused, in Turkish
    editor.name.setText("Benim")
    editor._save()
    assert load_style("Benim").size == pytest.approx(0.075)
