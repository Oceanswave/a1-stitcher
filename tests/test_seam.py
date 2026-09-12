import cv2
import numpy as np
import pytest
from conftest import metadata
from scipy.spatial.transform import Rotation

from a1_stitcher.errors import StitchError
from a1_stitcher.projection import (
    TiledStitcher,
    lenses_from_metadata,
    sphere_rays,
    unproject,
)
from a1_stitcher.seam import OverlapSeam, color_ratio, matched_flow, periodic_sample


def texture(height=96, width=512):
    rng = np.random.default_rng(49)
    pixels = rng.uniform(30, 200, (height, width)).astype(np.float32)
    pixels = cv2.GaussianBlur(pixels, (0, 0), 1.1)
    pixels = np.clip((pixels - 110) * 3 + 110, 20, 220).astype(np.uint8)
    return np.repeat(pixels[:, :, None], 3, axis=2)


def test_bidirectional_flow_recovers_subpixel_disparity():
    first = texture()
    y, x = np.indices(first.shape[:2], dtype=np.float32)
    second = periodic_sample(first, x - 2.5, y + 1.25)
    valid = np.ones(first.shape[:2], bool)
    pixel = np.array([2 * np.pi / 1024, np.radians(16) / first.shape[0]])
    flows, confidence = matched_flow(first, second, valid, pixel)
    roi = np.s_[20:-20, 40:-40]
    trusted = confidence[0][roi] > 0.5
    assert trusted.mean() > 0.8
    error = np.linalg.norm(flows[0][roi] - [2.5, -1.25], axis=-1)
    assert np.median(error[trusted]) < 0.3
    aligned = periodic_sample(second, x + flows[0][:, :, 0], y + flows[0][:, :, 1])
    before = np.abs(first[roi].astype(float) - second[roi]).mean()
    after = np.abs(first[roi].astype(float) - aligned[roi]).mean()
    assert after < before * 0.3


def test_flat_or_invalid_overlap_does_not_invent_motion():
    blank = np.full((64, 512, 3), 90, np.uint8)
    for valid in [np.ones((64, 512), bool), np.zeros((64, 512), bool)]:
        flows, confidence = matched_flow(blank, blank, valid, np.array([0.006, 0.004]))
        assert all(np.isfinite(f).all() for f in flows)
        assert all(np.max(c) == 0 for c in confidence)


@pytest.mark.parametrize("bad_value", [100, float("nan")])
def test_excessive_flow_is_rejected(monkeypatch, bad_value):
    class Impossible:
        def setFinestScale(self, value):
            pass

        def calc(self, a, b, initial):
            return np.full((*a.shape, 2), bad_value, np.float32)

    monkeypatch.setattr(cv2, "DISOpticalFlow_create", lambda _: Impossible())
    pixels = texture()
    _, confidence = matched_flow(
        pixels, pixels, np.ones(pixels.shape[:2], bool), np.array([0.006, 0.004])
    )
    assert all(np.max(c) == 0 for c in confidence)


def test_periodic_sampling_wraps_only_longitude():
    grid = np.arange(12, dtype=np.float32).reshape(3, 4)
    result = periodic_sample(
        grid, np.array([[-1, 4, 1]], np.float32), np.array([[-1, 3, 0]], np.float32)
    )
    assert np.array_equal(result, [[3, 8, 1]])


def test_robust_color_balance_recovers_gain_and_rejects_clipping():
    first = texture()
    second = np.clip(first.astype(float) * [1.3, 1.1, 0.8], 0, 255).astype(np.uint8)
    ratio, good = color_ratio(first, second, np.ones(first.shape[:2], bool))
    assert good
    assert np.allclose(np.exp(ratio).mean(axis=(0, 1)), [1.3, 1.1, 0.8], atol=0.02)
    assert np.max(np.abs(ratio[:, 0] - ratio[:, -1])) < 0.01
    ratio, good = color_ratio(first, np.full_like(first, 255), np.ones(first.shape[:2], bool))
    assert not good and not ratio.any()


def test_color_balance_is_bounded():
    ratio, good = color_ratio(
        np.full((64, 512, 3), 20, np.uint8),
        np.full((64, 512, 3), 220, np.uint8),
        np.ones((64, 512), bool),
    )
    assert good
    assert np.max(np.abs(ratio)) <= np.log(2) + 1e-6


def test_corrected_projection_reduces_synthetic_seam_ghosting():
    width = 512
    lenses = lenses_from_metadata(metadata(), width)
    relative = Rotation.from_euler("y", 180, degrees=True).as_matrix()
    # A spherical texture provides a known answer; shift only the second sensor
    # to simulate a small residual disparity not explained by static calibration.
    scene = texture(512, 1024)
    xx, yy = np.meshgrid(np.arange(width), np.arange(width))
    frames = []
    for index, lens in enumerate(lenses):
        rays, valid = unproject(np.column_stack([xx.ravel(), yy.ravel()]), lens)
        if index:
            rays = rays @ relative.T
            rays = Rotation.from_euler("z", -0.65, degrees=True).apply(rays)
        az = (np.arctan2(rays[:, 1], rays[:, 0]) + np.pi) / (2 * np.pi) * scene.shape[1] - 0.5
        lat = (np.arcsin(rays[:, 2]) + np.pi / 2) / np.pi * scene.shape[0] - 0.5
        frame = periodic_sample(scene, az.reshape(width, width), lat.reshape(width, width))
        frame.reshape(-1, 3)[~valid] = 0
        frames.append(frame)
    old, miss0 = TiledStitcher(lenses, relative, 1024).stitch(frames, np.eye(3))
    new, miss1 = TiledStitcher(lenses, relative, 1024, seam="flow").stitch(frames, np.eye(3))
    assert miss0 == miss1 == 0
    rays = sphere_rays(1024)
    az = (np.arctan2(rays[:, :, 1], rays[:, :, 0]) + np.pi) / (2 * np.pi) * scene.shape[1] - 0.5
    lat = (np.arcsin(rays[:, :, 2]) + np.pi / 2) / np.pi * scene.shape[0] - 0.5
    expected = periodic_sample(scene, az, lat)
    # Outside the narrow seam the first lens should retain its undoubled detail.
    roi = (rays[:, :, 2] > 0.025) & (rays[:, :, 2] < 0.075)
    old_error = np.abs(old.astype(float) - expected)[roi].mean()
    new_error = np.abs(new.astype(float) - expected)[roi].mean()
    assert new_error < old_error * 0.75, (old_error, new_error)


def test_balance_does_not_brighten_clean_lens_or_change_distant_pixels():
    lenses = lenses_from_metadata(metadata(), 128)
    relative = Rotation.from_euler("y", 180, degrees=True).as_matrix()
    seam = OverlapSeam(lenses, relative, 512)
    seam.flows = [np.zeros((seam.height, seam.width, 2), np.float32)] * 2
    seam.confidence = [np.zeros((seam.height, seam.width), np.float32)] * 2
    seam.log_ratio = np.full((1, seam.width, 3), np.log(1.5), np.float32)
    rays = seam.directions(np.zeros((1, 2)), np.array([[0, np.pi / 2]]))
    directions, alpha, gains = seam.sample(rays)
    assert np.allclose(gains[0], 1)
    assert np.allclose(gains[1][0, 0], 1 / 1.5)
    assert np.allclose(gains[1][0, 1], 1)
    assert np.allclose(directions[0], rays)
    assert alpha[0, 0] == pytest.approx(0.5)


def test_invalid_seam_mode_rejected():
    with pytest.raises(StitchError, match="Seam"):
        TiledStitcher([], np.eye(3), 256, seam="invented")


def test_unmeasured_color_arc_is_not_interpolated_from_distant_sectors():
    first = np.full((64, 1024, 3), 70, np.uint8)
    second = np.full_like(first, 140)
    valid = np.ones((64, 1024), bool)
    valid[:, 256:768] = False
    ratio, good = color_ratio(first, second, valid)
    assert good
    assert np.max(np.abs(ratio[:, 430:595])) < 1e-4
    assert np.exp(ratio[:, 40:160]).mean() > 1.9


def test_color_measurement_cannot_paint_a_band_outside_the_overlap():
    lenses = lenses_from_metadata(metadata(), 128)
    seam = OverlapSeam(lenses, Rotation.from_euler("y", 180, degrees=True).as_matrix(), 512)
    seam.flows = [np.zeros((seam.height, seam.width, 2), np.float32)] * 2
    seam.confidence = [np.zeros((seam.height, seam.width), np.float32)] * 2
    seam.log_ratio = np.full((1, seam.width, 3), np.log(2), np.float32)
    rays = seam.directions(np.zeros((1, 4)), np.radians([[0, 8, 12, -20]]))
    _, _, gains = seam.sample(rays)
    assert gains[1][0, 0, 0] == pytest.approx(0.5)
    for gain in gains:
        assert np.allclose(gain[0, 1:], 1, rtol=0, atol=1e-12)
