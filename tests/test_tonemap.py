import subprocess
from pathlib import Path

import numpy as np
import pytest
import vapoursynth as vs

from dvd import toolchain
from dvd.video.tonemap import eetf_nits, pq, tonemap

core = vs.core
FFMPEG = toolchain.find_executable(["ffmpeg.exe", "ffmpeg"], toolchain.tool_dirs())


def test_eetf_keeps_dark_tones_and_lands_the_peak_on_sdr_white():
    assert eetf_nits(5, 1000) == pytest.approx(5, rel=0.01)  # below the knee: unchanged
    assert eetf_nits(1000, 1000) == pytest.approx(100, rel=0.01)
    outs = [eetf_nits(n, 1000) for n in (50, 100, 203, 400, 1000)]
    assert outs == sorted(outs) and outs[-1] <= 100.5
    assert eetf_nits(4000, 4000) == pytest.approx(100, rel=0.01)


def test_vapoursynth_curve_matches_the_reference():
    nits = [1, 20, 100, 203, 500, 1000]
    rows = [core.std.BlankClip(format=vs.YUV444PS, width=8, height=2, length=1,
                               color=[pq(n), 0, 0]) for n in nits]  # fmt: skip
    clip = core.std.StackVertical(rows)
    out = tonemap(clip, "smpte2084", "709", vs.YUV444P16, 1000, range_in="full")
    luma = np.asarray(out.get_frame(0)[0]).astype(float)[::2, 0]
    shown = ((luma - 4096) / (60160 - 4096)).clip(0) ** 2.4 * 100  # BT.1886 display, 100 nits
    expected = [eetf_nits(n, 1000) for n in nits]
    assert shown == pytest.approx(expected, rel=0.03, abs=0.2)


@pytest.mark.skipif(FFMPEG is None, reason="ffmpeg not installed")
def test_hdr10_source_builds_a_normal_looking_sdr_disc(tmp_path: Path):
    from dvd.build import build
    from dvd.probe import probe
    from dvd.project import new_project, save

    def make(name: str, hdr: bool) -> Path:
        out = tmp_path / name
        to_pq = ("zscale=tin=bt709:min=bt709:pin=bt709:t=smpte2084:m=2020_ncl:p=2020:npl=100,"
                 "format=yuv420p10le")  # fmt: skip
        opts = (["-vf", to_pq, "-c:v", "libx265", "-x265-params",
                 "log-level=error:colorprim=bt2020:transfer=smpte2084:colormatrix=bt2020nc:"
                 "max-cll=1000,400:master-display=G(13250,34500)B(7500,3000)R(34000,16000)"
                 "WP(15635,16450)L(10000000,1)"]
                if hdr else ["-c:v", "libx264", "-colorspace", "bt709"])  # fmt: skip
        subprocess.run([str(FFMPEG), "-v", "error", "-y", "-f", "lavfi",
                        "-i", "testsrc2=size=1280x720:rate=25:duration=2", *opts,
                        "-preset", "ultrafast", str(out)], check=True)  # fmt: skip
        return out

    means = []
    for name, hdr in (("hdr.mkv", True), ("sdr.mkv", False)):
        info = probe(make(name, hdr))
        assert info.main_video.hdr == hdr
        if hdr:
            assert info.main_video.hdr_peak == 1000
        folder = tmp_path / name.split(".")[0]
        folder.mkdir()
        project_file = folder / "p.dvd.yaml"
        project = new_project(info, folder)
        project.titles[0].source = info.path.as_posix()
        project.titles[0].video.overrides = {"encoder": "ffmpeg"}
        save(project, project_file)
        build(project_file, make_iso=False)
        m2v = next(folder.rglob("t01.m2v"))
        with core.bs.VideoSource(str(m2v)).get_frame(25) as f:
            means.append(float(np.asarray(f[0]).mean()))
    # 100-nit SDR white sits in the knee and comes out a little darker; same picture otherwise.
    assert means[0] == pytest.approx(means[1], rel=0.2)
