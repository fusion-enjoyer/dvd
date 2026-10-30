import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from dvd.cli import app
from dvd.output import burn
from dvd.output.burn import BurnError, Drive, imgburn_command, parse_drives, verify_disc

# Nothing here writes a disc: only the command lines and the read-back are checked.


def test_drives_from_the_imapi2_listing():
    text = ("E:\\|HL-DT-ST DVDRAM GH24NSD1|8,9,10,17,18,19,20,21,26,27,43\n"
            "\n"
            "F:\\|ASUS BW-16D1HT|8,16\n")  # fmt: skip
    drives = parse_drives(text)
    assert drives[0] == Drive(
        "E:\\",
        "HL-DT-ST DVDRAM GH24NSD1",
        ("DVD-R", "DVD-RW", "DVD-R DL", "DVD+RW", "DVD+R", "DVD+R DL"),
    )
    assert drives[0].dual_layer and drives[1].media == ()  # a reader only


def test_imgburn_takes_the_layer_break_file_and_reads_the_disc_back(tmp_path: Path):
    iso = tmp_path / "Film.iso"
    iso.write_bytes(b"")
    exe = Path("C:/Program Files (x86)/ImgBurn/ImgBurn.exe")
    args = imgburn_command(exe, iso, "E:\\", "4")
    assert args[args.index("/SRC") + 1] == str(iso) and args[args.index("/DEST") + 1] == "E:"
    assert args[args.index("/SPEED") + 1] == "4x" and args[args.index("/VERIFY") + 1] == "YES"
    assert "/START" in args and "/CLOSE" in args
    iso.with_suffix(".dvd").write_text("LayerBreak=2084960\nFilm.iso\n", encoding="utf-8")
    args = imgburn_command(exe, iso, "E:", verify=False)
    assert args[args.index("/SRC") + 1] == str(iso.with_suffix(".dvd"))
    assert args[args.index("/SPEED") + 1] == "MAX" and args[args.index("/VERIFY") + 1] == "NO"
    with pytest.raises(BurnError):
        imgburn_command(exe, iso, "E:", "48")
    assert burn.windows_burner_command(iso, "E:\\") == ["isoburn.exe", "/Q", "E:", str(iso)]


def test_verify_disc_compares_every_file(tmp_path: Path):
    built = tmp_path / "VIDEO_TS"
    built.mkdir()
    (built / "VIDEO_TS.IFO").write_bytes(b"ifo" * 1000)
    (built / "VTS_01_1.VOB").write_bytes(bytes(range(256)) * 20_000)
    disc = tmp_path / "disc"
    shutil.copytree(built, disc / "VIDEO_TS")
    seen = []
    assert verify_disc(disc, built, seen.append) == [] and seen[-1] == 1.0
    vob = disc / "VIDEO_TS" / "VTS_01_1.VOB"
    data = bytearray(vob.read_bytes())
    data[3_000_000] ^= 1
    vob.write_bytes(bytes(data))
    (disc / "VIDEO_TS" / "VIDEO_TS.IFO").unlink()
    assert verify_disc(disc, built) == ["VIDEO_TS.IFO is missing on the disc",
                                        "VTS_01_1.VOB: differs from byte 2097152"]  # fmt: skip
    assert verify_disc(tmp_path / "empty", built) == [f"no VIDEO_TS folder on {tmp_path / 'empty'}"]


def test_burn_commands(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(burn, "drives", lambda: [Drive("E:\\", "Yazıcı", ("DVD+R", "DVD+R DL"))])
    runner = CliRunner()
    assert "E:\\  Yazıcı  (DVD+R, DVD+R DL)" in runner.invoke(app, ["drives"]).output
    monkeypatch.setattr(burn, "drives", lambda: [])
    assert "no DVD writer found" in runner.invoke(app, ["drives"]).output
    assert runner.invoke(app, ["burn", str(tmp_path / "yok.iso"), "-d", "E:"]).exit_code == 1
    built = tmp_path / "VIDEO_TS"
    built.mkdir()
    (built / "VIDEO_TS.IFO").write_bytes(b"x")
    shutil.copytree(built, tmp_path / "disc" / "VIDEO_TS")
    out = runner.invoke(app, ["verify-disc", str(tmp_path / "disc"), str(built)])
    assert out.exit_code == 0 and "the disc matches" in out.output
