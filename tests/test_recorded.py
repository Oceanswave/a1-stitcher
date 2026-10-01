import json
import struct
from fractions import Fraction

import pytest
from conftest import metadata, pb, trailer, varint

from a1_stitcher.cli import main
from a1_stitcher.errors import StitchError
from a1_stitcher.insv import InsvReader
from a1_stitcher.recorded import (
    accessory_candidates,
    exposure_clock,
    lens_record,
    recorded_calibration,
    singular,
)


def v6_values():
    # Synthetic values only; no camera-specific calibration in the fixture.
    values = [2]
    for lens in range(2):
        values += [2, 100, 102, 64 + 128 * lens, 65, 1, 2, 3, 0, 0, 0]
        values += [i / 100 for i in range(13)] + [256, 128, 113]
    return values + [0]


def v6_string(values=None):
    return "_".join(map(str, values if values is not None else v6_values())).encode()


def fixed_double(number, value):
    return varint(number * 8 + 1) + struct.pack("<d", value)


def accessories():
    return (
        pb(1, pb(1, "bare") + b"".join(fixed_double(2, i / 100) for i in range(6)))
        + pb(2, pb(1, "bare") + fixed_double(2, 200))
        + pb(3, pb(1, "heat_bare") + pb(2, 10))
    )


def metadata_payload():
    return (
        pb(2, "Insta360 X5")
        + pb(3, "synthetic")
        + pb(22, "standard")
        + pb(26, pb(1, 0))
        + pb(24, 1_000_000)
        + pb(104, 3)
        + pb(136, 4)
        + pb(111, v6_string())
        + pb(112, v6_string())
        + pb(145, accessories())
        + pb(64, 2)
    )


def exposure_payload(count=8):
    return b"".join(struct.pack("<Qd", 1_000_000 + i * 100_010, 0.01) for i in range(count))


@pytest.fixture
def recorded_source(tmp_path, monkeypatch):
    source = tmp_path / "recorded.insv"
    source.write_bytes(trailer([(1, metadata_payload()), (4, exposure_payload())]))
    profile = dict(fps="10/1", frames=8, width=128, color="SDR", recording_mode={})
    monkeypatch.setattr("a1_stitcher.recorded.input_profile", lambda *_: profile.copy())
    return source


def test_reads_recorded_parameters_and_actual_clock_without_claiming_export(recorded_source):
    r = recorded_calibration(recorded_source, frame=7)
    lenses = r["parameters"]["offset_v6"]["lenses"]
    assert lenses[0]["sensor_intrinsics"]["fx"] == 100
    assert lenses[1]["sensor_intrinsics"]["cx"] == 192
    assert lenses[0]["distortion_slots"][-1] == 0.12
    assert r["current_equals_original"]
    assert r["guard_detection"]["matched_candidate"] == "bare"
    assert not r["guard_detection"]["applied"]
    assert not r["sphere_export_available"]
    clock = r["exposure_clock"]
    assert clock["selected_frame"]["relative_timestamp_seconds"] == pytest.approx(0.700070)
    assert clock["selected_frame"]["candidate_midpoint_seconds"] == pytest.approx(0.695070)
    assert clock["playback_residual_seconds"]["maximum"] == pytest.approx(0.000070)
    assert not clock["applied_to_renderer"]


def test_parameters_reuse_fingerprint_across_recordings_but_bind_mode_and_values(
    recorded_source, tmp_path, monkeypatch
):
    baseline = recorded_calibration(recorded_source)
    other = tmp_path / "other.insv"
    other.write_bytes(recorded_source.read_bytes())
    assert recorded_calibration(other)["parameter_fingerprint"] == baseline["parameter_fingerprint"]
    values = v6_values()
    values[2] += 1
    # Replace via protobuf encoding, avoiding a length-changing byte substitution.
    changed = metadata_payload().replace(pb(111, v6_string()), pb(111, v6_string(values)))
    other.write_bytes(trailer([(1, changed), (4, exposure_payload())]))
    assert recorded_calibration(other)["parameter_fingerprint"] != baseline["parameter_fingerprint"]
    assert not recorded_calibration(other)["current_equals_original"]
    monkeypatch.setattr(
        "a1_stitcher.recorded.input_profile",
        lambda *_: dict(fps="10/1", frames=8, width=256, color="SDR", recording_mode={}),
    )
    assert (
        recorded_calibration(recorded_source)["parameter_fingerprint"]
        != baseline["parameter_fingerprint"]
    )


@pytest.mark.parametrize("change", ["length", "nan", "type", "sensor", "principal-point"])
def test_extended_lens_record_rejects_unknown_geometry(change):
    values = v6_values()
    if change == "length":
        values.pop()
    elif change == "nan":
        values[12] = float("nan")
    elif change == "type":
        values[27] = 999
    elif change == "sensor":
        values[25] = 128
    else:
        values[4] = 999
    with pytest.raises(StitchError):
        lens_record(v6_string(values))


def test_accessory_slots_are_retained_without_guessed_semantics():
    result = accessory_candidates(accessories())
    assert result["1"][0] == {"name": "bare", "slots": [0, 0.01, 0.02, 0.03, 0.04, 0.05]}
    assert result["2"][0]["slots"] == [200]
    assert result["3"][0]["slots"] == [10]
    with pytest.raises(StitchError, match="duplicate"):
        accessory_candidates(accessories() + accessories())
    with pytest.raises(StitchError, match="count or wire"):
        accessory_candidates(pb(1, pb(1, "bare") + fixed_double(2, 1)))
    with pytest.raises(StitchError, match="Non-finite"):
        accessory_candidates(
            pb(1, pb(1, "bare") + b"".join(fixed_double(2, float("nan")) for _ in range(6)))
        )


def test_guard_unknown_is_not_inferred_from_available_profiles(recorded_source):
    payload = metadata_payload().replace(pb(104, 3), pb(104, 0))
    recorded_source.write_bytes(trailer([(1, payload), (4, exposure_payload())]))
    r = recorded_calibration(recorded_source)
    assert r["guard_detection"]["label"] == "unknown"
    assert r["guard_detection"]["matched_candidate"] is None


def test_singular_field_requires_declared_wire_and_unique_value():
    for fields in [{111: [(0, 2)]}, {111: [(2, b"a"), (2, b"b")]}]:
        with pytest.raises(StitchError, match="singular"):
            singular(fields, 111, 2)


@pytest.mark.parametrize("change", ["missing-zero", "gap", "duration", "incomplete"])
def test_exposure_frame_correspondence_rejects_gaps_and_incomplete_mapping(recorded_source, change):
    stamps = [1_000_000 + i * 100_010 for i in range(8)]
    duration = 0.01
    if change == "missing-zero":
        stamps = [t + 1000 for t in stamps]
    elif change == "gap":
        stamps[4:] = [t + 100_000 for t in stamps[4:]]
    elif change == "duration":
        duration = 1
    else:
        stamps.pop()
    data = b"".join(struct.pack("<Qd", t, duration) for t in stamps)
    recorded_source.write_bytes(trailer([(1, metadata_payload()), (4, data)]))
    with pytest.raises(StitchError):
        exposure_clock(
            InsvReader(recorded_source),
            {"first_frame_timestamp_us": 1_000_000},
            {"fps": "10/1", "frames": 8},
        )


def test_cli_redaction_and_no_clobber_do_not_enable_x5(recorded_source, tmp_path, capsys):
    output = tmp_path / "recorded.json"
    args = ["recorded-calibration", str(recorded_source), "--redact-path", "--output", str(output)]
    assert main(args) == 0
    assert json.loads(capsys.readouterr().out)["source"] == recorded_source.name
    before = output.read_bytes()
    assert main(args) == 1
    assert output.read_bytes() == before
    assert main(["recorded-calibration", str(recorded_source), "--frame", "8"]) == 1


@pytest.mark.integration
def test_real_container_ingest_and_recorded_parameters_remain_separate_from_a1(
    synthetic_camera, tmp_path
):
    source = tmp_path / "synthetic-x5.insv"
    source.write_bytes(synthetic_camera["source"].read_bytes())
    meta = metadata()
    payload = metadata_payload() + pb(54, "_".join(map(str, meta["offset_v3"])))
    with source.open("ab") as stream:
        stream.write(trailer([(1, payload), (4, exposure_payload())]))
    report = recorded_calibration(source, frame=3)
    assert Fraction(report["parameters"]["capture"]["fps"]) == 10
    assert report["exposure_clock"]["mapped_frames"] == 8
    with pytest.raises(StitchError, match="currently X5 only"):
        recorded_calibration(synthetic_camera["source"])
