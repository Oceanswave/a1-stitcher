import pytest

from a1_stitcher.errors import StitchError
from a1_stitcher.media import source_profile


def good():
    stream = dict(
        codec_type="video",
        index=0,
        width=128,
        height=128,
        pix_fmt="yuvj420p",
        color_range="pc",
        color_space="bt709",
        color_transfer="bt709",
        r_frame_rate="30000/1001",
        avg_frame_rate="30000/1001",
        nb_frames="120",
    )
    return {"streams": [stream, {**stream, "index": 1}]}


@pytest.mark.parametrize(
    "field,value",
    [
        ("pix_fmt", "yuv420p10le"),
        ("color_transfer", "arib-std-b67"),
        ("color_space", "bt2020nc"),
        ("color_range", "tv"),
        ("height", 64),
        ("avg_frame_rate", "30/1"),
        ("r_frame_rate", "0/0"),
        ("nb_frames", "0"),
    ],
)
def test_unsupported_profiles_not_silently_converted(monkeypatch, field, value):
    info = good()
    info["streams"][0][field] = value
    monkeypatch.setattr("a1_stitcher.media.probe", lambda path: info)
    with pytest.raises(StitchError):
        source_profile("ignored", {"camera_type": "Antigravity A1"})


def test_audio_is_not_silently_dropped(monkeypatch):
    info = good()
    info["streams"].append({"codec_type": "audio"})
    monkeypatch.setattr("a1_stitcher.media.probe", lambda path: info)
    with pytest.raises(StitchError, match="audio|Audio"):
        source_profile("ignored", {"camera_type": "Antigravity A1"})


def test_matching_two_track_profile_and_unknown_gamma(monkeypatch):
    monkeypatch.setattr("a1_stitcher.media.probe", lambda path: good())
    assert source_profile("ignored", {"camera_type": "Antigravity A1"})["fps"] == "30000/1001"
    with pytest.raises(StitchError, match="gamma"):
        source_profile("ignored", {"camera_type": "Antigravity A1", "gamma_mode": "Log"})


def test_mismatched_track_lengths_rejected(monkeypatch):
    info = good()
    info["streams"][1]["nb_frames"] = "119"
    monkeypatch.setattr("a1_stitcher.media.probe", lambda path: info)
    with pytest.raises(StitchError, match="different"):
        source_profile("ignored", {"camera_type": "Antigravity A1"})
