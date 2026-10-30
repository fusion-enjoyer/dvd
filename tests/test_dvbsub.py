import subprocess
from fractions import Fraction
from pathlib import Path

import numpy as np
import pytest

from dvd import toolchain
from dvd.subs.dvbsub import _Bits, _string, cues_from_packets, decode_field

FFMPEG = toolchain.find_executable(["ffmpeg.exe", "ffmpeg"], toolchain.tool_dirs())
SPUMUX = toolchain.find_executable(["spumux.exe", "spumux"], toolchain.tool_dirs())


def _bytes(bits: str) -> bytes:
    bits = bits.replace(" ", "")
    bits += "0" * (-len(bits) % 8)
    return int(bits, 2).to_bytes(len(bits) // 8, "big")


def test_pixel_code_strings_at_4_and_8_bits():
    # 4 bits: one pixel of 3; 9+1 pixels of 5; 3 pixels of 0; end
    runs, ok = _string(_Bits(_bytes("0011 0000 1 1 10 0001 0101 0000 0 001 0000 0 000"), 0), 4)
    assert ok and runs == [(1, 3), (10, 5), (3, 0)]
    # 8 bits: one pixel of 5; 6 pixels of 9; 4 pixels of 0; end
    runs, ok = _string(
        _Bits(
            _bytes("00000101 00000000 1 0000110 00001001 00000000 0 0000100 00000000 0 0000000"), 0
        ),
        8,
    )
    assert ok and runs == [(1, 5), (6, 9), (4, 0)]
    # 2-bit codes drawn into a 4-bit region go through the default map (3 -> 15)
    rows = [np.zeros(8, np.uint8)]
    decode_field(bytes([0x10]) + _bytes("11 01 00 0 0 00") + bytes([0xF0]), rows, 4, 2)
    assert rows[0].tolist() == [0, 0, 15, 7, 0, 0, 0, 0]


def _set(page_regions: list[tuple[int, int, int]], timeout: int = 5) -> bytes:
    """A display set: page composition, one 4x2 region at 2 bits, a CLUT, one object."""

    def seg(kind: int, body: bytes) -> bytes:
        return bytes([0x0F, kind]) + (1).to_bytes(2, "big") + len(body).to_bytes(2, "big") + body

    page = bytes([timeout, 0x04]) + b"".join(
        bytes([rid, 0]) + x.to_bytes(2, "big") + y.to_bytes(2, "big") for rid, x, y in page_regions
    )
    if not page_regions:
        return seg(0x10, page) + seg(0x80, b"")
    region = bytes([0, 0x08]) + (4).to_bytes(2, "big") + (2).to_bytes(2, "big") \
        + bytes([0x04, 0, 0, 0]) + (1).to_bytes(2, "big") + (0).to_bytes(2, "big") \
        + (0).to_bytes(2, "big")  # fmt: skip
    clut = bytes([0, 0]) + bytes([1, 0x81, 235, 128, 128, 0])  # entry 1: white, 2-bit table
    line = bytes([0x10]) + _bytes("01 01 01 01 00 0 0 00") + bytes([0xF0])
    obj = (1).to_bytes(2, "big") + bytes([0]) + len(line).to_bytes(2, "big") \
        + (0).to_bytes(2, "big") + line  # fmt: skip
    return seg(0x10, page) + seg(0x11, region) + seg(0x12, clut) + seg(0x13, obj) + seg(0x80, b"")


def test_display_sets_become_cues_that_end_with_the_next_set_or_the_time_out():
    cues = cues_from_packets([(1.0, _set([(0, 100, 500)])), (2.5, _set([])),
                              (4.0, b"\x20\x00" + _set([(0, 10, 20)], timeout=2))])  # fmt: skip
    assert [(c.start, c.end, c.x, c.y) for c in cues] == [(1.0, 2.5, 100, 500), (4.0, 6.0, 10, 20)]
    assert cues[0].rgba.shape == (2, 4, 4) and (cues[0].rgba[..., 3] == 255).all()
    assert cues[0].rgba[0, 0, :3].tolist() == [255, 255, 255]  # both fields from the top one
    assert (cues[0].frame_width, cues[0].frame_height) == (720, 576)


@pytest.mark.skipif(FFMPEG is None or SPUMUX is None, reason="ffmpeg or spumux missing")
def test_dvb_subtitle_track_reaches_the_disc(tmp_path: Path):
    """A TV recording: the captions spumux made, encoded as DVB by FFmpeg, read back by us
    (the same shapes as the DVD subpictures) and put on a disc."""
    from dvd.build import build
    from dvd.probe import probe
    from dvd.project import new_project, save
    from dvd.subs.dvbsub import extract_dvbsub
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
    rec = tmp_path / "kayit.ts"
    subprocess.run(
        [str(FFMPEG), "-v", "error", "-y", "-i", str(with_subs), "-map", "0:v", "-map", "0:a",
         "-map", "0:s", "-c:v", "copy", "-c:a", "copy", "-c:s", "dvbsub",
         "-metadata:s:s:0", "language=tur", "-f", "mpegts", str(rec)],
        check=True,
    )  # fmt: skip
    info = probe(rec)
    v = info.main_video
    track = info.subtitles[0]
    assert track.codec == "dvb_subtitle" and track.usable
    read = extract_dvbsub(rec, track.index, v.start_time)
    assert [(round(c.start, 1), round(c.end, 1)) for c in read] == [(1.0, 2.5), (3.0, 4.0)]
    dvd = extract_vobsub(with_subs, next(s.index for s in probe(with_subs).subtitles),
                         (720, 576))  # fmt: skip
    for a, b in zip(read, dvd, strict=True):
        shapes = [np.zeros((576, 720), bool) for _ in range(2)]
        for canvas, c in zip(shapes, (a, b), strict=True):
            canvas[c.y : c.y + c.rgba.shape[0], c.x : c.x + c.rgba.shape[1]] = c.rgba[..., 3] > 0
        assert (shapes[0] != shapes[1]).sum() < 0.01 * shapes[1].sum()

    project = new_project(info, tmp_path)
    assert [s.track for s in project.titles[0].subtitles] == [track.index]
    project.titles[0].video.overrides = {"encoder": "ffmpeg"}
    project.menus = None
    project_file = tmp_path / "kayit.dvd.yaml"
    save(project, project_file)
    result = build(project_file, make_iso=False)
    assert [s.codec for s in probe(result.video_ts / "VTS_01_1.VOB").subtitles] == ["dvd_subtitle"]
    xml = next((tmp_path / "build").rglob("sub00/spumux.xml")).read_text(encoding="utf-8")
    assert xml.count("<spu ") == 2
