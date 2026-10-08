"""Serve VapourSynth frames to 32-bit AviSynth consumers (HCEnc) over a Windows named pipe.

The client side is the DvdSource AviSynth plugin (native/dvdsource). Each client connection
gets a header describing the clip, then sends frame numbers and receives raw YV12 planes.
Frames are fetched by number, so encoders may seek and run several passes.
"""

from __future__ import annotations

import _winapi
import struct
import threading
import uuid

import vapoursynth as vs

PROTOCOL_VERSION = 1
FORMAT_YV12 = 1
HEADER = struct.Struct("<4sIiiIIiI")
REQUEST = struct.Struct("<i")
_PIPE_BUFFER = 1 << 20
_ERROR_PIPE_CONNECTED = 535
# Not exported by _winapi; both are zero in the Windows headers.
_PIPE_TYPE_BYTE = 0x0
_PIPE_READMODE_BYTE = 0x0


class FrameServerError(Exception):
    pass


def pack_header(clip: vs.VideoNode) -> bytes:
    return HEADER.pack(
        b"DVDF",
        PROTOCOL_VERSION,
        clip.width,
        clip.height,
        clip.fps.numerator,
        clip.fps.denominator,
        clip.num_frames,
        FORMAT_YV12,
    )


def frame_bytes(frame: vs.VideoFrame) -> bytes:
    """Y, U and V planes of a YUV420P8 frame, rows packed without padding."""
    return b"".join(memoryview(frame[plane]).tobytes() for plane in range(3))


def check_clip(clip: vs.VideoNode) -> None:
    if clip.format is None or clip.format.id != vs.YUV420P8:
        raise FrameServerError("clip must be YUV420P8")
    if clip.width == 0 or clip.height == 0 or clip.fps.numerator == 0:
        raise FrameServerError("clip must have constant size and frame rate")
    if clip.width % 8 or clip.height % 8:
        raise FrameServerError("width and height must be divisible by 8 for MPEG-2")


def _read_exact(handle: int, size: int) -> bytes:
    chunks = []
    while size > 0:
        data, _ = _winapi.ReadFile(handle, size)
        if not data:
            raise BrokenPipeError
        chunks.append(data)
        size -= len(data)
    return b"".join(chunks)


def _write_all(handle: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        written, _ = _winapi.WriteFile(handle, view)
        view = view[written:]


class FrameServer:
    """Serves one clip on ``\\\\.\\pipe\\<name>`` until stopped; any number of clients."""

    def __init__(self, clip: vs.VideoNode, name: str | None = None) -> None:
        check_clip(clip)
        self.clip = clip
        self.name = name or f"dvd-{uuid.uuid4().hex[:12]}"
        self.path = rf"\\.\pipe\{self.name}"
        self.frames_served = 0
        self._header = pack_header(clip)
        self._stopping = threading.Event()
        self._listening = threading.Event()
        self._accept_thread: threading.Thread | None = None

    def __enter__(self) -> FrameServer:
        self.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.stop()

    def start(self) -> None:
        self._accept_thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._accept_thread.start()
        if not self._listening.wait(timeout=5):
            raise FrameServerError(f"could not create pipe {self.path}")

    def stop(self) -> None:
        self._stopping.set()
        # Unblock ConnectNamedPipe with a throwaway connection.
        try:
            h = _winapi.CreateFile(
                self.path,
                _winapi.GENERIC_READ | _winapi.GENERIC_WRITE,
                0,
                _winapi.NULL,
                _winapi.OPEN_EXISTING,
                0,
                _winapi.NULL,
            )
            _winapi.CloseHandle(h)
        except OSError:
            pass
        if self._accept_thread:
            self._accept_thread.join(timeout=5)

    def _accept_loop(self) -> None:
        while not self._stopping.is_set():
            handle = _winapi.CreateNamedPipe(
                self.path,
                _winapi.PIPE_ACCESS_DUPLEX,
                _PIPE_TYPE_BYTE | _PIPE_READMODE_BYTE | _winapi.PIPE_WAIT,
                _winapi.PIPE_UNLIMITED_INSTANCES,
                _PIPE_BUFFER,
                _PIPE_BUFFER,
                _winapi.NMPWAIT_WAIT_FOREVER,
                _winapi.NULL,
            )
            self._listening.set()
            try:
                _winapi.ConnectNamedPipe(handle, False)
            except OSError as exc:
                if getattr(exc, "winerror", None) != _ERROR_PIPE_CONNECTED:
                    _winapi.CloseHandle(handle)
                    raise
            if self._stopping.is_set():
                _winapi.CloseHandle(handle)
                return
            threading.Thread(target=self._serve_client, args=(handle,), daemon=True).start()

    def _serve_client(self, handle: int) -> None:
        try:
            _write_all(handle, self._header)
            while True:
                (n,) = REQUEST.unpack(_read_exact(handle, REQUEST.size))
                if n < 0:
                    return
                n = min(n, self.clip.num_frames - 1)
                with self.clip.get_frame(n) as frame:
                    _write_all(handle, frame_bytes(frame))
                self.frames_served += 1
        except (BrokenPipeError, OSError):
            return
        finally:
            _winapi.CloseHandle(handle)
