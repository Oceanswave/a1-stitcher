import json
import struct
from pathlib import Path

import cv2
import numpy as np
import pytest
import tifffile
from conftest import metadata, pb, trailer
from PIL import Image
from scipy.spatial.transform import Rotation

from a1_stitcher.errors import StitchError
from a1_stitcher.photo import export_photo, panorama_xmp, verify_photo
from a1_stitcher.projection import lenses_from_metadata, unproject
from a1_stitcher.storage import digest


@pytest.fixture
def photo_original(tmp_path):
    width = 512
    meta = metadata(width)
    rng = np.random.default_rng(12)
    sphere = cv2.GaussianBlur(rng.integers(0, 256, (1024, 2048, 3), dtype=np.uint8), (0, 0), 2)
    for _ in range(800):
        x, y = rng.integers([0, 0], [2048, 1024])
        color = rng.integers(0, 256, 3)
        cv2.circle(sphere, (int(x), int(y)), int(rng.integers(2, 12)), color.tolist(), -1)
    grid = np.indices((width, width))[::-1].reshape(2, -1).T
    frames = []
    for i, lens in enumerate(lenses_from_metadata(meta, width)):
        rays, valid = unproject(grid, lens)
        if i:
            rays = Rotation.from_euler("y", 180, degrees=True).apply(rays)
        u = (
            ((np.arctan2(rays[:, 0], rays[:, 2]) / (2 * np.pi) + 0.5) * 2048 - 0.5)
            .reshape(width, width)
            .astype("float32")
        )
        v = (
            ((np.arcsin(np.clip(rays[:, 1], -1, 1)) / np.pi + 0.5) * 1024 - 0.5)
            .reshape(width, width)
            .astype("float32")
        )
        f = cv2.remap(sphere, u, v, cv2.INTER_CUBIC, borderMode=cv2.BORDER_WRAP)
        f.reshape(-1, 3)[~valid] = 0
        frames.append(f)
    p = tmp_path / "original.insp"
    Image.fromarray(np.concatenate(frames, axis=1)[:, :, ::-1]).save(
        p, format="JPEG", quality=98, subsampling=0
    )
    record = b"".join(
        [
            pb(2, meta["camera_type"]),
            pb(19, pb(1, width * 2) + pb(2, width)),
            pb(24, 10_000_000),
            pb(54, "_".join(map(str, meta["offset_v3"]))),
        ]
    )
    view = struct.pack("<Q11f", 10_000_000, 0, 100, 100, 0, 1, 0, 0, 0, 1, 0, 0) + bytes(68)
    with p.open("ab") as stream:
        stream.write(trailer([(1, record), (32, view)]))
    return p


def test_original_only_rgb16_tiff_panorama_tags_and_resume(photo_original, tmp_path):
    original_sha = digest(photo_original)
    out = tmp_path / "sphere.tiff"
    result = export_photo(photo_original, out, backend="cpu")
    assert result["status"] == "created"
    assert result["verification"]["bits_per_sample"] == 16
    assert result["verification"]["width"] == 1024
    with tifffile.TiffFile(out) as im:
        assert im.pages[0].compression.name == "DEFLATE"
        pixels = im.asarray()
        assert pixels.dtype == np.uint16
        assert np.any(pixels % 257)  # Interpolation retained values between input byte levels.
        assert b"equirectangular" in im.pages[0].tags[700].value
    assert digest(photo_original) == original_sha
    assert export_photo(photo_original, out, backend="cpu", resume=True)["status"] == "reused"
    with pytest.raises(StitchError, match="already exists"):
        export_photo(photo_original, out, backend="cpu")
    with pytest.raises(StitchError, match="changed"):
        export_photo(photo_original, out, backend="cpu", resume=True, width=512)
    receipt = Path(result["receipt"])
    data = json.loads(receipt.read_text())
    data["output_sha256"] = "0" * 64
    receipt.write_text(json.dumps(data))
    with pytest.raises(StitchError, match="checksum"):
        verify_photo(out, receipt)


@pytest.mark.parametrize("kind", ["8bit", "missing", "bad_dimensions", "wrong_projection"])
def test_tiff_verification_rejects_false_sphere_claims(tmp_path, kind):
    dtype = np.uint8 if kind == "8bit" else np.uint16
    pixels = np.zeros((32, 64, 3), dtype=dtype)
    xmp = panorama_xmp(128 if kind == "bad_dimensions" else 64, 32)
    if kind == "wrong_projection":
        xmp = xmp.replace(b"equirectangular", b"fisheye")
    tags = [] if kind == "missing" else [(700, "B", len(xmp), xmp, False)]
    p = tmp_path / "bad.tiff"
    tifffile.imwrite(p, pixels, photometric="rgb", extratags=tags)
    with pytest.raises(StitchError):
        verify_photo(p)


def test_photo_refuses_input_overwrite_and_upscale(photo_original, tmp_path):
    out = tmp_path / "link.tiff"
    out.symlink_to(photo_original)
    with pytest.raises(StitchError, match="overwrite"):
        export_photo(photo_original, out, backend="cpu")
    with pytest.raises(StitchError, match="source resolution"):
        export_photo(photo_original, tmp_path / "up.tiff", width=2048, backend="cpu")
