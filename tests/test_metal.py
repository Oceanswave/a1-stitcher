"""Hardware parity is opt-in; unsupported hosts still exercise clean diagnostics."""

import os

import numpy as np
import pytest
from conftest import metadata
from scipy.spatial.transform import Rotation

from a1_stitcher.errors import StitchError
from a1_stitcher.projection import TiledStitcher, lenses_from_metadata


def test_unsupported_host(monkeypatch):
    from a1_stitcher import metal

    monkeypatch.setattr(metal, "_RUNTIME", None)
    monkeypatch.setattr(metal.platform, "system", lambda: "Linux")
    with pytest.raises(StitchError, match="Metal requires"):
        metal.runtime()


@pytest.mark.skipif(os.environ.get("A1_TEST_METAL") != "1", reason="Requires Metal GPU")
def test_mask_fallback_and_uncovered_pixel_failure_on_gpu():
    from a1_stitcher.metal import MetalStitcher
    from a1_stitcher.occlusion import template
    from a1_stitcher.projection import sphere_rays

    meta = metadata(128)
    # Give the synthetic alternate lens enough field of view for a five-degree exclusion.
    for index in [2, 3, 21, 22]:
        meta["offset_v3"][index] *= 0.8
    lenses = lenses_from_metadata(meta, 128)
    relative = Rotation.from_euler("y", 180, degrees=True).as_matrix()
    frames = [
        np.full((128, 128, 3), [0, 0, 255], np.uint8),
        np.full((128, 128, 3), [0, 200, 0], np.uint8),
    ]
    data = template(meta)
    data["lenses"][0]["max_angle_degrees"] = 85
    data["lenses"][1]["max_angle_degrees"] = 105
    args = dict(seam="flow", occlusion=data)
    cpu = TiledStitcher(lenses, relative, 256, **args)
    gpu = MetalStitcher(lenses, relative, 256, **args)
    try:
        a, _ = cpu.stitch(frames, np.eye(3))
        b, missing = gpu.stitch(frames, np.eye(3))
        z = sphere_rays(256)[..., 2]
        # The default flow preference is entirely lens 0 here; it is excluded.
        region = (z > 0.04) & (z < 0.06)
        np.testing.assert_array_equal(a[region], b[region])
        assert np.all(b[region, 2] == 0)
        assert np.all(b[region, 1] > 0)
        assert missing == 0
    finally:
        gpu.close()

    data["lenses"][1]["max_angle_degrees"] = 85
    gpu = MetalStitcher(lenses, relative, 256, seam="flow", occlusion=data)
    try:
        with pytest.raises(StitchError, match="both lenses"):
            gpu.stitch(frames, np.eye(3))
    finally:
        gpu.close()


@pytest.mark.skipif(os.environ.get("A1_TEST_METAL") != "1", reason="Requires Metal GPU")
def test_reviewed_quality_mask_rejects_clipped_alternate_on_both_backends():
    from a1_stitcher.metal import MetalStitcher
    from a1_stitcher.occlusion import template

    meta = metadata(128)
    for index in [2, 3, 21, 22]:
        meta["offset_v3"][index] *= 0.8
    lenses = lenses_from_metadata(meta, 128)
    relative = Rotation.from_euler("y", 180, degrees=True).as_matrix()
    profile = template(meta)
    profile.update(
        schema_version=2,
        alternate_quality="clipping-contrast-v1",
        proposal=dict(status="reviewed", review_notes="Synthetic fixture visibility verified."),
    )
    profile["lenses"][0]["max_angle_degrees"] = 85
    profile["lenses"][1]["max_angle_degrees"] = 105
    frames = [np.full((128, 128, 3), 120, np.uint8), np.full((128, 128, 3), 255, np.uint8)]
    for renderer in [
        TiledStitcher(lenses, relative, 256, seam="multiband", occlusion=profile),
        MetalStitcher(lenses, relative, 256, seam="multiband", occlusion=profile),
    ]:
        try:
            with pytest.raises(StitchError, match="both lenses"):
                renderer.stitch(frames, np.eye(3))
        finally:
            if isinstance(renderer, MetalStitcher):
                renderer.close()


@pytest.mark.skipif(
    os.environ.get("A1_TEST_METAL") != "1", reason="Set A1_TEST_METAL=1 on a Metal host"
)
@pytest.mark.parametrize("seam", ["feather", "flow", "adaptive", "multiband"])
@pytest.mark.parametrize("dtype", [np.uint8, np.uint16])
@pytest.mark.parametrize("readout", [0, 0.021])
@pytest.mark.parametrize("model", ["velocity", "trajectory"])
@pytest.mark.parametrize("masked", [False, True])
def test_gpu_matches_cpu(seam, dtype, readout, model, masked):
    from a1_stitcher.metal import MetalStitcher

    lenses = lenses_from_metadata(metadata(128), 128)
    relative = Rotation.from_euler("y", 180, degrees=True).as_matrix()
    rotation = Rotation.from_euler("xyz", [0.3, 0.5, 0.4]).as_matrix()
    y, x = np.mgrid[:128, :128]
    frames = [
        np.stack(
            [
                100 + 45 * np.sin(x / 9 + i),
                110 + 60 * np.sin(y / 11 + i),
                120 + 80 * np.sin((x + y) / 7),
            ],
            axis=2,
        )
        for i in range(2)
    ]
    frames = [(f * (257 if dtype == np.uint16 else 1)).astype(dtype) for f in frames]
    args = dict(seam=seam, readout_seconds=readout)
    if masked:
        from test_occlusion import profile

        args["occlusion"] = profile()
    cpu = TiledStitcher(lenses, relative, 256, **args)
    gpu = MetalStitcher(lenses, relative, 256, **args)
    rows = None
    if model == "trajectory":
        from test_motion import vibration

        from a1_stitcher.motion import row_rotations

        rows = row_rotations(vibration, 0, Rotation.identity(), relative, 0.021)
    for _ in range(2):
        a, ma = cpu.stitch(frames, rotation, [2, -3, 1], rows)
        b, mb = gpu.stitch(frames, rotation, [2, -3, 1], rows)
        difference = np.abs(a.astype(float) - b.astype(float)) / (257 if dtype == np.uint16 else 1)
        assert difference.mean() < 0.15
        assert np.percentile(difference, 99.9) <= 2
        assert abs(ma - mb) < 0.0001
    gpu.close()
    with pytest.raises(StitchError, match="closed"):
        gpu.stitch(frames, rotation)
