from pathlib import Path

import pytest

from dvd.probe import AudioTrack, SourceInfo
from dvd.profiles import (
    ProfileError,
    list_user_profiles,
    load_user_profile,
    resolve,
    save_user_profile,
)
from dvd.project.edit import apply_audio_profile
from dvd.project.model import Audio, Profiles, Title
from dvd.subs.render import DEFAULT_STYLE, style_for


def test_defaults_and_origins():
    r = resolve(Profiles())
    assert r["deband"] == 1 and r.origin["deband"] == "content:modern-film"
    assert r["peak_kbps"] == 9_000 and r.origin["peak_kbps"] == "viewing:modern-tv"
    assert r["dither"] == "error_diffusion" and r.origin["dither"] == "default"


def test_later_layers_win():
    r = resolve(Profiles(content="animasyon-2d", viewing="tasinabilir", audio="tv"))
    assert r["deband"] == 2 and r.origin["deband"] == "viewing:tasinabilir"  # 3 - 1
    assert (r["peak_kbps"], r["subtitle_size"], r["safe_area"]) == (7_500, 1.2, 0.9)
    assert (r["audio_channels"], r["audio_bitrate"]) == ("2.0", 192)
    r = resolve(Profiles(), {"deband": 0, "peak_kbps": "8000k"})
    assert (r["deband"], r["peak_kbps"]) == (0, 8_000)
    assert r.origin["peak_kbps"] == "override"


def test_invalid_values_are_rejected():
    with pytest.raises(ProfileError):
        resolve(Profiles(), {"deband": 7})
    with pytest.raises(ProfileError):
        resolve(Profiles(), {"tone": "warm"})


def test_user_profile_round_trip(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DVD_PROFILE_DIR", str(tmp_path))
    save_user_profile("Yazlık CRT", {"safe_area": 0.85, "subtitle_size": 1.4})
    assert list_user_profiles() == ["Yazlık CRT"]
    assert load_user_profile("Yazlık CRT")["safe_area"] == 0.85
    r = resolve(Profiles(viewing="crt", user="Yazlık CRT"))
    assert r["subtitle_size"] == 1.4 and r.origin["subtitle_size"] == "user:Yazlık CRT"
    assert r["peak_kbps"] == 9_000  # not in the user profile: comes from the viewing layer
    with pytest.raises(ProfileError):
        resolve(Profiles(user="yok"))


def _info():
    tracks = [AudioTrack(1, "truehd", 8, language="eng"), AudioTrack(2, "ac3", 2, language="tur")]
    return SourceInfo(Path("x.mkv"), "matroska", 100.0, 1, audio=tracks)


def test_audio_profiles_reshape_tracks():
    title = Title(source="x.mkv", audio=[
        Audio(track=1, lang="en", default=True),
        Audio(track=2, lang="tr", channels="2.0", bitrate=192),
    ])  # fmt: skip
    apply_audio_profile(title, _info(), resolve(Profiles(audio="tv")))
    assert [(a.track, a.channels, a.bitrate) for a in title.audio] == [
        (1, "2.0", 192),
        (2, "2.0", 192),
    ]
    apply_audio_profile(title, _info(), resolve(Profiles(audio="hepsi")))
    assert [(a.track, a.channels) for a in title.audio] == [(1, "5.1"), (1, "2.0"), (2, "2.0")]
    assert title.audio[0].default and title.audio[0].lang == "en"
    apply_audio_profile(title, _info(), resolve(Profiles(audio="5.1")))
    assert [(a.track, a.channels) for a in title.audio] == [(1, "5.1"), (2, "2.0")]


def test_subtitle_style_follows_viewing():
    r = resolve(Profiles(viewing="crt"))
    style = style_for(r["subtitle_size"], r["safe_area"])
    assert style.size == pytest.approx(DEFAULT_STYLE.size * 1.2)
    assert style.bottom > DEFAULT_STYLE.bottom  # stays inside the overscan-safe area
    assert style_for(1.0, 0.95) == DEFAULT_STYLE
