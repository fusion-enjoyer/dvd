import subprocess
from pathlib import Path

import pytest

from dvd import toolchain
from dvd.probe import Chapter, probe
from dvd.project.edit import chapter_times, format_time, set_manual_chapters
from dvd.project.model import ChapterEvery, Title

FFMPEG = toolchain.find_executable(["ffmpeg.exe", "ffmpeg"], toolchain.tool_dirs())


class _Info:
    duration = 600.0
    chapters = [Chapter(0, 100), Chapter(100, 400), Chapter(400, 600)]


def test_chapter_times_for_every_kind_of_setting():
    title = Title(source="x.mkv")
    assert chapter_times(title, _Info()) == [0, 100, 400]
    title.chapters = ChapterEvery(every=4)
    assert chapter_times(title, _Info()) == [0, 240, 480]
    assert chapter_times(title, _Info(), speedup=1.25) == [0, 300]  # 4 disc minutes = 5 source
    title.chapters = "none"
    assert chapter_times(title, _Info()) == [0]
    set_manual_chapters(title, [125.5, 30, 30, 0.0004])
    assert title.chapters == ["0:00:00.000", "0:00:30.000", "0:02:05.500"]
    assert chapter_times(title, _Info()) == [0, 30, 125.5]
    assert format_time(3725.25) == "1:02:05.250"


@pytest.mark.skipif(FFMPEG is None, reason="ffmpeg not installed")
def test_suggestions_land_on_scene_cuts(tmp_path: Path):
    from dvd.video.scenes import suggest_chapters

    # Four shots of different colours: cuts at 5.0, 11.2 and 16.0 s.
    src = tmp_path / "sahne.mkv"
    shots = [("red", 5.0), ("yellow", 6.2), ("blue", 4.8), ("white", 4.0)]  # distinct luma
    inputs = []
    for color, length in shots:
        inputs += ["-f", "lavfi", "-i", f"color=c={color}:s=320x180:r=25:d={length}"]
    joined = "".join(f"[{i}:v]" for i in range(len(shots))) + f"concat=n={len(shots)}:v=1"
    subprocess.run([str(FFMPEG), "-v", "error", "-y", *inputs, "-filter_complex", joined,
                    "-c:v", "libx264", "-preset", "ultrafast", str(src)], check=True)  # fmt: skip
    info = probe(src)
    times = suggest_chapters(src, info.main_video, 20.0, every_minutes=0.1, window=2.5)
    # Wanted 6 and 12 s; the nearest cuts are 5.0 and 11.2. 18 s is too close to the end.
    assert times == pytest.approx([0, 5.0, 11.2], abs=0.05)
