import struct
from copy import deepcopy

import pytest
from conftest import pb, trailer
from test_media import good

from a1_stitcher.errors import StitchError
from a1_stitcher.insv import InsvReader
from a1_stitcher.media import source_profile
from a1_stitcher.modes import recording_mode, require_recording_mode


@pytest.mark.parametrize(
    "uav,group,name",
    [
        (0, 0, "standard-video"),
        (1, 3, "standard-photo"),
        (2, 2, "timelapse"),
        (4, 17, "slow-motion"),
        (5, 4, "hdr-photo"),
        (6, 7, "burst-photo"),
        (7, 28, "aeb-photo"),
    ],
)
def test_mode_identifiers_are_decoded_and_inspectable(tmp_path, uav, group, name):
    path = tmp_path / "original.insv"
    path.write_bytes(trailer([(1, pb(2, "Antigravity A1") + pb(153, uav) + pb(26, pb(1, group)))]))
    info = InsvReader(path).inspect()
    assert info["recording_mode"]["name"] == name
    assert 153 not in info["metadata"]["unknown_protobuf_field_numbers"]
    assert info["metadata"]["file_group_type"] == group


def test_inspect_reports_timelapse_despite_unsupported_exposure_cadence(tmp_path):
    path = tmp_path / "interval.insv"
    path.write_bytes(
        trailer(
            [
                (1, pb(2, "Antigravity A1") + pb(153, 2) + pb(24, 0)),
                (4, struct.pack("<QdQd", 0, 0.1, 2_000_000, 0.1)),
            ]
        )
    )
    info = InsvReader(path).inspect()
    assert info["recording_mode"]["name"] == "timelapse"
    assert info["exposure"]["supported"] is False
    assert "cadence" in info["exposure"]["reason"]


@pytest.mark.parametrize(
    "payload",
    [
        pb(153, b"wrong"),
        pb(153, 0) + pb(153, 4),
        pb(26, pb(1, b"wrong")),
        pb(26, pb(1, 0) + pb(1, 17)),
    ],
)
def test_malformed_or_ambiguous_mode_metadata_is_rejected(tmp_path, payload):
    path = tmp_path / "bad.insv"
    path.write_bytes(trailer([(1, pb(2, "Antigravity A1") + payload)]))
    with pytest.raises(ValueError):
        InsvReader(path).metadata()


@pytest.mark.parametrize(
    "meta,name",
    [
        ({"uav_camera_mode": 2}, "timelapse"),
        ({"file_group_type": 8}, "timelapse"),
        ({"file_group_type": 17}, "slow-motion"),
        ({"uav_camera_mode": 4}, "slow-motion"),
        ({"uav_camera_mode": 99}, "unknown"),
        ({"uav_camera_mode": 0, "file_group_type": 17}, "conflicting"),
        ({"uav_camera_mode": 1}, "standard-photo"),
    ],
)
def test_retimed_unknown_and_wrong_media_are_not_treated_as_normal_video(monkeypatch, meta, name):
    monkeypatch.setattr("a1_stitcher.media.probe", lambda path: good())
    with pytest.raises(StitchError, match=name):
        source_profile("unused", {"camera_type": "Antigravity A1", **meta})


@pytest.mark.parametrize(
    "meta",
    [
        {"hdr_state": 1},
        {"hdr_mode": 2},
        {"ultra_hdr_enabled": 1},
        {"video_bit_depth": 2},
        {"video_bit_depth": 99},
    ],
)
def test_hdr_and_depth_declarations_cannot_bypass_pixel_checks(monkeypatch, meta):
    monkeypatch.setattr("a1_stitcher.media.probe", lambda path: good())
    with pytest.raises(StitchError, match="HDR|bit-depth"):
        source_profile("unused", {"camera_type": "Antigravity A1", **meta})


@pytest.mark.parametrize("mode", [5, 6, 7, 8, 9])
def test_grouped_photos_do_not_silently_become_single_normal_photos(mode):
    with pytest.raises(StitchError, match="grouped capture"):
        require_recording_mode({"uav_camera_mode": mode}, "photo")


def test_absent_mode_stays_unspecified_instead_of_claiming_standard():
    assert recording_mode({})["name"] == "unspecified"
    assert require_recording_mode({}, "video")["declarations"] == {}
    with pytest.raises(StitchError, match="Invalid"):
        recording_mode({"uav_camera_mode": True})


# This checks the input contract, not native-resolution image quality. Include
# fractional rates observed on A1 alongside the marketed integer rates.
STANDARD_RATES = [
    (3840, "30", 30),
    (3840, "30000/1001", 30),
    (3840, "25", 25),
    (3840, "24", 24),
    (3840, "24000/1001", 24),
    (2624, "60", 60),
    (2624, "60000/1001", 60),
    (2624, "50", 50),
    (2624, "30", 30),
    (2624, "30000/1001", 30),
    (2624, "25", 25),
    (2624, "24", 24),
    (2624, "24000/1001", 24),
    (1920, "100", 100),
]


@pytest.mark.parametrize("width,rate,nominal", STANDARD_RATES)
@pytest.mark.parametrize("codec", ["h264", "hevc"])
def test_standard_a1_resolution_rate_and_codec_contract(monkeypatch, width, rate, nominal, codec):
    info = deepcopy(good())
    for s in info["streams"]:
        s.update(
            width=width, height=width, r_frame_rate=rate, avg_frame_rate=rate, codec_name=codec
        )
    monkeypatch.setattr("a1_stitcher.media.probe", lambda path: info)
    result = source_profile(
        "unused",
        dict(
            camera_type="Antigravity A1",
            uav_camera_mode=0,
            file_group_type=0,
            frame_rate_nominal=nominal,
        ),
    )
    assert result["width"] == width
    assert result["recording_mode"]["name"] == "standard-video"


@pytest.mark.parametrize("nominal", [100, 60, 25, 0, True])
def test_capture_playback_mismatch_does_not_silently_retime_telemetry(monkeypatch, nominal):
    monkeypatch.setattr("a1_stitcher.media.probe", lambda path: good())
    with pytest.raises(StitchError, match="Capture and playback"):
        source_profile("unused", dict(camera_type="Antigravity A1", frame_rate_nominal=nominal))
