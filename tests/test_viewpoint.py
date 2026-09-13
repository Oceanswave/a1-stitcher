import copy
import struct
from fractions import Fraction

import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from a1_stitcher.errors import StitchError
from a1_stitcher.viewpoint import AXIS, DTYPE, Viewpoint, camera_path


class Reader:
    def __init__(self, *, photo=False):
        self.records = {32: type("Record", (), {"encoding": 0})()}
        self.data = bytearray() if photo else bytearray(struct.pack("<I", 4))
        self.times = [0.0] if photo else [0.0, 0.1, 0.2, 0.3]
        for t in self.times:
            camera = Rotation.from_euler("xyz", [10 * t, 20 * t, 30 * t], degrees=True)
            pilot = Rotation.from_euler("y", 179 + 20 * t, degrees=True)
            self.data.extend(
                struct.pack(
                    "<Q11f",
                    1_000_000 + round(t * 1e6),
                    0,
                    100,
                    100,
                    *camera.as_quat()[[3, 0, 1, 2]],
                    *pilot.as_quat()[[3, 0, 1, 2]],
                )
                + bytes(68)
            )

    def payload(self, _):
        return bytes(self.data)

    def metadata(self):
        return {"first_frame_timestamp_us": 1_000_000}


def test_distinct_pilot_camera_conventions_and_times():
    view = Viewpoint(Reader())
    assert DTYPE.itemsize == 120
    expected = AXIS * Rotation.from_euler("xyz", [2, 4, 6], degrees=True).inv() * AXIS
    assert (view.at([0.2])[0].inv() * expected).magnitude() < 1e-6
    pilot = AXIS.inv() * Rotation.from_euler("y", 183, degrees=True) * AXIS.inv()
    assert (view.at([0.2], pilot=True)[0].inv() * pilot).magnitude() < 1e-6
    assert view.report()["gaps_over_250ms"] == 0


def test_quaternion_wrap_and_trimmed_presentation_clock():
    view = Viewpoint(Reader())
    path = camera_path(view, np.array([1, 2, 3]), Fraction(10), np.repeat(np.eye(3)[None], 3, 0))
    assert [s["time"] for s in path["samples"]] == [0, 0.1, 0.2]
    assert path["source_first_frame"] == 1
    q = Rotation.from_quat([s["quaternion"] for s in path["samples"]])
    assert np.max(np.degrees((q[:-1].inv() * q[1:]).magnitude())) == pytest.approx(2, abs=1e-4)
    assert path["fov_policy"] == "presentation-default-not-decoded-pilot-zoom"


@pytest.mark.parametrize(
    "mutation", ["truncated", "header", "nan", "zero", "time", "encoding", "category", "missing"]
)
def test_reject_invalid_view_records(mutation):
    r = Reader()
    if mutation == "truncated":
        r.data.pop()
    elif mutation == "header":
        struct.pack_into("<I", r.data, 0, 999999)
    elif mutation == "nan":
        struct.pack_into("<f", r.data, 4 + 20, float("nan"))
    elif mutation == "zero":
        r.data[24:40] = bytes(16)
    elif mutation == "time":
        r.data[124:132] = r.data[4:12]
    elif mutation == "encoding":
        r.records[32].encoding = 1
    elif mutation == "category":
        struct.pack_into("<I", r.data, 4 + 116, 1)
    else:
        r.records = {}
    with pytest.raises(StitchError):
        Viewpoint(r)


def test_coverage_gap_and_single_photo():
    r = Reader()
    struct.pack_into("<Q", r.data, 4 + 3 * 120, 2_000_000)
    v = Viewpoint(r)
    with pytest.raises(StitchError, match="gap"):
        v.at([0.4])
    with pytest.raises(StitchError, match="cover"):
        v.at([-1])
    p = Viewpoint(Reader(photo=True), photo=True)
    assert len(p.at([0, 0])) == 2
    with pytest.raises(StitchError, match="one recorded"):
        p.at([1])


def test_quaternion_sign_equivalence():
    r = Reader()
    other = copy.deepcopy(r)
    for i in [1, 3]:
        q = np.frombuffer(r.data, dtype="<f4", count=4, offset=4 + i * 120 + 36).copy()
        struct.pack_into("<4f", other.data, 4 + i * 120 + 36, *(-q))
    a, b = Viewpoint(r), Viewpoint(other)
    assert (
        np.max(
            (
                a.at([0.05, 0.15, 0.25], pilot=True).inv() * b.at([0.05, 0.15, 0.25], pilot=True)
            ).magnitude()
        )
        < 1e-6
    )
