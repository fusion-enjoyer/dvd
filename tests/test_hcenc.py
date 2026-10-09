import subprocess
import sys
from pathlib import Path

import pytest

from dvd import toolchain
from dvd.video.hcenc import EncodeSettings, encode, ini_text

sys.path.insert(0, str(Path(__file__).parent))
from test_frameserver import pattern_clip  # noqa: E402

DIRS = toolchain.tool_dirs()
READY = all(toolchain.find_executable([p], DIRS) for p in ("HCenc_*.exe", "DvdSource.dll"))


def test_ini_for_pal_film_with_chapters():
    s = EncodeSettings(bitrate=6500, maxrate=9000, aspect="16:9", standard="pal",
                       chapters=[0, 2500, 1200, 2500])  # fmt: skip
    text = ini_text(Path("a.avs"), Path("b.m2v"), Path("c.log"), Path("w"), s)
    assert "*BITRATE 6500\n*MAXBITRATE 9000\n" in text
    assert "*AUTOGOP 15" in text and "*COLOUR 5" in text and "*PULLDOWN" not in text
    assert text.endswith("*CHAPTER 2\n1200\n2500\n")


def test_ini_for_ntsc_film_uses_pulldown_and_shorter_gops():
    s = EncodeSettings(bitrate=6000, maxrate=8000, aspect="4:3", standard="ntsc", pulldown=True)
    text = ini_text(Path("a.avs"), Path("b.m2v"), Path("c.log"), Path("w"), s)
    assert "*PULLDOWN" in text and "*AUTOGOP 12" in text and "*COLOUR 6" in text
    assert "*ASPECT 4:3" in text


def _frame_types(m2v: Path) -> list[str]:
    ffprobe = toolchain.find_executable(["ffprobe.exe", "ffprobe"], DIRS)
    out = subprocess.run(
        [str(ffprobe), "-v", "error", "-select_streams", "v", "-show_entries", "frame=pict_type",
         "-of", "csv=p=0", str(m2v)],
        capture_output=True, text=True, check=True,
    ).stdout  # fmt: skip
    return [line.strip().rstrip(",") for line in out.splitlines() if line.strip()]


@pytest.mark.skipif(not READY, reason="HCEnc or DvdSource.dll not installed")
@pytest.mark.parametrize("folder", ["çalışma ğİş", "映画 iş"])
def test_encode_into_non_ascii_folders_with_chapter_keyframes(tmp_path: Path, folder: str):
    clip = pattern_clip(60)
    work = tmp_path / folder
    out = tmp_path / folder / "Film çıktısı.m2v"
    seen = []
    s = EncodeSettings(bitrate=5000, maxrate=8000, aspect="16:9", standard="pal",
                       chapters=[37], profile="fast")  # fmt: skip
    encode(clip, out, s, work, progress=seen.append)
    assert out.stat().st_size > 0
    assert seen[-1] == 1.0
    types = _frame_types(out)
    assert len(types) == 60
    assert types[0] == "I" and types[37] == "I"


def test_ini_for_interlaced_is_tff_not_progressive():
    s = EncodeSettings(bitrate=6000, maxrate=9000, aspect="16:9", standard="pal", interlaced=True)
    text = ini_text(Path("a.avs"), Path("a.m2v"), Path("a.log"), Path("w"), s)
    assert "*TFF" in text and "*PROGRESSIVE" not in text
