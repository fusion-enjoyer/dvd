from pathlib import Path

from dvd import toolchain


def test_parse_version_ffmpeg():
    text = "ffmpeg version 9.0.1-full_build-www.gyan.dev Copyright (c) 2000-2026"
    assert toolchain.parse_version(text, r"ffmpeg version (\S+)") == "9.0.1-full_build-www.gyan.dev"


def test_parse_version_dvdauthor():
    text = "DVDAuthor::dvdauthor, version 0.7.2.\nBuild options: gnugetopt"
    assert toolchain.parse_version(text, r"version (\d+\.\d+\.\d+)") == "0.7.2"


def test_parse_version_missing():
    assert toolchain.parse_version("no version here", r"version (\d+)") is None


def test_find_executable_in_subfolder(tmp_path: Path, monkeypatch):
    (tmp_path / "hcenc").mkdir()
    exe = tmp_path / "hcenc" / "HCenc_028.exe"
    exe.write_bytes(b"")
    monkeypatch.setenv("DVD_TOOLS_DIR", str(tmp_path))

    found = toolchain.find_executable(["HCenc_*.exe"], toolchain.tool_dirs())

    assert found == exe


def test_hcenc_version_from_file_name(tmp_path: Path, monkeypatch):
    (tmp_path / "HCenc_028.exe").write_bytes(b"")
    monkeypatch.setenv("DVD_TOOLS_DIR", str(tmp_path))
    hcenc = next(t for t in toolchain.EXE_TOOLS if t.name == "HCEnc")

    status = toolchain.check_exe(hcenc, toolchain.tool_dirs())

    assert status.found
    assert status.version == "028"


def test_missing_tool_reports_not_found(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DVD_TOOLS_DIR", str(tmp_path))
    monkeypatch.setenv("PATH", str(tmp_path))
    tool = toolchain.ExeTool("x", "test", True, ("definitely-not-a-tool-xyz",))

    status = toolchain.check_exe(tool, toolchain.tool_dirs())

    assert not status.found
    assert status.required
