import copy

import numpy as np
import pytest

from a1_stitcher.errors import StitchError
from a1_stitcher.x5_projection import (
    diagnostic_lens,
    distort,
    pixel_diagnostic,
    undistort,
    unproject,
)


@pytest.mark.parametrize(
    "slot,delta",
    [
        (0, [0.026, -0.039]),
        (1, [0.00338, -0.00507]),
        (2, [0.0004394, -0.0006591]),
        (3, [0.000057122, -0.000085683]),
        (4, [0.00000742586, -0.00001113879]),
        (5, [0.21, -0.12]),
        (6, [-0.12, 0.31]),
        (7, [0.0273, -0.0156]),
        (8, [-0.0156, 0.0403]),
        (9, [0.13, 0]),
        (10, [0, 0.13]),
        (11, [0.0169, 0]),
        (12, [0, 0.0169]),
    ],
)
def test_distortion_slot_order_against_hand_computed_polynomial(slot, delta):
    coefficients = np.zeros(13)
    coefficients[slot] = 1
    assert distort([[0.2, -0.3]], coefficients)[0] == pytest.approx(np.array([0.2, -0.3]) + delta)


def test_analytic_jacobian_and_nonzero_inverse_on_asymmetric_field():
    rng = np.random.default_rng(7)
    points = rng.uniform(-0.45, 0.45, (80, 2))
    coefficients = rng.uniform(-0.015, 0.015, 13)
    value, jacobian = distort(points, coefficients, jacobian=True)
    numerical = np.stack(
        [
            (distort(points + axis, coefficients) - distort(points - axis, coefficients)) / 2e-6
            for axis in np.eye(2) * 1e-6
        ],
        axis=2,
    )
    assert jacobian == pytest.approx(numerical, abs=1e-9)
    recovered, valid = undistort(value, coefficients)
    assert valid.all()
    assert recovered == pytest.approx(points, abs=1e-10)


@pytest.fixture
def parameters():
    lenses = [
        dict(
            xi=2,
            sensor_height=128,
            sensor_intrinsics=dict(fx=100, fy=102, cx=64 + i * 128, cy=65),
            distortion_slots=[0.0] * 13,
        )
        for i in (0, 1)
    ]
    result = dict(
        guard_detected_value=3,
        offset_v6=dict(lenses=lenses),
        window_crop_info=dict(src_width=128, src_height=128, dst_width=120, dst_height=120),
        capture=dict(width=64),
    )
    result["original_offset_v6"] = copy.deepcopy(result["offset_v6"])
    return result


def test_crop_endpoint_mapping_and_concatenated_right_principal_point(parameters):
    left, right = [diagnostic_lens(parameters, index) for index in (0, 1)]
    assert left["center"] == pytest.approx(np.array([60, 61]) * 63 / 119)
    assert left["focal"] == pytest.approx(np.array([100, 102]) * 63 / 119)
    assert right["center"] == pytest.approx(left["center"])
    report = pixel_diagnostic(parameters, 1, right["center"].tolist())
    assert report["unit_ray"] == pytest.approx([0, 0, 1])
    assert not report["applied_to_renderer"]


def test_unified_projection_inverse_and_far_branch_rejection(parameters):
    lens = diagnostic_lens(parameters, 0)
    rays = np.array([[0.3, 0.4, np.sqrt(0.75)], [-0.6, 0, 0.8]])
    pixels = lens["center"] + lens["focal"] * rays[:, :2] / (rays[:, 2, None] + 2)
    recovered, valid = unproject(pixels, lens)
    assert valid.all()
    assert recovered == pytest.approx(rays, abs=1e-10)
    _, valid = unproject([[0, 0], [-1, 30], [64, 30], [1e300, 30]], lens)
    assert not valid.any()
    with pytest.raises(StitchError, match="no converged"):
        pixel_diagnostic(parameters, 0, [0, 0])


@pytest.mark.parametrize("case", ["guard", "edited", "crop", "odd-crop", "width", "lens"])
def test_diagnostics_reject_uninterpreted_parameter_variants(parameters, case):
    index = 0
    if case == "guard":
        parameters["guard_detected_value"] = 1
    elif case == "edited":
        parameters["original_offset_v6"]["lenses"][0]["xi"] = 3
    elif case == "crop":
        parameters["window_crop_info"]["src_width"] = 129
    elif case == "odd-crop":
        parameters["window_crop_info"].update(dst_width=119, dst_height=119)
    elif case == "width":
        parameters["capture"]["width"] = 121
    else:
        index = True
    with pytest.raises(StitchError):
        diagnostic_lens(parameters, index)


def test_invalid_polynomial_inputs_and_folded_inverse_are_not_valid():
    for points, coefficients in [([[0, 0]], [0] * 12), ([[float("nan"), 0]], [0] * 13)]:
        with pytest.raises(StitchError):
            distort(points, coefficients)
    with pytest.raises(StitchError, match="numerical bounds"):
        distort([[0, 0]], [1e300] * 13)
    coefficients = np.zeros(13)
    coefficients[0] = -1
    _, valid = undistort([[1, 0]], coefficients)
    assert not valid[0]
