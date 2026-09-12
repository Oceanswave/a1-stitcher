import numpy as np
import pytest
from conftest import metadata
from scipy.spatial.transform import Rotation

from a1_stitcher.errors import StitchError
from a1_stitcher.projection import (
    TiledStitcher,
    lenses_from_metadata,
    project,
    project_scan,
    sphere_rays,
    unproject,
)
from a1_stitcher.render import sensor_readout


def scene(rays):
    lon = np.arctan2(rays[:, 0], rays[:, 2])
    lat = np.arcsin(np.clip(rays[:, 1], -1, 1))
    return np.column_stack(
        [
            125 + 100 * np.sin(lon * 12),
            125 + 100 * np.cos(lat * 10),
            125 + 100 * np.sin(lon * 7 + lat * 9),
        ]
    )


def test_sensor_row_correction_recovers_a_known_fast_rotating_scene():
    width, readout = 512, 0.022
    lenses = lenses_from_metadata(metadata(), width)
    relative = Rotation.from_euler("y", 180, degrees=True).as_matrix()
    velocity = np.array([2, -3, 1.0])
    x, y = np.meshgrid(np.arange(width), np.arange(width))
    dt = (y.ravel() / (width - 1) - 0.5) * readout
    frames = []
    for index, lens in enumerate(lenses):
        rays, valid = unproject(np.column_stack([x.ravel(), y.ravel()]), lens)
        if index:
            rays = rays @ relative.T
        captured = Rotation.from_rotvec(dt[:, None] * velocity).apply(rays)
        frame = np.clip(scene(captured), 0, 255).astype(np.uint8)
        frame[~valid] = 0
        frames.append(frame.reshape(width, width, 3))
    before, _ = TiledStitcher(lenses, relative, 1024).stitch(frames, np.eye(3))
    after, missing = TiledStitcher(lenses, relative, 1024, readout_seconds=readout).stitch(
        frames, np.eye(3), velocity
    )
    rays = sphere_rays(1024)
    expected = scene(rays.reshape(-1, 3)).reshape(before.shape)
    mask = np.abs(rays[:, :, 2]) > 0.2
    before_error = np.abs(before - expected)[mask].mean()
    after_error = np.abs(after - expected)[mask].mean()
    assert missing == 0
    assert after_error < before_error * 0.2, (before_error, after_error)


def test_zero_readout_or_motion_preserves_original_map_exactly():
    lens = lenses_from_metadata(metadata(), 128)[0]
    rays = sphere_rays(128)
    expected = project(rays, lens)
    for velocity, readout in [(None, 0.02), ([0, 0, 0], 0.02), ([1, 2, 3], 0)]:
        result = project_scan(rays, lens, velocity, readout)
        assert all(np.array_equal(a, b) for a, b in zip(expected, result))


@pytest.mark.parametrize("value", [float("nan"), -1, 100, True, "21"])
def test_invalid_readout_metadata_fails(value):
    with pytest.raises(StitchError, match="readout"):
        sensor_readout({"rolling_shutter_ms": value}, 30, "auto")


def test_readout_policy_uses_actual_metadata_and_supports_comparison():
    assert sensor_readout({"rolling_shutter_ms": 21.325}, 30, "auto") == pytest.approx(0.021325)
    assert sensor_readout({"rolling_shutter_ms": 21.325}, 30, "off") == 0
    assert sensor_readout({}, 30, "auto") == 0
    with pytest.raises(StitchError):
        sensor_readout({}, 30, "guess")


def test_bad_renderer_readout_rejected():
    with pytest.raises(StitchError):
        TiledStitcher([], np.eye(3), 256, readout_seconds=-0.01)


@pytest.mark.parametrize("velocity", [[float("nan"), 0, 0], [1, 2]])
def test_bad_angular_velocity_rejected(velocity):
    with pytest.raises(StitchError, match="velocity"):
        TiledStitcher(lenses_from_metadata(metadata(128), 128), np.eye(3), 256).stitch(
            [np.zeros((128, 128, 3), np.uint8)] * 2, np.eye(3), velocity
        )
