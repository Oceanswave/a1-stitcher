"""Independent orientation sampling for sensor rows and a repeatable sphere heading."""

import numpy as np
from scipy.spatial.transform import Rotation

from .errors import StitchError

ROW_SAMPLES = 33  # <= 0.7 ms spacing for the observed A1 readout.


def row_rotations(orientation, center, mount, relative, readout):
    """Return center-to-capture rotations in each lens's native coordinate system.

    Use the measured trajectory across the exposure scan, rather than assuming
    one angular velocity. This is geometric resampling, not motion deblurring.
    """
    if not np.isfinite(center) or not np.isfinite(readout) or not 0 < readout <= 0.1:
        raise StitchError("Invalid row trajectory timing")
    query = center + np.linspace(-0.5, 0.5, ROW_SAMPLES) * readout
    capture = orientation(query)
    center_pose = capture[ROW_SAMPLES // 2]
    correction = mount.inv() * capture.inv() * center_pose * mount
    second = Rotation.from_matrix(relative)
    quaternions = np.stack([correction.as_quat(), (second.inv() * correction * second).as_quat()])
    # q and -q describe the same rotation. Choose adjacent signs before NLERP.
    for row in range(1, ROW_SAMPLES):
        flip = np.sum(quaternions[:, row - 1] * quaternions[:, row], axis=1) < 0
        quaternions[flip, row] *= -1
    return validate_rows(quaternions)


def validate_rows(value):
    if value is None:
        return None
    q = np.asarray(value, np.float32)
    if (
        q.ndim != 3
        or q.shape[0] != 2
        or q.shape[2] != 4
        or not 3 <= q.shape[1] <= 257
        or not np.isfinite(q).all()
        or np.max(np.abs(np.linalg.norm(q, axis=-1) - 1)) > 1e-4
        or np.any(np.sum(q[:, 1:] * q[:, :-1], axis=-1) <= 0)
    ):
        raise StitchError("Row rotations must be two continuous, unit-quaternion tracks")
    return np.ascontiguousarray(q)


def rotate_rows(rays, row_fraction, quaternions):
    """Interpolate a short, uniformly sampled quaternion track and apply it."""
    position = np.clip(row_fraction, 0, 1) * (len(quaternions) - 1)
    lower = np.minimum(position.astype(np.int32), len(quaternions) - 2)
    fraction = (position - lower)[..., None]
    q = quaternions[lower] * (1 - fraction) + quaternions[lower + 1] * fraction
    q /= np.linalg.norm(q, axis=-1)[..., None]
    cross = 2 * np.cross(q[..., :3], rays)
    return rays + q[..., 3:] * cross + np.cross(q[..., :3], cross)


def world_orientation(reference_pose):
    """A fixed NED-to-sphere rotation: choose heading once, preserve full attitude."""
    # atan2 on the forward vector avoids Euler gimbal-lock extraction warnings.
    forward = reference_pose.apply([1.0, 0, 0])
    if np.hypot(*forward[:2]) < 1e-6:
        raise StitchError("Heading reference points vertically; choose another source frame")
    heading = np.arctan2(forward[1], forward[0])
    ned_to_camera = Rotation.from_matrix([[0, 1, 0], [0, 0, 1], [1, 0, 0]])
    return Rotation.from_euler("y", -heading) * ned_to_camera
