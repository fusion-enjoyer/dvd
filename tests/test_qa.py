import subprocess
from fractions import Fraction
from pathlib import Path

import pytest

from dvd import toolchain
from dvd.probe import probe
from dvd.project import new_project, save
from dvd.qa.metrics import FrameScore, Measurement

DIRS = toolchain.tool_dirs()
FFMPEG = toolchain.find_executable(["ffmpeg.exe", "ffmpeg"], DIRS)
READY = FFMPEG is not None and all(
    toolchain.find_executable([p], DIRS) for p in ("HCenc_*.exe", "DvdSource.dll")
)


def scores(values):
    m = Measurement(Fraction(25))
    m.scores = [FrameScore(i, 40.0, v) for i, v in enumerate(values)]
    return m


def test_summary_statistics():
    m = scores([90.0] * 90 + [50.0] * 10)
    assert m.mean("ssimu2") == pytest.approx(86.0)
    assert m.percentile("ssimu2", 5) == 50.0


def test_worst_scenes_do_not_overlap():
    values = [90.0] * 200
    values[100:125] = [40.0] * 25  # one bad second
    values[10:20] = [70.0] * 10
    worst = scores(values).worst_scenes(count=2, seconds=1.0)
    assert worst[0].start == 100 and worst[0].ssimu2 == pytest.approx(40.0)
    assert worst[1].end <= 100 or worst[1].start >= 125
    assert worst[0].timecode(Fraction(25)) == "0:00:04"


@pytest.mark.skipif(not READY, reason="toolchain not installed")
def test_trial_encode_scores_lower_at_a_lower_bitrate(tmp_path: Path):
    from dvd.qa.trial import trial_encode

    src = tmp_path / "deneme.mkv"
    subprocess.run(
        [str(FFMPEG), "-v", "error", "-y", "-f", "lavfi",
         "-i", "testsrc2=size=1920x1080:rate=25:duration=6",
         "-vf", "noise=alls=25:allf=t", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "12",
         str(src)],
        check=True,
    )  # fmt: skip
    project_file = tmp_path / "deneme.dvd.yaml"
    save(new_project(probe(src), tmp_path), project_file)
    good = trial_encode(project_file, at=1.0, seconds=3, out_dir=tmp_path / "iyi")
    assert good.frames == 75 and len(good.measurement.scores) == 75
    assert good.reference_png.is_file() and good.encoded_png.is_file()
    poor = trial_encode(project_file, at=1.0, seconds=3, out_dir=tmp_path / "zayif",
                        video_kbps=2500)  # fmt: skip
    assert poor.video_kbps == 2500
    assert good.measurement.mean("ssimu2") > poor.measurement.mean("ssimu2") + 5
    assert good.measurement.mean("xpsnr") > poor.measurement.mean("xpsnr") + 1
