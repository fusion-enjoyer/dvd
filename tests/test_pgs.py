import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from dvd import toolchain
from dvd.subs.pgs import decode_rle, parse_sup
from dvd.subs.render import Placement, place_bitmap

sys.path.insert(0, str(Path(__file__).parent))
from sup_writer import caption, display_set, encode_rle  # noqa: E402

FFMPEG = toolchain.find_executable(["ffmpeg.exe", "ffmpeg"], toolchain.tool_dirs())


def sample_sup() -> bytes:
    return (display_set(1.0, 0, [(caption(), 760, 900, False)]) + display_set(3.0, 1, [])
            + display_set(4.0, 2, [(caption(200, 40), 860, 100, True)])
            + display_set(5.5, 3, []))  # fmt: skip


def test_rle_round_trip():
    img = np.zeros((5, 300), np.uint8)
    img[1, 10:200] = 1
    img[2, :] = 2
    img[3, 5] = 7
    assert (decode_rle(encode_rle(img), 300, 5) == img).all()


def test_display_sets_become_timed_pictures():
    cues = parse_sup(sample_sup())
    assert [(c.start, c.end, c.forced) for c in cues] == [(1.0, 3.0, False), (4.0, 5.5, True)]
    first = cues[0]
    assert (first.x, first.y, first.frame_width, first.frame_height) == (760, 900, 1920, 1080)
    assert first.rgba.shape == (60, 400, 4)
    assert tuple(first.rgba[30, 200]) == (255, 255, 255, 255)  # Y 235 = white
    assert tuple(first.rgba[1, 1]) == (0, 0, 0, 255)  # black border (16 -> 0 in full range)


def test_bitmap_follows_the_video_crop_and_scale():
    # 2.39:1 film in 1920x1080 with 138-line bars, on a PAL 16:9 frame: 720x432 + 72 bars.
    where = Placement((0, 0, 138, 138), (720, 432), (0, 72), (720, 576))
    cue = parse_sup(sample_sup())[0]
    b = place_bitmap(cue.rgba, cue.x, cue.y, (1920, 1080), where)
    assert b.x == pytest.approx(760 * 720 / 1920, abs=2) and b.x % 2 == 0
    assert b.y == pytest.approx((900 - 138) * 432 / 804 + 72, abs=2) and b.y % 2 == 0
    assert b.width == pytest.approx(150, abs=2) and b.height == pytest.approx(32, abs=3)
    assert len({tuple(p) for p in b.rgba.reshape(-1, 4)}) <= 4
    # A caption in the cropped-away band is kept inside the frame.
    low = place_bitmap(cue.rgba, 760, 1060, (1920, 1080), where)
    assert low.y + low.height <= 576


@pytest.mark.skipif(FFMPEG is None, reason="ffmpeg not installed")
def test_pgs_track_from_mkv_reaches_the_disc(tmp_path: Path):
    from dvd.build import build
    from dvd.probe import probe
    from dvd.project import new_project, save

    sup = tmp_path / "subs.sup"
    sup.write_bytes(sample_sup())
    src = tmp_path / "film.mkv"
    subprocess.run(
        [str(FFMPEG), "-v", "error", "-y",
         "-f", "lavfi", "-i", "testsrc2=size=1920x1080:rate=25:duration=6",
         "-f", "lavfi", "-i", "sine=sample_rate=48000:duration=6", "-i", str(sup),
         "-map", "0", "-map", "1", "-map", "2", "-c:v", "libx264", "-preset", "ultrafast",
         "-c:a", "ac3", "-c:s", "copy", "-metadata:s:s:0", "language=tur", str(src)],
        check=True,
    )  # fmt: skip
    info = probe(src)
    project = new_project(info, tmp_path)
    assert len(project.titles[0].subtitles) == 1  # PGS is picked up like a text track
    project_file = tmp_path / "film.dvd.yaml"
    save(project, project_file)

    result = build(project_file, make_iso=False)

    vob = probe(result.video_ts / "VTS_01_1.VOB")
    assert [s.codec for s in vob.subtitles] == ["dvd_subtitle"]
    xml = next(tmp_path.rglob("sub00/spumux.xml")).read_text(encoding="utf-8")
    assert xml.count("<spu ") == 2 and xml.count('force="yes"') == 1
