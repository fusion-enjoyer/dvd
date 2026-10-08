import hashlib
import io
import os
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pycdlib
import pytest

from dvd import toolchain
from dvd.output.iso import (
    IsoError,
    crc_ccitt,
    dir_record,
    dvd_layout,
    tag,
    volume_label,
    write_iso,
)

DIRS = toolchain.tool_dirs()
FFMPEG = toolchain.find_executable(["ffmpeg.exe", "ffmpeg"], DIRS)
FFPROBE = toolchain.find_executable(["ffprobe.exe", "ffprobe"], DIRS)
DVDAUTHOR = toolchain.find_executable(["dvdauthor.exe", "dvdauthor"], DIRS)
needs_tools = pytest.mark.skipif(
    not (FFMPEG and FFPROBE and DVDAUTHOR), reason="ffmpeg/dvdauthor not installed"
)
WHEN = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)


def test_crc_matches_ccitt_check_value():
    assert crc_ccitt(b"123456789") == 0x31C3


def test_tag_checksum_and_crc():
    t = tag(257, 42, b"\x01\x02\x03\x04")
    assert sum(t[0:4]) + sum(t[5:16]) & 0xFF == t[4]
    assert int.from_bytes(t[8:10], "little") == crc_ccitt(b"\x01\x02\x03\x04")
    assert int.from_bytes(t[12:16], "little") == 42


def test_iso_records_have_even_length_matching_their_length_byte():
    for name in (b"\x00", b"VIDEO_TS", b"VIDEO_TS.IFO;1"):
        rec = dir_record(name, 100, 2048, True, WHEN)
        assert len(rec) % 2 == 0 and rec[0] == len(rec)


@pytest.mark.parametrize(
    ("name", "label"),
    [
        ("Yüzüklerin Efendisi: Kralın Dönüşü", "YUZUKLERIN_EFENDISI_KRALIN_DONUSU"),
        ("İstanbul Hatırası (2007)", "ISTANBUL_HATIRASI_2007"),
        ("???", "DVD_VIDEO"),
    ],
)
def test_volume_label(name, label):
    assert volume_label(name) == label[:32]


def _mpg(folder: Path, name: str, size: str, aspect: str, seconds: int = 3) -> Path:
    out = folder / name
    subprocess.run(
        [
            str(FFMPEG), "-v", "error", "-y",
            "-f", "lavfi", "-i", f"testsrc2=size={size}:rate=25:duration={seconds}",
            "-f", "lavfi", "-i", f"sine=duration={seconds}",
            "-c:v", "mpeg2video", "-b:v", "4M", "-g", "12", "-aspect", aspect,
            "-c:a", "ac3", "-ar", "48000", "-f", "dvd", str(out),
        ],
        check=True,
    )  # fmt: skip
    return out


@pytest.fixture(scope="module")
def two_titleset_disc(tmp_path_factory) -> Path:
    """A real VIDEO_TS with two title sets (16:9 and 4:3), authored by dvdauthor."""
    if not (FFMPEG and DVDAUTHOR):
        pytest.skip("ffmpeg/dvdauthor not installed")
    work = tmp_path_factory.mktemp("disc")
    _mpg(work, "a.mpg", "720x576", "16:9")
    _mpg(work, "b.mpg", "720x576", "4:3", seconds=2)
    (work / "dvd.xml").write_text(
        '<dvdauthor dest="out"><vmgm><fpc>jump title 1;</fpc></vmgm>'
        '<titleset><titles><video aspect="16:9"/><pgc><vob file="a.mpg" chapters="0,0:01"/>'
        "</pgc></titles></titleset>"
        '<titleset><titles><video aspect="4:3"/><pgc><vob file="b.mpg"/></pgc></titles>'
        "</titleset></dvdauthor>",
        encoding="utf-8",
    )
    subprocess.run(
        [str(DVDAUTHOR), "-x", "dvd.xml"],
        cwd=work,
        env={**os.environ, "VIDEO_FORMAT": "PAL"},
        check=True,
        capture_output=True,
    )
    return work / "out" / "VIDEO_TS"


def test_layout_follows_the_ifos(two_titleset_disc: Path):
    files = {f.name: f for f in dvd_layout(two_titleset_disc)}
    assert list(files)[:2] == ["VIDEO_TS.IFO", "VIDEO_TS.BUP"]
    vts1, vts2 = files["VTS_01_0.IFO"], files["VTS_02_0.IFO"]
    assert files["VTS_01_1.VOB"].offset == vts1.offset + vts1.sectors
    assert (
        files["VTS_01_0.BUP"].offset == files["VTS_01_1.VOB"].offset + files["VTS_01_1.VOB"].sectors
    )
    assert vts2.offset == files["VTS_01_0.BUP"].offset + files["VTS_01_0.BUP"].sectors


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@needs_tools
def test_image_is_readable_as_udf_iso9660_and_dvd_video(two_titleset_disc: Path, tmp_path: Path):
    out = write_iso(two_titleset_disc, tmp_path / "çıktı" / "disk.iso", "Deneme Diski", WHEN)
    assert out.stat().st_size % 2048 == 0

    iso = pycdlib.PyCdlib()
    iso.open(str(out))
    try:
        assert iso.has_udf()
        expected = sorted(p.name for p in two_titleset_disc.iterdir())
        udf_names = sorted(
            c.file_identifier().decode()
            for c in iso.list_children(udf_path="/VIDEO_TS")
            if c is not None  # pycdlib yields None for the parent entry
        )
        assert udf_names == expected
        iso_names = sorted(
            c.file_identifier().decode().removesuffix(";1")
            for c in iso.list_children(iso_path="/VIDEO_TS")
            if c.file_identifier() not in (b".", b"..")
        )
        assert iso_names == expected
        for name in expected:
            source = (two_titleset_disc / name).read_bytes()
            for kw in ({"udf_path": f"/VIDEO_TS/{name}"}, {"iso_path": f"/VIDEO_TS/{name};1"}):
                buf = io.BytesIO()
                iso.get_file_from_iso_fp(buf, **kw)
                assert _sha(buf.getvalue()) == _sha(source), (name, kw)
        assert iso.pvd.volume_identifier.rstrip() == b"DENEME_DISKI"
    finally:
        iso.close()

    # libdvdread is what DVD player software uses to find titles through UDF.
    for title, seconds in ((1, 3), (2, 2)):
        duration = subprocess.run(
            [str(FFPROBE), "-v", "quiet", "-f", "dvdvideo", "-title", str(title), "-i", str(out),
             "-show_entries", "format=duration", "-of", "csv=p=0"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()  # fmt: skip
        assert float(duration) == pytest.approx(seconds, abs=0.2)


def test_stray_file_is_rejected(two_titleset_disc: Path, tmp_path: Path):
    copy = tmp_path / "VIDEO_TS"
    shutil.copytree(two_titleset_disc, copy)
    (copy / "notlar.txt").write_text("x")
    with pytest.raises(IsoError, match="unexpected files"):
        dvd_layout(copy)


def test_missing_backup_ifo_is_rejected(two_titleset_disc: Path, tmp_path: Path):
    copy = tmp_path / "VIDEO_TS"
    shutil.copytree(two_titleset_disc, copy)
    (copy / "VTS_02_0.BUP").unlink()
    with pytest.raises(IsoError, match="BUP is missing"):
        dvd_layout(copy)
