import ctypes
import struct
import subprocess
import sys
from pathlib import Path

import pytest
import vapoursynth as vs

from dvd import toolchain

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="named pipes are Windows only")

if sys.platform == "win32":
    import _winapi

    from dvd.video import frameserver as fs

core = vs.core
W, H, FRAMES = 720, 576, 30


def pattern_clip(frames: int = FRAMES) -> vs.VideoNode:
    """Diagonal ramps that move with the frame number, so frames differ from each other."""
    base = core.std.BlankClip(format=vs.YUV420P8, width=W, height=H, fpsnum=25, length=frames)

    ramp = bytes(range(256)) * 8

    def draw(n: int, f: vs.VideoFrame) -> vs.VideoFrame:
        out = f.copy()
        for plane, step in ((0, 1), (1, 2), (2, 3)):
            base, stride = out.get_write_ptr(plane).value, out.get_stride(plane)
            w, h = out.width >> (plane > 0), out.height >> (plane > 0)
            for y in range(h):
                start = (y * step + n * 8) % 256
                ctypes.memmove(base + y * stride, ramp[start : start + w], w)
        return out

    return core.std.ModifyFrame(base, base, draw)


def read_exact(handle, size):
    data = b""
    while len(data) < size:
        chunk, _ = _winapi.ReadFile(handle, size - len(data))
        data += chunk
    return data


def connect(path):
    return _winapi.CreateFile(
        path,
        _winapi.GENERIC_READ | _winapi.GENERIC_WRITE,
        0,
        _winapi.NULL,
        _winapi.OPEN_EXISTING,
        0,
        _winapi.NULL,
    )


def test_rejects_non_yv12():
    clip = core.std.BlankClip(format=vs.RGB24, width=W, height=H)
    with pytest.raises(fs.FrameServerError):
        fs.check_clip(clip)


def test_rejects_size_not_divisible_by_8():
    clip = core.std.BlankClip(format=vs.YUV420P8, width=718, height=576)
    with pytest.raises(fs.FrameServerError):
        fs.check_clip(clip)


def test_client_gets_header_and_random_frames():
    clip = pattern_clip()
    frame_size = W * H * 3 // 2
    with fs.FrameServer(clip) as server:
        handle = connect(server.path)
        try:
            magic, version, w, h, num, den, count, fmt = fs.HEADER.unpack(
                read_exact(handle, fs.HEADER.size)
            )
            assert (magic, version, w, h, num, den, count, fmt) == (
                b"DVDF",
                1,
                W,
                H,
                25,
                1,
                FRAMES,
                fs.FORMAT_YV12,
            )
            for n in (7, 0, 29, 7):
                _winapi.WriteFile(handle, struct.pack("<i", n))
                data = read_exact(handle, frame_size)
                with clip.get_frame(n) as expected:
                    assert data == fs.frame_bytes(expected)
            _winapi.WriteFile(handle, struct.pack("<i", -1))
        finally:
            _winapi.CloseHandle(handle)


def test_serves_several_clients_in_turn():
    clip = pattern_clip(5)
    with fs.FrameServer(clip) as server:
        for _ in range(3):
            handle = connect(server.path)
            read_exact(handle, fs.HEADER.size)
            _winapi.WriteFile(handle, struct.pack("<i", 4))
            read_exact(handle, W * H * 3 // 2)
            _winapi.CloseHandle(handle)


DVDSOURCE = toolchain.REPO_TOOLS_DIR / "hcenc" / "DvdSource.dll"


def _psnr_y(m2v: Path, clip: vs.VideoNode) -> float:
    ffmpeg = toolchain.find_executable(["ffmpeg.exe", "ffmpeg"], toolchain.tool_dirs())
    raw = subprocess.run(
        [str(ffmpeg), "-v", "error", "-i", str(m2v), "-f", "rawvideo", "-pix_fmt", "yuv420p", "-"],
        capture_output=True,
        check=True,
    ).stdout
    import math

    frame_size = W * H * 3 // 2
    total, count = 0.0, 0
    for n in range(clip.num_frames):
        decoded = raw[n * frame_size : n * frame_size + W * H]
        with clip.get_frame(n) as f:
            source = memoryview(f[0]).tobytes()
        total += sum((a - b) ** 2 for a, b in zip(decoded[::97], source[::97], strict=True))
        count += len(source[::97])
    mse = total / count
    return 99.0 if mse == 0 else 10 * math.log10(255 * 255 / mse)


@pytest.mark.skipif(not DVDSOURCE.is_file(), reason="DvdSource.dll not built")
def test_hcenc_encodes_frames_served_from_vapoursynth(tmp_path: Path):
    hcenc = toolchain.find_executable(["HCenc_*.exe"], toolchain.tool_dirs())
    if hcenc is None:
        pytest.skip("HCEnc not installed")
    clip = pattern_clip()
    out = tmp_path / "out.m2v"
    with fs.FrameServer(clip) as server:
        avs = tmp_path / "in.avs"
        avs.write_text(f'LoadCPlugin("{DVDSOURCE}")\nDvdSource("{server.name}")\n')
        subprocess.run(
            [
                str(hcenc),
                "-i",
                str(avs),
                "-o",
                str(out),
                "-b",
                "8000",
                "-maxbitrate",
                "9000",
                "-profile",
                "fast",
                "-2pass",
                "-progressive",
                "-silent",
                "-wait",
                "0",
                "-noini",
            ],
            check=True,
            timeout=300,
        )
        assert server.frames_served >= FRAMES
    assert out.stat().st_size > 0
    assert _psnr_y(out, clip) > 30
