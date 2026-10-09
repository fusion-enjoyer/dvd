import pytest

from dvd.budget.planner import plan

FILM = 130 * 60


def test_doc_example_dvd9():
    p = plan("dvd9", FILM, [448, 448], subtitle_tracks=2)
    assert p.video_kbps == pytest.approx(7_580, abs=50)  # "≈ 7.5 Mbps video"
    assert p.peak_kbps == 9_000
    assert p.fits and not p.warnings


def test_doc_example_dvd5_warns():
    p = plan("dvd5", FILM, [448, 448], subtitle_tracks=2)
    assert p.video_kbps == pytest.approx(3_760, abs=50)  # "≈ 3.8 Mbps video"
    assert p.fits
    assert "consider DVD-9" in p.warnings[0]


def test_short_film_is_capped_below_peak():
    p = plan("dvd9", 20 * 60, [448])
    assert p.video_kbps == 8_000
    assert p.estimated_bytes < p.capacity_bytes / 3


def test_peak_leaves_room_for_audio_in_mux_limit():
    p = plan("dvd9", FILM, [448] * 8, peak_kbps=9_500)
    assert p.peak_kbps == 10_080 - 8 * 448


def test_requested_peak_is_used():
    assert plan("dvd9", FILM, [448], peak_kbps=7_500).peak_kbps == 7_500


def test_zero_duration_is_an_error():
    with pytest.raises(ValueError):
        plan("dvd5", 0, [])
