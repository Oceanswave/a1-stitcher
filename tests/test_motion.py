import numpy as np
import pytest
from conftest import metadata
from scipy.spatial.transform import Rotation
from test_rolling_shutter import scene

from a1_stitcher.errors import StitchError
from a1_stitcher.motion import rotate_rows, row_rotations, validate_rows, world_orientation
from a1_stitcher.projection import TiledStitcher, lenses_from_metadata, sphere_rays, unproject


def vibration(times):
    times = np.asarray(times)
    return Rotation.from_rotvec(
        np.column_stack(
            [
                0.06 * np.sin(2 * np.pi * 70 * times),
                0.04 * np.cos(2 * np.pi * 55 * times),
                times * 0.7,
            ]
        )
    )


def test_changing_motion_recovers_known_scene_beyond_average_velocity():
    width, readout = 512, 0.022
    lenses = lenses_from_metadata(metadata(), width)
    relative = Rotation.from_euler("y", 180, degrees=True).as_matrix()
    mount = Rotation.from_euler("xyz", [0.2, -0.3, 0.4])
    x, y = np.meshgrid(np.arange(width), np.arange(width))
    times = (y.ravel() / (width - 1) - 0.5) * readout
    capture = mount.inv() * vibration([0])[0].inv() * vibration(times) * mount
    frames = []
    for index, lens in enumerate(lenses):
        rays, valid = unproject(np.column_stack([x.ravel(), y.ravel()]), lens)
        if index:
            rays = rays @ relative.T
        frame = np.clip(scene(capture.apply(rays)), 0, 255).astype(np.uint8)
        frame[~valid] = 0
        frames.append(frame.reshape(width, width, 3))
    renderer = TiledStitcher(lenses, relative, 1024, readout_seconds=readout)
    velocity = (
        mount.inv() * vibration([-readout / 2])[0].inv() * vibration([readout / 2])[0] * mount
    ).as_rotvec() / readout
    before, _ = renderer.stitch(frames, np.eye(3), velocity)
    rows = row_rotations(vibration, 0, mount, relative, readout)
    after, missing = renderer.stitch(frames, np.eye(3), row_quaternions=rows)
    rays = sphere_rays(1024)
    expected = scene(rays.reshape(-1, 3)).reshape(before.shape)
    mask = np.abs(rays[..., 2]) > 0.3
    before_error = np.abs(before - expected)[mask].mean()
    after_error = np.abs(after - expected)[mask].mean()
    assert missing == 0
    assert after_error < before_error * 0.2, (before_error, after_error)


def test_constant_rotation_matches_analytic_solution_in_both_lenses():
    velocity = np.array([2, -3, 1.0])
    mount = Rotation.from_euler("xyz", [0.2, 0.3, 0.4])
    relative = Rotation.from_euler("xy", [3, 1])

    def orientation(t):
        return Rotation.from_rotvec(np.asarray(t)[:, None] * velocity)

    rows = row_rotations(orientation, 10, mount, relative.as_matrix(), 0.022)
    fractions = np.linspace(0, 1, 1003)
    rays = np.tile([0.2, 0.3, 0.8], (len(fractions), 1))
    offsets = (fractions - 0.5) * 0.022
    for i, lens_mount in enumerate([mount, mount * relative]):
        expected = (
            lens_mount.inv() * Rotation.from_rotvec(-offsets[:, None] * velocity) * lens_mount
        ).apply(rays)
        actual = rotate_rows(rays, fractions, rows[i])
        np.testing.assert_allclose(actual, expected, atol=1e-7)


def test_heading_is_fixed_across_clip_boundaries_and_levels_world():
    orientation = Rotation.from_euler("xyz", [[0.2, -0.3, 0.7], [-0.1, 0.1, 1.2]])
    world = world_orientation(orientation[0])
    np.testing.assert_allclose(world.apply([0, 0, 1]), [0, 1, 0], atol=1e-12)
    forward = world.apply(orientation[0].apply([1, 0, 0]))
    assert abs(forward[0]) < 1e-12 and forward[2] > 0
    # Splitting the selected range must not rotate its second portion's heading.
    whole = (world * orientation).as_matrix()[1]
    chunk = (world_orientation(orientation[0]) * orientation[1]).as_matrix()
    np.testing.assert_array_equal(whole, chunk)
    with pytest.raises(StitchError, match="vertically"):
        world_orientation(Rotation.from_euler("y", np.pi / 2))


@pytest.mark.parametrize(
    "bad", [np.zeros((2, 33, 4)), np.ones((3, 4)), np.full((2, 33, 4), np.nan)]
)
def test_malformed_rows_rejected(bad):
    with pytest.raises(StitchError, match="Row rotations"):
        validate_rows(bad)


def test_antipodal_jump_is_rejected_and_missing_rows_are_allowed():
    q = np.zeros((2, 33, 4))
    q[..., 3] = 1
    q[0, 4] *= -1
    with pytest.raises(StitchError, match="continuous"):
        validate_rows(q)
    assert validate_rows(None) is None
    with pytest.raises(StitchError, match="timing"):
        row_rotations(vibration, 0, Rotation.identity(), np.eye(3), -0.01)
