import struct

import numpy as np
import pytest
from conftest import pb, trailer

from a1_stitcher.errors import StitchError
from a1_stitcher.exposure import ExposureClock, exposure_summary
from a1_stitcher.insv import InsvReader


def reader(tmp_path, samples):
    path = tmp_path / "exposure.insv"
    metadata = pb(2, "Antigravity A1") + pb(24, 1000000)
    records = [(1, metadata)]
    if samples is not None:
        records.append((4, samples))
    path.write_bytes(trailer(records))
    return InsvReader(path)


def test_exposure_telemetry_uses_explicit_units_and_keeps_calibrated_clock(tmp_path):
    samples = b"".join(
        struct.pack("<Qd", 1000000 + i * 33367, s) for i, s in enumerate([0.001, 0.002, 0.003])
    )
    source = reader(tmp_path, samples)
    before = source.path.read_bytes()
    info = source.inspect()["exposure"]
    assert info["samples"] == 3
    assert info["shutter_seconds"]["median"] == 0.002
    assert info["half_exposure_variation_seconds"] == 0.001
    assert info["first_relative_seconds"] == 0
    assert info["last_relative_seconds"] == pytest.approx(0.066734)
    assert info["applied_to_frame_clock"] is False
    assert source.path.read_bytes() == before
    assert exposure_summary(reader(tmp_path, None)) is None


@pytest.mark.parametrize(
    "samples",
    [
        b"",
        b"x" * 17,
        struct.pack("<QdQd", 100, 0.001, 100, 0.002),
        struct.pack("<QdQd", 100, 0.001, 90, 0.002),
        struct.pack("<QdQd", 100, float("nan"), 33467, 0.002),
        struct.pack("<QdQd", 100, -0.001, 33467, 0.002),
        struct.pack("<QdQd", 100, 0.001, 101, 0.002),
    ],
)
def test_malformed_exposure_rejected(tmp_path, samples):
    with pytest.raises(StitchError):
        exposure_summary(reader(tmp_path, samples))


def test_exposure_clock_matches_frame_indices_and_changing_shutters(tmp_path):
    times = [900000, 1000000, 1100050, 1199990]
    shutters = [0.002, 0.004, 0.010, 0.008]
    data = b"".join(struct.pack("<Qd", t, s) for t, s in zip(times, shutters))
    clock = ExposureClock(reader(tmp_path, data), 10)
    np.testing.assert_allclose(clock.at_frames([0, 1, 2]), [-0.002, 0.09505, 0.19599])
    np.testing.assert_allclose(clock.at_video_times([0.2, 0]), [0.19599, -0.002])
    assert clock.report()["first_exposure_record"] == 1
    for frames in [[-1], [3], [1.5], [True]]:
        with pytest.raises(StitchError, match="coverage"):
            clock.at_frames(frames)
    for times in [[0.05], [float("nan")], [float("inf")]]:
        with pytest.raises(StitchError, match="exact"):
            clock.at_video_times(times)


@pytest.mark.parametrize(
    "samples,match",
    [
        (None, "record 4"),
        ([(1000001, 0.001), (1100000, 0.001)], "exact first"),
        ([(1000000, 0.001), (1200000, 0.001)], "gap"),
        ([(1000000, 0.001), (1111000, 0.001)], "drift"),
        ([(1000000, 0.2), (1100000, 0.001)], "frame period"),
    ],
)
def test_ambiguous_exposure_correspondence_is_not_guessed(tmp_path, samples, match):
    payload = None if samples is None else b"".join(struct.pack("<Qd", *s) for s in samples)
    with pytest.raises(StitchError, match=match):
        ExposureClock(reader(tmp_path, payload), 10)
