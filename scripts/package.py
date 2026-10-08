"""Build the portable app (dist/DVDStudio) and, when Inno Setup is installed, its installer.

    uv run python scripts/package.py [--no-installer]

Layout of dist/DVDStudio:
    DVD Studyo.exe, dvd.exe   launchers (native/launcher)
    python/                   CPython runtime with the app and its locked dependencies
    tools/                    hcenc (+ x86 AviSynth and VC++ runtime), dvdauthor, ffmpeg
    licenses/
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
APP = DIST / "DVDStudio"
MSYS = Path("C:/msys64")
SYSWOW64 = Path("C:/Windows/SysWOW64")
SYSTEM32 = Path("C:/Windows/System32")
PRUNE_DIRS = {"__pycache__", "test", "tests", "idlelib", "tkinter", "turtledemo", "ensurepip",
              "tcl", "include", "libs"}  # fmt: skip
# Parts of PySide6-Essentials the app does not use (QML, Qt tools, headers). Besides size, the
# deep QML paths break installs into long folders (MAX_PATH).
QT_UNUSED_DIRS = ("qml", "include", "metatypes", "typesystems", "glue", "doc", "lib", "scripts")
QT_UNUSED = (
    "Qt6Quick", "Qt6Qml", "Qt6Pdf", "Qt6Designer", "Qt6ShaderTools", "Qt6VirtualKeyboard",
    "Qt6Labs", "Qt6Lottie", "Qt6Help", "Qt6Test", "Qt6UiTools", "Qt6Sql",
    "QtQuick", "QtQml", "QtPdf", "QtDesigner", "QtHelp", "QtTest", "QtUiTools", "QtSql",
)  # fmt: skip


def step(text: str) -> None:
    print(f"== {text}", flush=True)


def run(*args: str | Path, **kw) -> None:
    subprocess.run([str(a) for a in args], check=True, **kw)


def copy_python() -> Path:
    step(f"python runtime from {sys.base_prefix}")
    target = APP / "python"
    shutil.copytree(
        sys.base_prefix,
        target,
        ignore=lambda d, names: [n for n in names if n in PRUNE_DIRS or n.endswith(".pdb")],
    )
    (target / "Lib" / "EXTERNALLY-MANAGED").unlink(missing_ok=True)
    for dll in ("msvcp140.dll", "vcruntime140.dll", "vcruntime140_1.dll"):
        if not (target / dll).exists() and (SYSTEM32 / dll).exists():
            shutil.copy2(SYSTEM32 / dll, target / dll)
    return target / "python.exe"


def install_app(python: Path) -> None:
    step("dependencies (from uv.lock) and the app")
    requirements = DIST / "requirements.txt"
    run("uv", "export", "--no-dev", "--no-hashes", "--no-emit-project", "-o", requirements,
        cwd=ROOT)  # fmt: skip
    run("uv", "pip", "install", "--python", python, "--no-cache", "-r", requirements)
    run("uv", "pip", "install", "--python", python, "--no-cache", "--no-deps", ROOT)
    packages = python.parent / "Lib" / "site-packages"
    qt = packages / "PySide6"
    for name in QT_UNUSED_DIRS:
        shutil.rmtree(qt / name, ignore_errors=True)
    for f in [*qt.glob("*.exe"), *(f for p in QT_UNUSED for f in qt.glob(f"{p}*"))]:
        shutil.rmtree(f) if f.is_dir() else f.unlink()
    for qm in (qt / "translations").glob("*.qm"):
        if not qm.stem.endswith(("_tr", "_en")):
            qm.unlink()
    for tests in [*packages.rglob("tests"), *packages.rglob("test")]:
        if tests.is_dir():
            shutil.rmtree(tests, ignore_errors=True)
    shutil.rmtree(python.parent / "Lib" / "site-packages" / "pip", ignore_errors=True)
    for cache in python.parent.rglob("__pycache__"):
        shutil.rmtree(cache, ignore_errors=True)


def copy_tools() -> None:
    step("tools")
    tools, src = APP / "tools", ROOT / "tools"
    hcenc = tools / "hcenc"
    hcenc.mkdir(parents=True)
    for name in ("HCenc_028.exe", "AviSynth.dll", "DvdSource.dll", "HC.ini", "HC028.pdf"):
        shutil.copy2(src / "hcenc" / name, hcenc / name)
    # The x86 AviSynth.dll needs the 32-bit VC++ runtime; app-local copies are allowed.
    for dll in ("msvcp140.dll", "vcruntime140.dll"):
        if not (SYSWOW64 / dll).exists():
            raise SystemExit(f"missing {SYSWOW64 / dll}: install the x86 VC++ 2015-2022 runtime")
        shutil.copy2(SYSWOW64 / dll, hcenc / dll)
    shutil.copytree(src / "dvdauthor", tools / "dvdauthor")
    # The shared build (exe + DLLs) is about half the size of two static executables.
    ffmpeg_src = src / "ffmpeg"
    if not (ffmpeg_src / "ffmpeg.exe").exists():
        raise SystemExit("tools/ffmpeg is missing; see tools/README.md")
    ffmpeg_dir = tools / "ffmpeg"
    ffmpeg_dir.mkdir()
    for f in ffmpeg_src.iterdir():
        if f.suffix.lower() in (".exe", ".dll") or f.name.upper().startswith("LICENSE"):
            shutil.copy2(f, ffmpeg_dir / f.name)


def build_launchers() -> None:
    step("launchers")
    gcc = MSYS / "ucrt64" / "bin" / "gcc.exe"
    source = ROOT / "native" / "launcher" / "launcher.c"
    common = ["-O2", "-municode", "-static", "-s"]
    env = {**os.environ, "PATH": f"{gcc.parent};{MSYS / 'usr' / 'bin'}"}
    run(gcc, *common, "-DGUI", "-mwindows", "-o", APP / "DVD Studyo.exe", source, env=env)
    run(gcc, *common, "-o", APP / "dvd.exe", source, env=env)


def copy_licenses() -> None:
    step("licenses")
    lic = APP / "licenses"
    lic.mkdir()
    shutil.copy2(ROOT / "LICENSE", lic / "DVD-Studyo-GPL-3.0.txt")
    shutil.copy2(ROOT / "tools" / "avisynthplus" / "gpl.txt", lic / "AviSynthPlus-GPL.txt")
    dvdauthor_copying = ROOT / "build" / "dvdauthor-src" / "COPYING"
    if dvdauthor_copying.exists():
        shutil.copy2(dvdauthor_copying, lic / "dvdauthor-GPL-2.0.txt")
    (lic / "README.txt").write_text(
        "DVD Stüdyo GPL-3.0-or-later lisanslıdır.\n"
        "Birlikte gelen araçlar: FFmpeg (GPL, gyan.dev derlemesi), dvdauthor/spumux (GPL-2.0+),\n"
        "AviSynth+ (GPL-2.0+), VapourSynth (LGPL-2.1), BestSource (MIT), Qt/PySide6 (LGPL-3.0),\n"
        "HCEnc 0.28 (freeware, hank315.nl), fontlar (SIL OFL 1.1, uygulama klasöründe).\n"
        "Kaynak kod: https://github.com/fusion-enjoyer/dvd\n",
        encoding="utf-8",
    )


def smoke_test() -> None:
    step("smoke test: dvd doctor with a clean PATH")
    env = {"PATH": str(SYSTEM32), "SYSTEMROOT": "C:\\Windows"}
    out = subprocess.run([APP / "dvd.exe", "doctor"], env=env, capture_output=True, text=True,
                         encoding="utf-8")  # fmt: skip
    print(out.stdout)
    if out.returncode != 0:
        raise SystemExit("packaged app is missing a required tool")
    for line in out.stdout.splitlines():
        if line.startswith("ok") and "DVDStudio" not in line and "VapourSynth" not in line:
            raise SystemExit(f"tool found outside the package: {line}")
    step("smoke test: open the main window offscreen")
    script = (
        "from PySide6.QtWidgets import QApplication;"
        "from dvd.gui.theme import load_fonts;from dvd.gui.main_window import MainWindow;"
        "app=QApplication([]);load_fonts();w=MainWindow();w.show();app.processEvents();"
        "w.set_mode('pro');app.processEvents();print('window ok')"
    )
    env["QT_QPA_PLATFORM"] = "offscreen"
    out = subprocess.run([APP / "python" / "python.exe", "-c", script], env=env,
                         capture_output=True, text=True)  # fmt: skip
    print(out.stdout, out.stderr[-2000:])
    if "window ok" not in out.stdout:
        raise SystemExit("the packaged app cannot open its window")


def build_installer() -> None:
    iscc = shutil.which("ISCC") or next(
        (str(p) for p in (Path.home() / "AppData/Local/Programs/Inno Setup 6/ISCC.exe",
                          Path("C:/Program Files (x86)/Inno Setup 6/ISCC.exe")) if p.exists()),
        None,
    )  # fmt: skip
    if iscc is None:
        print("Inno Setup not found; skipping the installer (winget install JRSoftware.InnoSetup)")
        return
    step("installer")
    from dvd import __version__

    run(iscc, f"/DAppVersion={__version__}", f"/DSourceDir={APP}", f"/DOutputDir={DIST}",
        ROOT / "installer" / "dvdstudio.iss")  # fmt: skip


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-installer", action="store_true")
    args = parser.parse_args()
    shutil.rmtree(APP, ignore_errors=True)
    APP.mkdir(parents=True)
    python = copy_python()
    install_app(python)
    copy_tools()
    build_launchers()
    copy_licenses()
    smoke_test()
    if not args.no_installer:
        build_installer()
    size = sum(f.stat().st_size for f in APP.rglob("*") if f.is_file())
    print(f"done: {APP} ({size / 1e6:.0f} MB)")


if __name__ == "__main__":
    main()
