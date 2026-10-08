from fractions import Fraction
from pathlib import Path

import pytest

from dvd.probe import parse
from dvd.project import ProjectError, dumps, load, new_project, save, source_path, suggest_standard
from dvd.project.model import parse_timecode

ARCHITECTURE_EXAMPLE = """\
disc:
  name: "Interstellar"
  standard: pal              # pal | ntsc
  media: dvd9                # dvd5 | dvd9
  profiles:
    content: grenli-film
    viewing: modern-tv
    audio: "5.1"

titles:
  - source: "D:/Rips/Interstellar.mkv"
    video:
      crop: auto
      overrides: { deband: 3 }
    audio:
      - { track: 1, lang: en, codec: ac3, channels: "5.1", bitrate: 448k }
      - { track: 3, lang: tr, codec: ac3, channels: "5.1", bitrate: 448k }
    subtitles:
      - { file: "Interstellar.tr.srt", lang: tr, style: varsayilan, default: true }
    chapters: from-source

menus:
  template: sinematik
  pages: [main, chapters, settings]
  background: { frame: "01:12:03" }

first_play: [ { intro: "logo.mkv", skippable: true }, main_menu ]
"""


def write(tmp_path: Path, text: str, name: str = "film.dvd.yaml") -> Path:
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def errors_for(tmp_path: Path, text: str) -> str:
    with pytest.raises(ProjectError) as exc:
        load(write(tmp_path, text))
    return str(exc.value)


MINIMAL = """\
disc: {{name: Deneme, standard: pal}}
titles:
  - source: film.mkv
{extra}
"""


def test_architecture_example_loads(tmp_path: Path):
    project = load(write(tmp_path, ARCHITECTURE_EXAMPLE))
    assert project.disc.profiles.content == "grenli-film"
    title = project.titles[0]
    assert title.video.overrides == {"deband": 3}
    assert [a.bitrate for a in title.audio] == [448, 448]
    assert title.subtitles[0].default
    assert project.menus["template"] == "sinematik"


def test_round_trip_keeps_everything(tmp_path: Path):
    project = load(write(tmp_path, ARCHITECTURE_EXAMPLE))
    again = load(write(tmp_path, dumps(project), "again.dvd.yaml"))
    assert again == project
    assert "bitrate: 448k" in dumps(project)


def test_save_is_utf8_and_replaces_atomically(tmp_path: Path):
    project = load(write(tmp_path, ARCHITECTURE_EXAMPLE))
    project.disc.name = "Yüzüklerin Efendisi: Kralın Dönüşü"
    target = tmp_path / "çıktı" / "proje.dvd.yaml"
    save(project, target)
    save(project, target)
    assert "Kralın Dönüşü" in target.read_text(encoding="utf-8")
    assert [p.name for p in target.parent.iterdir()] == ["proje.dvd.yaml"]


def test_typo_in_key_is_reported(tmp_path: Path):
    text = "disc: {name: X, standart: pal}\ntitles: [{source: a.mkv}]\n"
    message = errors_for(tmp_path, text)
    assert "disc.standart" in message
    assert "disc.standard" in message  # the missing required key


def test_ac3_bitrate_limit(tmp_path: Path):
    extra = "    audio: [{track: 1, lang: tr, bitrate: 640k}]"
    message = errors_for(tmp_path, MINIMAL.format(extra=extra))
    assert "titles[0].audio[0].bitrate" in message
    assert "448k" in message


def test_three_letter_language_codes_are_converted(tmp_path: Path):
    extra = (
        "    audio: [{track: 1, lang: tur}, {track: 2, lang: eng, channels: '2.0', bitrate: 192k}]"
    )
    project = load(write(tmp_path, MINIMAL.format(extra=extra)))
    assert [a.lang for a in project.titles[0].audio] == ["tr", "en"]


def test_unknown_language_is_rejected(tmp_path: Path):
    extra = "    audio: [{track: 1, lang: turkish}]"
    assert "two-letter" in errors_for(tmp_path, MINIMAL.format(extra=extra))


def test_dvd_track_limits(tmp_path: Path):
    tracks = ", ".join(f"{{track: {i}, lang: tr}}" for i in range(9))
    message = errors_for(tmp_path, MINIMAL.format(extra=f"    audio: [{tracks}]"))
    assert "titles[0].audio" in message


def test_only_one_default_audio(tmp_path: Path):
    extra = "    audio: [{track: 1, lang: tr, default: true}, {track: 2, lang: en, default: true}]"
    assert "only one audio" in errors_for(tmp_path, MINIMAL.format(extra=extra))


def test_subtitle_needs_exactly_one_source(tmp_path: Path):
    extra = "    subtitles: [{file: a.srt, track: 3, lang: tr}]"
    assert "either 'file' or 'track'" in errors_for(tmp_path, MINIMAL.format(extra=extra))


def test_chapter_list_must_increase(tmp_path: Path):
    extra = "    chapters: ['0:00', '12:00', '5:00']"
    assert "increasing" in errors_for(tmp_path, MINIMAL.format(extra=extra))


def test_chapter_options(tmp_path: Path):
    project = load(write(tmp_path, MINIMAL.format(extra="    chapters: {every: 5}")))
    assert project.titles[0].chapters.every == 5


def test_invalid_yaml_message(tmp_path: Path):
    assert "not valid YAML" in errors_for(tmp_path, "disc: [unclosed")


def test_parse_timecode():
    assert parse_timecode("1:02:03.5") == pytest.approx(3723.5)
    assert parse_timecode("12:00") == 720
    with pytest.raises(ValueError):
        parse_timecode("1:75:00")


@pytest.mark.parametrize(
    ("fps", "standard"),
    [
        (Fraction(25), "pal"),
        (Fraction(50), "pal"),
        (Fraction(30000, 1001), "ntsc"),
        (Fraction(60000, 1001), "ntsc"),
        (Fraction(24000, 1001), "pal"),
        (Fraction(24), "pal"),
        (None, "pal"),
    ],
)
def test_suggest_standard(fps, standard):
    assert suggest_standard(fps)[0] == standard


def bluray_info(path: Path, duration: str = "10140"):
    return parse(
        {
            "format": {"format_name": "matroska,webm", "duration": duration,
                       "tags": {"title": "Interstellar"}},
            "streams": [
                {"index": 0, "codec_type": "video", "codec_name": "h264", "width": 1920,
                 "height": 1080, "r_frame_rate": "24000/1001", "avg_frame_rate": "24000/1001"},
                {"index": 1, "codec_type": "audio", "codec_name": "truehd", "channels": 8,
                 "tags": {"language": "eng"}},
                {"index": 2, "codec_type": "audio", "codec_name": "ac3", "channels": 2,
                 "tags": {"language": "tur"}, "disposition": {"default": 1}},
                {"index": 3, "codec_type": "subtitle", "codec_name": "subrip",
                 "tags": {"language": "tur"}},
                {"index": 4, "codec_type": "subtitle", "codec_name": "hdmv_pgs_subtitle",
                 "tags": {"language": "eng"}},
            ],
            "chapters": [{"start_time": "0", "end_time": "600", "tags": {"title": "1"}}],
        },
        path,
    )  # fmt: skip


def test_new_project_from_bluray_source(tmp_path: Path):
    source = tmp_path / "rips" / "Interstellar.mkv"
    project = new_project(bluray_info(source), tmp_path)
    assert project.disc.name == "Interstellar"
    assert project.disc.standard == "pal"
    assert project.disc.media == "dvd9"
    title = project.titles[0]
    assert title.source == "rips/Interstellar.mkv"
    assert [(a.track, a.lang, a.channels, a.bitrate, a.default) for a in title.audio] == [
        (1, "en", "5.1", 448, False),
        (2, "tr", "2.0", 192, True),
    ]
    # PGS needs Phase 3 (bitmap re-scaling); only text subtitles are taken for now.
    assert [(s.track, s.lang) for s in title.subtitles] == [(3, "tr")]
    assert title.chapters == "from-source"
    assert source_path(tmp_path / "film.dvd.yaml", title) == source.resolve()


def test_short_source_goes_on_dvd5(tmp_path: Path):
    project = new_project(bluray_info(tmp_path / "kisa.mkv", duration="1800"), tmp_path)
    assert project.disc.media == "dvd5"


def test_source_on_another_drive_is_absolute(tmp_path: Path):
    title = new_project(bluray_info(Path("Z:/filmler/x.mkv")), tmp_path).titles[0]
    assert title.source == "Z:/filmler/x.mkv"


def test_check_sources_reports_missing_tracks_and_files(tmp_path: Path):
    from dvd.project.check import check_sources

    source = tmp_path / "film.mkv"
    source.write_bytes(b"")
    text = MINIMAL.format(
        extra="    audio: [{track: 1, lang: en}, {track: 3, lang: tr}]\n"
        "    subtitles: [{track: 2, lang: tr}, {file: yok.srt, lang: tr}]"
    )
    project_file = write(tmp_path, text)
    problems = check_sources(load(project_file), project_file, lambda p: bluray_info(p))
    assert len(problems) == 3
    assert problems[0].startswith("titles[0].audio[1].track: stream 3 is not an audio track")
    assert problems[1].startswith("titles[0].subtitles[0].track: stream 2")
    assert "yok.srt" in problems[2]


def test_check_sources_missing_source(tmp_path: Path):
    from dvd.project.check import check_sources

    project_file = write(tmp_path, MINIMAL.format(extra=""))
    problems = check_sources(load(project_file), project_file)
    assert problems == [f"titles[0].source: file not found: {tmp_path / 'film.mkv'}"]


def test_turkish_subtitle_is_on_when_main_audio_is_not_turkish(tmp_path: Path):
    info = bluray_info(tmp_path / "x.mkv")
    import dataclasses

    english_first = dataclasses.replace(
        info, audio=[dataclasses.replace(a, default=(a.index == 1)) for a in info.audio]
    )
    assert new_project(english_first, tmp_path).titles[0].subtitles[0].default
    assert not new_project(info, tmp_path).titles[0].subtitles[0].default  # Turkish audio


def test_estimate_uses_pal_playback_duration(tmp_path: Path):
    from dvd.budget.planner import plan
    from dvd.build import estimate

    info = bluray_info(tmp_path / "x.mkv")  # 169 min at 23.976 fps
    project = new_project(info, tmp_path)
    p = estimate(project, [info])
    assert p.duration == pytest.approx(10140 / (25 / (24000 / 1001)), rel=1e-6)
    assert p.video_kbps == plan("dvd9", p.duration, [448 + 192], 1).video_kbps
