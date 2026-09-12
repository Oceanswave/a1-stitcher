"""Synthetic sensor streams and ground-truth vibration; no camera recordings."""

import copy
import struct

import numpy as np
import pytest
from conftest import metadata
from scipy.spatial.transform import Rotation, Slerp

from a1_stitcher.calibration import lens_fingerprint
from a1_stitcher.errors import StitchError
from a1_stitcher.gyro import AnchoredGyro, dataset, fit, raw_gyro, validate


def profile():
    return dict(
        schema_version=1,
        kind="a1-rigid-gyro-v1",
        lens_fingerprint=lens_fingerprint(metadata()),
        raw_query_shift_seconds=0,
        raw_to_body_row_matrix=np.eye(3).tolist(),
        body_bias_radians_per_second=[0, 0, 0],
    )


def test_high_frequency_motion_between_recorded_anchors():
    t = np.arange(0, 2.001, 0.001)

    def angle(t):
        return np.radians(20 * t + 0.6 * np.sin(2 * np.pi * 40 * t))

    values = np.zeros((len(t), 3))
    values[:, 2] = np.radians(20 + 0.6 * 2 * np.pi * 40 * np.cos(2 * np.pi * 40 * t))
    at = np.arange(0, 2.001, 0.02)
    poses = Rotation.from_euler("z", angle(at)[:, None])
    trajectory = AnchoredGyro(at, poses, t, values, profile())
    query = np.arange(0.1, 1.9, 0.0037)
    truth = Rotation.from_euler("z", angle(query)[:, None])
    error = (truth.inv() * trajectory(query)).magnitude()
    old = (truth.inv() * Slerp(at, poses)(query)).magnitude()
    assert np.sqrt(np.mean(error**2)) < np.sqrt(np.mean(old**2)) * 0.02
    assert np.max((poses.inv() * trajectory(at)).magnitude()) < 1e-12


def test_anchors_bound_bias_and_reject_extrapolation():
    t = np.arange(0, 1.001, 0.001)
    at = np.arange(0, 1.001, 0.02)
    poses = Rotation.from_euler("z", at[:, None])
    motion = AnchoredGyro(at, poses, t, np.tile([0.03, 0.01, 1.02], (len(t), 1)), profile())
    assert np.max((poses.inv() * motion(at)).magnitude()) < 1e-12
    with pytest.raises(StitchError, match="coverage"):
        motion([-1])
    with pytest.raises(StitchError, match="coverage"):
        motion([float("nan")])
    with pytest.raises(StitchError, match="gaps"):
        AnchoredGyro([0, 2], Rotation.identity(2), t, np.zeros((len(t), 3)), profile())
    with pytest.raises(StitchError, match="gaps"):
        AnchoredGyro(at, poses, [0, 0.02], np.zeros((2, 3)), profile())
    short = AnchoredGyro(at, poses, t[10:], np.zeros((len(t) - 10, 3)), profile())
    with pytest.raises(StitchError, match="Raw gyro does not cover"):
        short([0])


@pytest.mark.parametrize(
    "change",
    [
        {"raw_to_body_row_matrix": np.diag([1, 1, -1]).tolist()},
        {"body_bias_radians_per_second": [0, 0, float("nan")]},
        {"raw_query_shift_seconds": 0.5},
        {"lens_fingerprint": "bad"},
        {"kind": "unknown"},
    ],
)
def test_profile_boundaries(change):
    with pytest.raises(StitchError):
        validate(profile() | change, metadata())


class Sensor:
    def __init__(self, still=False):
        self.meta = metadata() | {"gyro_configuration": {"gyro_range_dps": 2000}}
        self.records = {3: type("Record", (), {"encoding": 0})()}
        self.rt = np.arange(0, 90.001, 0.001)
        self.pt = np.arange(0, 90.001, 0.02)

        def pose(t):
            angles = np.column_stack(
                [0.35 * np.sin(t * 0.71), 0.28 * np.sin(t * 0.91), 0.4 * np.sin(t * 0.53)]
            )
            return Rotation.from_euler("xyz", angles * (0 if still else 1))

        rate = (pose(self.rt - 0.00001).inv() * pose(self.rt + 0.00001)).as_rotvec() / 0.00002
        self.matrix = Rotation.from_euler("xyz", [0.25, -0.1, 0.6]).as_matrix()
        rate = rate @ self.matrix.T
        records = np.zeros(
            len(self.rt),
            dtype=np.dtype([("t", "<u8"), ("acc", "<u2", (3,)), ("gyro", "<u2", (3,))]),
        )
        records["t"] = 10_000_000 + np.rint(self.rt * 1e6).astype("u8")
        records["gyro"] = np.rint(np.degrees(rate) * 32768 / 2000 + 32768).astype("u2")
        self.raw = records.tobytes()
        self.pose = b"".join(
            struct.pack("<Q7f", 10_000_000 + round(t * 1e6), *q, 0, 0, 0)
            for t, q in zip(self.pt, pose(self.pt).as_quat())
        )

    def metadata(self):
        return self.meta

    def payload(self, kind):
        return self.raw if kind == 3 else self.pose


def test_rigid_fit_recovers_axes_without_scale():
    sensor = Sensor()
    result = fit(sensor)
    rotation = np.array(result["raw_to_body_row_matrix"])
    assert np.max(np.abs(rotation - sensor.matrix)) < 0.003
    assert abs(result["raw_query_shift_seconds"]) <= 0.001
    assert result["qualification"]["holdout_rms_dps"] < 0.1
    validate(result, sensor.metadata())


def test_stationary_data_cannot_claim_axis_calibration():
    with pytest.raises(StitchError, match="Too little motion"):
        fit(Sensor(still=True))


def test_raw_layout_and_timestamp_guards():
    sensor = Sensor()
    for value in [b"", b"abc"]:
        invalid = copy.copy(sensor)
        invalid.raw = value
        with pytest.raises(StitchError, match="layout"):
            raw_gyro(invalid)
    invalid = copy.copy(sensor)
    invalid.raw = sensor.raw[:20] * 200
    with pytest.raises(StitchError, match="timestamps"):
        raw_gyro(invalid)
    invalid = copy.copy(sensor)
    invalid.raw = sensor.raw[: 20 * 500]
    with pytest.raises(StitchError, match="55 seconds"):
        dataset(invalid)
    invalid = copy.copy(sensor)
    invalid.meta = sensor.meta | {"gyro_configuration": {"gyro_range_dps": 3}}
    with pytest.raises(StitchError, match="range"):
        raw_gyro(invalid)


def test_anchor_spacing_does_not_reintroduce_recorded_jitter(tmp_path):
    import json

    from a1_stitcher.gyro import trajectory

    sensor = Sensor(still=True)
    # Synthetic erroneous 10 Hz attitude ripple with an otherwise stationary gyro.
    quaternions = Rotation.from_euler(
        "z", (0.01 * np.sin(2 * np.pi * 10 * sensor.pt))[:, None]
    ).as_quat()
    sensor.pose = b"".join(
        struct.pack("<Q7f", 10_000_000 + round(t * 1e6), *q, 0, 0, 0)
        for t, q in zip(sensor.pt, quaternions)
    )
    path = tmp_path / "gyro.json"
    path.write_text(json.dumps(profile()))
    every, _ = trajectory(sensor, path, 0.02)
    spaced, _ = trajectory(sensor, path, 0.1)
    query = np.arange(1, 2, 0.007)
    assert np.mean(spaced(query).magnitude() ** 2) < np.mean(every(query).magnitude() ** 2) * 0.001
    for bad in [0, 1.1, float("nan"), True]:
        with pytest.raises(StitchError, match="anchor interval"):
            trajectory(sensor, path, bad)
