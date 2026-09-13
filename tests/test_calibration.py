import struct

import numpy as np
import pytest
from scipy.spatial.transform import Rotation, Slerp

from a1_stitcher.calibration import fit_gravity, score_gravity
from a1_stitcher.errors import StitchError
from a1_stitcher.projection import orientation37
from a1_stitcher.reference import cube_features, fit_spheres


class AttitudeReader:
    def __init__(self):
        times = np.arange(0, 1.01, 0.02)
        poses = Rotation.from_euler(
            "xyz", np.column_stack([0.2 * np.sin(times * 8), 0.15 * np.sin(times * 5), times * 0.4])
        )
        self.data = b"".join(
            struct.pack("<Q7f", round(t * 1e6), *q, 0, 0, 0) for t, q in zip(times, poses.as_quat())
        )

    def payload(self, kind):
        return self.data

    def metadata(self):
        return {"first_frame_timestamp_us": 0}


def test_reference_fit_recovers_mount_and_timing_on_unseen_frames():
    reader = AttitudeReader()
    times, poses = orientation37(reader)
    slerp = Slerp(times, poses)
    mount = Rotation.from_euler("xyz", [-0.15, 0.004, -np.pi / 2])
    shift = 0.016
    world = Rotation.from_matrix([[0, 1, 0], [0, 0, 1], [1, 0, 0]])

    def observations(indices):
        return [
            dict(
                raw_seconds=t,
                lens_to_reference=(world * slerp(t + shift) * mount).as_matrix().tolist(),
            )
            for t in indices
        ]

    training = observations(np.arange(0.1, 0.71, 0.1))
    fitted, offset = fit_gravity(reader, training)
    assert (fitted.inv() * mount).magnitude() < 1e-5
    assert offset == pytest.approx(shift, abs=1e-5)
    holdout = score_gravity(reader, observations([0.15, 0.35, 0.65, 0.8]), fitted, offset)
    assert holdout["maximum_degrees"] < 0.001


def test_exposure_fit_uses_variable_midpoints_and_recovers_mount(tmp_path):
    from test_exposure import reader as exposure_reader

    from a1_stitcher.exposure import ExposureClock

    shutters = [0.002, 0.006, 0.014, 0.004, 0.01, 0.008, 0.003, 0.018, 0.012, 0.005]
    payload = b"".join(struct.pack("<Qd", 1000000 + i * 100000, s) for i, s in enumerate(shutters))
    clock = ExposureClock(exposure_reader(tmp_path, payload), 10)
    reader = AttitudeReader()
    times, poses = orientation37(reader)
    slerp = Slerp(times, poses)
    mount = Rotation.from_euler("xyz", [-0.15, 0.004, -np.pi / 2])
    world = Rotation.from_matrix([[0, 1, 0], [0, 0, 1], [1, 0, 0]])
    offset = 0.017
    observations = [
        dict(
            raw_seconds=i / 10,
            lens_to_reference=(world * slerp(clock.at_frames([i])[0] + offset) * mount)
            .as_matrix()
            .tolist(),
        )
        for i in range(1, 10)
    ]
    fitted, shift = fit_gravity(reader, observations[:6], frame_clock=clock)
    assert shift == pytest.approx(offset, abs=1e-5)
    assert (fitted.inv() * mount).magnitude() < 1e-5
    checked = score_gravity(reader, observations[6:], fitted, shift, frame_clock=clock)
    assert checked["maximum_degrees"] < 0.001


def test_still_reference_is_underconstrained():
    reader = AttitudeReader()
    with pytest.raises(StitchError, match="variation"):
        fit_gravity(
            reader,
            [
                dict(raw_seconds=t, lens_to_reference=np.eye(3).tolist())
                for t in np.arange(0.1, 0.8, 0.1)
            ],
        )


def test_too_few_reference_samples():
    with pytest.raises(StitchError, match="six"):
        fit_gravity(AttitudeReader(), [])


def test_blank_reference_has_actionable_error():
    with pytest.raises(StitchError, match="texture"):
        cube_features(np.zeros((64, 128, 3), np.uint8), size=64)


def test_spherical_feature_match_recovers_known_yaw():
    import cv2

    rng = np.random.default_rng(3)
    sphere = rng.integers(0, 256, (512, 1024, 3), dtype=np.uint8)
    sphere = cv2.GaussianBlur(sphere, (5, 5), 1)
    shifted = np.roll(sphere, 64, axis=1)
    rotation, report = fit_spheres(sphere, shifted)
    expected = Rotation.from_euler("y", 22.5, degrees=True)
    assert (Rotation.from_matrix(rotation).inv() * expected).magnitude() < np.radians(0.1)
    assert report["inliers"] > 100


def test_calibration_workflow_maps_reference_frames_and_saves_profile(
    synthetic_camera, tmp_path, monkeypatch
):
    import json

    import a1_stitcher.reference as module
    from a1_stitcher.insv import InsvReader

    reader = InsvReader(synthetic_camera["source"])
    times, poses = orientation37(reader)
    slerp = Slerp(times, poses)
    original = json.loads(synthetic_camera["calibration"].read_text())
    mount = Rotation.from_matrix(original["lens_mount"])
    world = Rotation.from_matrix([[0, 1, 0], [0, 0, 1], [1, 0, 0]])
    reference = tmp_path / "reference.mp4"
    reference.write_bytes(b"synthetic-reference-placeholder")
    monkeypatch.setattr(
        module,
        "probe",
        lambda path: {
            "streams": [
                dict(codec_type="video", width=256, height=128, r_frame_rate="10", nb_frames="8")
            ]
        },
    )

    def decode(path, seconds, **kwargs):
        return np.full((8, 8, 3), round(seconds * 10), np.uint8)

    monkeypatch.setattr(module, "decode_frame", decode)
    monkeypatch.setattr(
        module,
        "match_lenses",
        lambda *args: (
            np.array(original["rotation_lens1_to_lens0"]),
            dict(inliers=100, matches=110),
        ),
    )
    monkeypatch.setattr(module, "blend_sphere", lambda frames, *args, **kwargs: (frames[0], 0))

    def fit(source, target):
        index = int(target[0, 0, 0])
        t = index / 10
        observed = (world * slerp(t) * mount).as_matrix()
        provisional = Rotation.from_euler("x", 90, degrees=True).as_matrix()
        return observed @ provisional, dict(
            inliers=200, matches=210, median_degrees=0, p95_degrees=0
        )

    monkeypatch.setattr(module, "fit_spheres", fit)
    output = tmp_path / "profile.json"
    evidence = tmp_path / "evidence"
    result = module.calibrate(
        synthetic_camera["source"],
        reference,
        0,
        [0, 1, 2, 3, 4, 5],
        [6, 7],
        output,
        evidence=evidence,
    )
    assert result["schema_version"] == 1
    assert result["holdout"]["samples"] == 2
    assert result["holdout"]["maximum_degrees"] < 0.01
    assert (
        json.loads((evidence / "observations.json").read_text())["observations"][3]["raw_seconds"]
        == 0.3
    )
    assert output.exists()
    with pytest.raises(StitchError, match="new file"):
        module.calibrate(
            synthetic_camera["source"], reference, 0, [0, 1, 2, 3, 4, 5], [6, 7], output
        )
