"""Original A1 plane-view records and independent, timed viewing instructions.

Record 32 has a length-prefixed header in video and one bare 120-byte item in
the examined INSP photos. Quaternion storage is WXYZ, unlike attitude record 37.
No Studio project, profile, library, or network service is consulted.
"""

import struct

import numpy as np
from scipy.spatial.transform import Rotation, Slerp

from .errors import StitchError

AXIS = Rotation.from_euler("x", 90, degrees=True)
DTYPE = np.dtype(
    [
        ("timestamp", "<u8"),
        ("reserved", "<f4"),
        ("fov", "<f4", (2,)),
        ("camera", "<f4", (4,)),
        ("pilot", "<f4", (4,)),
        ("other", "u1", (64,)),
        ("category", "<u4"),
    ]
)


class Viewpoint:
    def __init__(self, reader, *, photo=False):
        if 32 not in reader.records or reader.records[32].encoding != 0:
            raise StitchError(
                "No supported embedded A1 view record; use an explicit calibration and --view fixed"
            )
        data = reader.payload(32)
        if photo:
            if len(data) != 120:
                raise StitchError("Unsupported still-photo view record")
            offset = 0
        else:
            if len(data) < 4:
                raise StitchError("Truncated view header")
            offset = struct.unpack_from("<I", data)[0]
            if not 4 <= offset <= min(len(data) - 240, 1024 * 1024):
                raise StitchError("Invalid view record header length")
        if not data[offset:] or (len(data) - offset) % 120:
            raise StitchError("Truncated 120-byte view record")
        items = np.frombuffer(data, DTYPE, offset=offset)
        if np.any(items["category"] != 0):
            raise StitchError(
                "Unsupported view category; tracking-mode interpretation is not qualified"
            )
        self.times = (
            items["timestamp"].astype(float) - reader.metadata()["first_frame_timestamp_us"]
        ) / 1e6
        if not np.isfinite(self.times).all() or np.any(np.diff(self.times) <= 0):
            raise StitchError("View timestamps must be strictly increasing")
        self.fov = np.array(items["fov"], float)
        if not np.isfinite(self.fov).all():
            raise StitchError("Invalid recorded viewport extent")
        rotations = {}
        for name in ("camera", "pilot"):
            q = items[name]
            if not np.isfinite(q).all() or np.any(np.abs(np.linalg.norm(q, axis=1) - 1) > 0.002):
                raise StitchError(f"Invalid {name} view quaternion")
            rotations[name] = Rotation.from_quat(q[:, [1, 2, 3, 0]])
        self.camera = AXIS * rotations["camera"].inv() * AXIS
        self.pilot_local = AXIS.inv() * rotations["pilot"] * AXIS.inv()
        self.photo = photo

    def at(self, times, *, pilot=False, max_gap=0.25):
        query = np.atleast_1d(np.asarray(times, float))
        if not np.isfinite(query).all():
            raise StitchError("Nonfinite viewpoint time")
        rotations = self.pilot_local if pilot else self.camera
        if self.photo:
            if np.any(np.abs(query - self.times[0]) > 1e-6):
                raise StitchError("A photo has one recorded orientation")
            return Rotation.from_quat(np.repeat(rotations.as_quat(), len(query), axis=0))
        if np.any(query < self.times[0]) or np.any(query > self.times[-1]):
            raise StitchError(
                "View record does not cover the requested range; select a covered range"
            )
        left = np.clip(np.searchsorted(self.times, query, side="right") - 1, 0, len(self.times) - 2)
        gap = self.times[left + 1] - self.times[left]
        exact = np.isclose(query, self.times[left], atol=1e-8, rtol=0) | np.isclose(
            query, self.times[left + 1], atol=1e-8, rtol=0
        )
        if np.any((gap > max_gap) & ~exact):
            raise StitchError("View record has a gap over 250 ms in the requested range")
        return Slerp(self.times, rotations)(query)

    def report(self):
        return dict(
            kind="a1-plane-view-v1",
            record=32,
            samples=len(self.times),
            first_seconds=float(self.times[0]),
            last_seconds=float(self.times[-1]),
            gaps_over_250ms=int(np.sum(np.diff(self.times) > 0.25)),
            quaternion_storage="wxyz",
            category=0,
            recorded_extent_range=[self.fov.min(axis=0).tolist(), self.fov.max(axis=0).tolist()],
            coordinate_system="x-right-y-down-z-forward",
        )


def heading_rotation(pose):
    """Hold a source-relative heading while retaining the embedded vertical."""
    forward = pose.apply([0, -1, 0])
    if np.hypot(forward[0], forward[2]) < 1e-6:
        raise StitchError("Embedded heading is vertical; choose another heading reference frame")
    return Rotation.from_euler("y", -np.arctan2(forward[0], forward[2]))


def camera_path(view, frames, fps, sphere_matrices):
    times = np.asarray(frames) / float(fps)
    rotation = Rotation.from_matrix(sphere_matrices) * view.at(times, pilot=True)
    q = rotation.as_quat()
    for i in range(1, len(q)):
        if np.dot(q[i - 1], q[i]) < 0:
            q[i] *= -1
    # The two recorded extent values are retained as observations. The initial
    # rectilinear presentation uses a documented 90-degree horizontal FOV;
    # Studio's projection-specific 100/100 values are not assumed to be degrees.
    return dict(
        schema_version=1,
        kind="a1-pilot-viewport-v1",
        default_mode="pilot",
        coordinate_system="x-right-y-down-z-forward",
        quaternion_order="xyzw",
        interpolation="slerp",
        timebase="output-presentation-seconds",
        source_first_frame=int(frames[0]),
        fps=str(fps),
        hfov_degrees=90.0,
        fov_policy="presentation-default-not-decoded-pilot-zoom",
        samples=[
            dict(
                time=float((f - frames[0]) / float(fps)), source_frame=int(f), quaternion=v.tolist()
            )
            for f, v in zip(frames, q)
        ],
    )
