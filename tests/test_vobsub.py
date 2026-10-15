import subprocess
from fractions import Fraction
from pathlib import Path

import numpy as np
import pytest

from dvd import toolchain
from dvd.subs.vobsub import TICK, cues_from_packets, parse_idx, parse_spu, rgba

FFMPEG = toolchain.find_executable(["ffmpeg.exe", "ffmpeg"], toolchain.tool_dirs())
SPUMUX = toolchain.find_executable(["spumux.exe", "spumux"], toolchain.tool_dirs())

IDX = """# VobSub index file, v7 (do not modify this line!)
size: 720x576
palette: 000000, ffffff, 808080, ff0000, 00ff00, 0000ff, ffff00, 00ffff, ff00ff, 101010, \
202020, 303030, 404040, 505050, 606060, 707070
"""


def _code(run: int, slot: int) -> list[int]:
    v = (run << 2) | slot
    length = 1 if run < 4 else 2 if run < 16 else 3 if run < 64 else 4
    return [(v >> (4 * k)) & 0xF for k in reversed(range(length))]


def _field(rows: np.ndarray) -> bytes:
    out = bytearray()
    for row in rows:
        nibbles, x = [], 0
        while x < len(row):
            run = 1
            while x + run < len(row) and row[x + run] == row[x] and run < 255:
                run += 1
            nibbles += _code(run, int(row[x]))
            x += run
        if len(nibbles) % 2:
            nibbles.append(0)
        out += bytes((a << 4) | b for a, b in zip(nibbles[0::2], nibbles[1::2], strict=True))
    return bytes(out)


def spu(slots, x, y, colours=(0, 1, 2, 3), alpha=(0, 15, 15, 8), stop=1.5, forced=False):
    """A subpicture unit as a DVD player reads it (the writer side of `parse_spu`)."""
    h, w = slots.shape
    top, bottom = _field(slots[0::2]), _field(slots[1::2])
    pixels = top + bottom
    first = 4 + len(pixels)
    second_cmds = bytes([0x02, 0xFF])
    x2, y2 = x + w - 1, y + h - 1
    cmds = bytearray([0x00] if forced else []) + bytes([0x01])
    cmds += bytes([0x03, (colours[3] << 4) | colours[2], (colours[1] << 4) | colours[0]])
    cmds += bytes([0x04, (alpha[3] << 4) | alpha[2], (alpha[1] << 4) | alpha[0]])
    cmds += bytes([0x05, x >> 4, ((x & 0xF) << 4) | (x2 >> 8), x2 & 0xFF,
                   y >> 4, ((y & 0xF) << 4) | (y2 >> 8), y2 & 0xFF])  # fmt: skip
    cmds += bytes([0x06]) + (4).to_bytes(2, "big") + (4 + len(top)).to_bytes(2, "big")
    cmds += bytes([0xFF])
    second = first + 4 + len(cmds)
    dcsq1 = (0).to_bytes(2, "big") + second.to_bytes(2, "big") + bytes(cmds)
    dcsq2 = round(stop / TICK).to_bytes(2, "big") + second.to_bytes(2, "big") + second_cmds
    body = pixels + dcsq1 + dcsq2
    return (4 + len(body)).to_bytes(2, "big") + first.to_bytes(2, "big") + body


def letters(h=20, w=300) -> np.ndarray:
    """Slot 1 fill inside slot 2 outline, a slot 3 rim, on slot 0 background."""
    s = np.zeros((h, w), np.uint8)
    s[3:-3, 10:-10] = 3
    s[4:-4, 11:-11] = 2
    s[6:-6, 14:-14] = 1
    return s


def test_spu_round_trip_and_palette():
    slots = letters()
    unit = parse_spu(spu(slots, 200, 500, colours=(0, 1, 9, 3), forced=True))
    assert unit is not None and unit.forced and (unit.x, unit.y) == (200, 500)
    assert np.array_equal(unit.slots, slots)
    assert unit.start == 0 and abs(unit.end - 1.5) < TICK
    header = parse_idx(IDX)
    assert header.size == (720, 576) and tuple(header.palette[3]) == (255, 0, 0)
    pic = rgba(unit, header.palette)
    assert tuple(pic[10, 150]) == (255, 255, 255, 255)  # slot 1 -> palette 1, opaque
    assert tuple(pic[4, 150]) == (16, 16, 16, 255)  # slot 2 -> palette 9
    assert tuple(pic[3, 150]) == (255, 0, 0, 136)  # slot 3 -> palette 3, half transparent
    assert pic[0, 0, 3] == 0


def test_cues_get_times_and_colours_without_a_palette():
    packets = [(10.5, None, spu(letters(), 100, 480, stop=2.0)),
               (20.0, 3.0, spu(letters(), 100, 480, stop=0.0)),  # no stop: packet duration
               (30.0, None, b"\x00\x01")]  # fmt: skip
    cues = cues_from_packets(packets, parse_idx(""), (720, 576), origin=0.5)
    assert [(c.start, round(c.end, 2)) for c in cues] == [(10.0, 12.0), (19.5, 22.5)]
    pic = cues[0].rgba
    # No palette: the colour least often next to transparency is the white fill.
    assert tuple(pic[10, 150, :3]) == (255, 255, 255) and tuple(pic[4, 150, :3]) == (0, 0, 0)
    assert (cues[0].frame_width, cues[0].frame_height) == (720, 576)


@pytest.mark.skipif(FFMPEG is None or SPUMUX is None, reason="ffmpeg or spumux missing")
def test_dvd_subtitle_track_reaches_the_disc(tmp_path: Path):
    """A DVD rip in MKV: subpictures made by spumux, remuxed, read back and put on a disc."""
    from dvd.build import build
    from dvd.probe import probe
    from dvd.project import new_project, save
    from dvd.subs.spumux import add_subtitle_stream
    from dvd.subs.srt import Cue
    from dvd.subs.vobsub import extract_vobsub

    mpg = tmp_path / "in.mpg"
    subprocess.run(
        [str(FFMPEG), "-v", "error", "-y", "-f", "lavfi",
         "-i", "testsrc2=size=720x576:rate=25:duration=5", "-f", "lavfi",
         "-i", "sine=sample_rate=48000:duration=5", "-c:v", "mpeg2video", "-b:v", "4M",
         "-c:a", "ac3", "-f", "dvd", "-muxrate", "10080000", str(mpg)],
        check=True,
    )  # fmt: skip
    cues = [Cue(1.0, 2.5, ("Merhaba dünya",)), Cue(3.0, 4.0, ("İkinci",))]
    with_subs = add_subtitle_stream(mpg, tmp_path / "subs.mpg", cues, 0,
                                    (720, 576, Fraction(4, 3)), "pal", tmp_path / "w")  # fmt: skip
    rip = tmp_path / "rip.mkv"
    subprocess.run(
        [str(FFMPEG), "-v", "error", "-y", "-i", str(with_subs), "-map", "0:v", "-map", "0:a",
         "-map", "0:s", "-c", "copy",
         "-metadata:s:s:0", "language=tur", str(rip)],
        check=True,
    )  # fmt: skip
    info = probe(rip)
    v = info.main_video
    track = info.subtitles[0]
    assert track.codec == "dvd_subtitle" and track.usable
    read = extract_vobsub(rip, track.index, (v.width, v.height), v.start_time)
    assert [(round(c.start, 2), round(c.end, 2)) for c in read] == [(1.0, 2.5), (3.0, 4.0)]

    project = new_project(info, tmp_path)
    assert [s.track for s in project.titles[0].subtitles] == [track.index]
    project.titles[0].video.overrides = {"encoder": "ffmpeg"}
    project.menus = None
    project_file = tmp_path / "rip.dvd.yaml"
    save(project, project_file)
    result = build(project_file, make_iso=False)
    assert [s.codec for s in probe(result.video_ts / "VTS_01_1.VOB").subtitles] == ["dvd_subtitle"]
    xml = next((tmp_path / "build").rglob("sub00/spumux.xml")).read_text(encoding="utf-8")
    assert xml.count("<spu ") == 2
