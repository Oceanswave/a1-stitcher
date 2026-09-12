import struct

import numpy as np
import pytest
from conftest import metadata
from scipy.spatial.transform import Rotation

from a1_stitcher.calibration import validate_calibration
from a1_stitcher.errors import StitchError
from a1_stitcher.projection import (
    TiledStitcher,
    blend_sphere,
    lenses_from_metadata,
    match_lenses,
    orientation37,
    project,
    project_scan,
    robust_rotation,
    sample_pixels,
    unproject,
)


@pytest.mark.parametrize("count", [1, 4096, 4097, 65539, 262144])
def test_sparse_interpolation_matches_dense_pixel_selection(count):
    import cv2

    rng = np.random.default_rng(99)
    frame = rng.integers(0, 255, (128, 128, 3), dtype=np.uint8)
    u, v = [rng.uniform(-2, 130, (512, 512)).astype(np.float32) for _ in range(2)]
    reference = cv2.remap(frame, u, v, cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
    selection = rng.choice(u.size, count, replace=False)
    actual = sample_pixels(frame, u.ravel()[selection], v.ravel()[selection])
    assert np.array_equal(actual, reference.reshape(-1, 3)[selection])


def test_sparse_sensor_row_projection_matches_full_grid():
    rng = np.random.default_rng(41)
    rays = rng.normal(size=(31, 83, 3)).astype(np.float32)
    rays /= np.linalg.norm(rays, axis=-1, keepdims=True)
    lens = lenses_from_metadata(metadata(), 512)[0]
    dense = project_scan(rays, lens, [3, -2, 1], 0.021)
    selection = rng.random(rays.shape[:2]) > 0.5
    sparse = project_scan(rays[selection], lens, [3, -2, 1], 0.021)
    for a, b in zip(dense, sparse):
        assert np.array_equal(a[selection], b)


def test_mei_roundtrip_and_principal_point_mapping():
    lenses = lenses_from_metadata(metadata(), 512)
    assert lenses[0]["K"][0, 2] == lenses[1]["K"][0, 2] == 256
    rng = np.random.default_rng(7)
    rays = np.column_stack([rng.normal(size=(1000, 2)), np.ones(1000)])
    rays /= np.linalg.norm(rays, axis=1)[:, None]
    x, y, valid = project(rays, lenses[0])
    back, good = unproject(np.column_stack([x[valid], y[valid]]), lenses[0])
    assert good.all()
    assert np.max(np.linalg.norm(back - rays[valid], axis=1)) < 1e-5
    assert not project(np.array([[0.0, 0.0, -1.0]]), lenses[0])[2][0]


def test_rotation_fit_tolerates_outliers_without_reflection():
    rng = np.random.default_rng(8)
    rays = rng.normal(size=(100, 3))
    rays /= np.linalg.norm(rays, axis=1)[:, None]
    rotation = Rotation.from_euler("xyz", [0.2, 0.5, 2.9])
    target = rotation.apply(rays)
    target[:25] = np.roll(target[:25], 1, axis=0)
    fitted, inliers, _ = robust_rotation(rays, target, iterations=300)
    assert inliers.sum() >= 75
    assert (Rotation.from_matrix(fitted).inv() * rotation).magnitude() < 1e-8
    assert np.linalg.det(fitted) == pytest.approx(1)


def test_blank_lenses_fail_actionably():
    blank = np.zeros((128, 128, 3), np.uint8)
    with pytest.raises(StitchError, match="texture"):
        match_lenses(blank, blank, lenses_from_metadata(metadata(), 128))


def test_tiled_renderer_agrees_with_full_reference():
    rng = np.random.default_rng(5)
    frames = [rng.integers(0, 255, (128, 128, 3), dtype=np.uint8) for _ in range(2)]
    lenses = lenses_from_metadata(metadata(), 128)
    relative = Rotation.from_euler("y", 180, degrees=True).as_matrix()
    rotation = Rotation.from_euler("xyz", [0.3, 0.1, -0.5]).as_matrix()
    reference, missing = blend_sphere(frames, lenses, relative, rotation, width=256)
    tiled, miss2 = TiledStitcher(lenses, relative, 256, strip_height=17).stitch(frames, rotation)
    assert missing == miss2 == 0
    # Float32 map rounding near interpolation-bin boundaries can affect isolated pixels.
    assert np.abs(reference.astype(float) - tiled.astype(float)).mean() < 0.1
    assert np.percentile(np.abs(reference.astype(float) - tiled.astype(float)), 99) <= 1


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"x",
        struct.pack("<Q7f", 1000, 0, 0, 0, 2, 0, 0, 0),
        struct.pack("<Q7f", 1000, 0, 0, 0, 1, 0, 0, 0) * 2,
    ],
)
def test_bad_attitude_records_rejected(data):
    class Reader:
        def payload(self, kind):
            return data

        def metadata(self):
            return {"first_frame_timestamp_us": 0}

    with pytest.raises(ValueError):
        orientation37(Reader())


@pytest.mark.parametrize(
    "field,value",
    [
        ("lens_mount", np.diag([1, 1, -1]).tolist()),
        ("time_shift_seconds", float("nan")),
        ("time_shift_seconds", 1),
        ("inverse", True),
        ("schema_version", 2),
    ],
)
def test_invalid_calibration_rejected(synthetic_camera, field, value):
    import json

    data = json.loads(synthetic_camera["calibration"].read_text())
    data[field] = value
    with pytest.raises(StitchError):
        validate_calibration(data)


def test_calibration_cannot_cross_camera_units(synthetic_camera):
    import json

    data = json.loads(synthetic_camera["calibration"].read_text())
    other = metadata()
    other["offset_v3"][2] += 0.1
    with pytest.raises(StitchError, match="different"):
        validate_calibration(data, other)
