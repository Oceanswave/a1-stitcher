import json
import struct
from copy import deepcopy
from dataclasses import replace
from fractions import Fraction

import numpy as np
import pytest
from conftest import metadata, pb, trailer
from test_jobs import options
from test_media import good

from a1_stitcher.audio import audio_profile, audio_window, extract_audio
from a1_stitcher.cameras import A1, X5, camera_adapter
from a1_stitcher.cli import main
from a1_stitcher.errors import StitchError
from a1_stitcher.insv import InsvReader
from a1_stitcher.media import input_profile, source_profile
from a1_stitcher.preflight import imu_summary, preflight
from a1_stitcher.process import binary, probe, run
from a1_stitcher.render import plan
from a1_stitcher.storage import digest


def x5_metadata():
    return dict(camera_type="Insta360 X5", gamma_mode="standard", file_group_type=0)


def x5_info():
    info = deepcopy(good())
    info["streams"].append(
        dict(
            codec_type="audio",
            codec_name="aac",
            index=4,
            sample_rate="48000",
            channels=2,
            start_time="0",
            time_base="1/48000",
            duration_ts=192192,
        )
    )
    return info


def test_dispatch_never_infers_camera_from_extension_or_borrows_a1():
    assert camera_adapter({"camera_type": "Antigravity A1"}) is A1
    assert camera_adapter(x5_metadata()) is X5
    for model in (None, "Insta360 X6", "Insta360 X3", "unknown.insv", []):
        with pytest.raises(StitchError, match="Unsupported camera model"):
            camera_adapter({"camera_type": model})


def test_a1_profile_keeps_existing_shape_and_audio_rejection(monkeypatch):
    monkeypatch.setattr("a1_stitcher.media.probe", lambda _: good())
    result = source_profile("ignored", {"camera_type": "Antigravity A1"})
    assert set(result) == {"fps", "frames", "width", "color", "audio", "streams", "recording_mode"}
    assert result["audio"] == "none"
    monkeypatch.setattr("a1_stitcher.media.probe", lambda _: x5_info())
    with pytest.raises(StitchError, match="Audio"):
        source_profile("ignored", {"camera_type": "Antigravity A1"})


def test_x5_contract_accepts_audio_but_never_grants_render_support(monkeypatch):
    info = x5_info()
    info["streams"][0]["index"] = 7
    monkeypatch.setattr("a1_stitcher.media.probe", lambda _: info)
    profile = input_profile("ignored", x5_metadata())
    assert profile["streams"] == [7, 1]
    assert profile["audio"]["stream"] == 4
    assert profile["video_start_seconds"] == "0.000000"
    with pytest.raises(StitchError, match="X5 sphere export is not qualified"):
        source_profile("ignored", x5_metadata())


@pytest.mark.parametrize(
    "change",
    [
        {"gamma_mode": None},
        {"gamma_mode": "Log"},
        {"file_group_type": None},
        {"file_group_type": 17},
        {"file_group_type": 2},
        {"file_group_type": 99},
        {"uav_camera_mode": 0},
        {"hdr_state": 1},
        {"hdr_mode": 2},
        {"video_bit_depth": 2},
        {"ultra_hdr_enabled": 1},
        {"frame_rate_nominal": 60},
    ],
)
def test_x5_unqualified_modes_color_and_retiming_rejected(monkeypatch, change):
    monkeypatch.setattr("a1_stitcher.media.probe", lambda _: x5_info())
    with pytest.raises(StitchError):
        input_profile("ignored", x5_metadata() | change)


@pytest.mark.parametrize(
    "change",
    [
        {"codec_name": "opus"},
        {"channels": 6},
        {"sample_rate": "44100"},
        {"start_time": "N/A"},
        {"duration_ts": 0},
        {"time_base": "1/0"},
    ],
)
def test_audio_requires_known_single_track_contract(change):
    info = x5_info()
    info["streams"][-1].update(change)
    with pytest.raises(StitchError, match="audio contract"):
        audio_profile(info)


def test_multi_audio_and_absent_audio_are_distinguished():
    assert audio_profile(good()) == {"status": "absent"}
    info = x5_info()
    info["streams"].append(info["streams"][-1].copy())
    with pytest.raises(StitchError, match="at most one"):
        audio_profile(info)


def test_fractional_rate_uses_absolute_sample_boundaries_and_track_offsets():
    profile = X5.profile(x5_info(), x5_metadata())
    audio = profile["audio"]
    profile["frames"] = 100000
    audio["samples"] = 200000000
    profile["video_start_seconds"] = "1/10"
    audio["start_seconds"] = "1/20"
    window = audio_window(profile, 99999, 1)
    start = round((Fraction(1, 20) + 99999 / Fraction(30000, 1001)) * 48000)
    end = round((Fraction(1, 20) + 100000 / Fraction(30000, 1001)) * 48000)
    assert window["first_decoded_sample"] == start
    assert window["samples"] == end - start
    audio["start_seconds"] = "1/5"
    with pytest.raises(StitchError, match="does not cover"):
        audio_window(profile, 0, 1)
    audio["samples"] = 1
    with pytest.raises(StitchError, match="does not cover"):
        audio_window(profile, 30, 1)
    with pytest.raises(StitchError, match="frame range"):
        audio_window(profile, True, 1)


@pytest.fixture
def synthetic_x5(synthetic_camera, tmp_path):
    source = tmp_path / "x5.insv"
    run(
        [
            binary("ffmpeg"),
            "-v",
            "error",
            "-n",
            "-i",
            str(synthetic_camera["source"]),
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=997:sample_rate=48000:duration=0.8",
            "-map",
            "0:v:0",
            "-map",
            "0:v:1",
            "-map",
            "1:a:0",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-ac",
            "2",
            "-f",
            "mp4",
            str(source),
        ]
    )
    meta = metadata()
    record = (
        pb(2, "Insta360 X5")
        + pb(22, "standard")
        + pb(26, pb(1, 0))
        + pb(24, meta["first_frame_timestamp_us"])
        + pb(62, 1)
        + pb(54, "_".join(map(str, meta["offset_v3"])))
    )
    imu = b"".join(
        struct.pack("<Q6H", meta["first_frame_timestamp_us"] + i * 1000, *([32768] * 6))
        for i in range(1001)
    )
    with source.open("ab") as stream:
        stream.write(trailer([(1, record), (3, imu)]))
    return source


@pytest.mark.integration
def test_preflight_and_render_gate_do_not_need_a1_attitude(
    synthetic_x5, synthetic_camera, tmp_path, capsys
):
    before = digest(synthetic_x5)
    report = preflight(synthetic_x5)
    assert report["status"] == "input-contract-passed"
    assert report["sphere_export_available"] is False
    assert report["export_blockers"]
    assert report["embedded_orientation_records"] == {"32": False, "37": False}
    assert report["imu"]["median_rate_hz"] == 1000
    assert report["imu"]["orientation_qualified"] is False
    output = tmp_path / "sphere.mp4"
    cfg = replace(options(synthetic_camera, output), source=str(synthetic_x5), view="fixed")
    with pytest.raises(StitchError, match="X5 sphere export is not qualified"):
        plan(cfg)
    assert not output.exists()
    assert main(["preflight", str(synthetic_x5), "--redact-path"]) == 0
    assert json.loads(capsys.readouterr().out)["source"] == synthetic_x5.name
    assert digest(synthetic_x5) == before


@pytest.mark.integration
def test_pcm_companion_matches_exact_decoded_samples_and_never_clobbers(synthetic_x5, tmp_path):
    output = tmp_path / "audio.wav"
    before = digest(synthetic_x5)
    result = extract_audio(synthetic_x5, output, 2, 4)
    assert result["source_frame_mapping"]["samples"] == 19200
    assert result["full_decode"]
    assert result["camera_type"] == "Insta360 X5"
    assert probe(output)["streams"][0]["channels"] == 2

    def pcm(path):
        return np.frombuffer(
            run(
                [
                    binary("ffmpeg"),
                    "-v",
                    "error",
                    "-i",
                    str(path),
                    "-map",
                    "0:a:0",
                    "-f",
                    "f32le",
                    "-",
                ]
            ),
            dtype="<f4",
        ).reshape(-1, 2)

    np.testing.assert_array_equal(pcm(output), pcm(synthetic_x5)[9600:28800])
    assert digest(synthetic_x5) == before
    assert json.loads((tmp_path / "audio.wav.receipt.json").read_text())["output_sha256"] == digest(
        output
    )
    with pytest.raises(StitchError, match="new files"):
        extract_audio(synthetic_x5, output, 2, 4)
    alias = tmp_path / "alias.wav"
    alias.symlink_to(output)
    with pytest.raises(StitchError, match="new files"):
        extract_audio(synthetic_x5, alias, 2, 4)
    assert not list(tmp_path.glob(".a1-audio-*"))


def test_preflight_rejects_gapped_raw_imu(tmp_path):
    source = tmp_path / "gaps.insv"
    payload = b"".join(struct.pack("<Q6H", i * 20000, *([32768] * 6)) for i in range(100))
    source.write_bytes(trailer([(1, pb(2, "Insta360 X5")), (3, payload)]))
    with pytest.raises(StitchError, match="cadence"):
        imu_summary(InsvReader(source), {"first_frame_timestamp_us": 0, "is_raw_gyro": 1})


@pytest.mark.integration
def test_audio_source_change_and_receipt_failure_leave_no_partial_output(
    synthetic_x5, tmp_path, monkeypatch
):
    import a1_stitcher.audio as module

    output = tmp_path / "changed.wav"
    calls = iter([{"generation": 0}, {"generation": 1}])
    with monkeypatch.context() as patch:
        patch.setattr(module, "identity", lambda _: next(calls))
        with pytest.raises(StitchError, match="Source changed"):
            extract_audio(synthetic_x5, output, 2, 4)
    assert not output.exists()
    assert not (tmp_path / "changed.wav.receipt.json").exists()

    def fail_receipt(*_):
        raise OSError("simulated publication failure")

    monkeypatch.setattr(module, "write_new_json", fail_receipt)
    with pytest.raises(OSError, match="publication failure"):
        extract_audio(synthetic_x5, output, 2, 4)
    assert not output.exists()
    assert not list(tmp_path.glob(".a1-audio-*"))
    assert not list(tmp_path.glob("*.lock"))
