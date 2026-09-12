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


@pytest.mark.skipif(
    os.environ.get("A1_TEST_METAL") != "1", reason="Set A1_TEST_METAL=1 on a Metal host"
)
@pytest.mark.parametrize("seam", ["feather", "flow", "adaptive"])
@pytest.mark.parametrize("dtype", [np.uint8, np.uint16])
@pytest.mark.parametrize("readout", [0, 0.021])
def test_gpu_matches_cpu(seam, dtype, readout):
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
    cpu = TiledStitcher(lenses, relative, 256, **args)
    gpu = MetalStitcher(lenses, relative, 256, **args)
    for _ in range(2):
        a, ma = cpu.stitch(frames, rotation, [2, -3, 1])
        b, mb = gpu.stitch(frames, rotation, [2, -3, 1])
        difference = np.abs(a.astype(float) - b.astype(float)) / (257 if dtype == np.uint16 else 1)
        assert difference.mean() < 0.15
        assert np.percentile(difference, 99.9) <= 2
        assert abs(ma - mb) < 0.0001
    gpu.close()
    with pytest.raises(StitchError, match="closed"):
        gpu.stitch(frames, rotation)
