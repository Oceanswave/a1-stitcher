from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from conftest import metadata
from scipy.spatial.transform import Rotation

from a1_stitcher.encoding import check_encoder, encoding_profile
from a1_stitcher.errors import StitchError
from a1_stitcher.media import verify
from a1_stitcher.projection import TiledStitcher, lenses_from_metadata
from a1_stitcher.render import Options, plan, stitch


@pytest.mark.parametrize(
    "name,extension,codec,pixel_format",
    [
        ("hevc10", ".mp4", "hevc", "yuv420p10le"),
        ("prores", ".mov", "prores", "yuv422p10le"),
    ],
)
@pytest.mark.integration
def test_finishing_export_precision_metadata_and_resume(
    synthetic_camera, tmp_path, name, extension, codec, pixel_format
):
    output = tmp_path / ("master" + extension)
    config = Options(
        str(synthetic_camera["source"]),
        str(synthetic_camera["calibration"]),
        str(output),
        first_frame=1,
        frames=3,
        width=256,
        lens_width=128,
        threads=1,
        encoding=name,
    )
    result = stitch(config)
    assert result["verification"]["codec"] == codec
    assert result["verification"]["pixel_format"] == pixel_format
    assert result["verification"]["full_decode"]
    assert stitch(replace(config, resume=True))["status"] == "reused"
    contents = output.read_bytes()
    assert contents.index(b"moov") < contents.index(b"mdat")
    with pytest.raises(StitchError, match="pix_fmt"):
        verify(
            output, expected=dict(width=256, height=128, nb_frames=3, fps="10", pix_fmt="yuv420p")
        )
    if name == "hevc10":
        with pytest.raises(StitchError, match="changed"):
            stitch(replace(config, resume=True, encoding="h264"))
    else:
        assert (
            plan(config)["recipe_sha256"]
            != plan(replace(config, encoding="h264", output=str(output.with_suffix(".mp4"))))[
                "recipe_sha256"
            ]
        )


@pytest.mark.parametrize("seam", ["feather", "flow", "adaptive"])
def test_sub_8bit_signal_survives_stitch(seam):
    lenses = lenses_from_metadata(metadata(128), 128)
    relative = Rotation.from_euler("y", 180, degrees=True).as_matrix()
    frames = [np.full((128, 128, 3), 32001, np.uint16) for _ in range(2)]
    renderer = TiledStitcher(lenses, relative, 256, seam=seam)
    result, missing = renderer.stitch(frames, np.eye(3))
    assert result.dtype == np.uint16 and missing == 0
    assert np.max(np.abs(result.astype(float) - 32001)) <= 1
    assert np.max(np.abs(result.astype(float) / 257 - np.rint(result.astype(float) / 257))) > 0.1


def test_bad_encoding_and_extension_rejected_before_writes(synthetic_camera, tmp_path):
    config = Options(
        str(synthetic_camera["source"]),
        str(synthetic_camera["calibration"]),
        str(tmp_path / "new" / "master.mp4"),
        first_frame=0,
        frames=2,
        encoding="prores",
    )
    with pytest.raises(StitchError, match=".mov"):
        plan(config)
    with pytest.raises(StitchError, match="Encoding must"):
        plan(replace(config, encoding="made-up"))
    assert not Path(config.output).parent.exists()


def test_missing_optional_encoder_fails_preflight(monkeypatch):
    import a1_stitcher.encoding as module

    monkeypatch.setattr(module, "run", lambda *a: b" V..... libx264 H.264\n")
    with pytest.raises(StitchError, match="lacks"):
        check_encoder("ffmpeg", encoding_profile("prores"))


def test_lens_precision_and_shape_must_match():
    renderer = TiledStitcher(
        lenses_from_metadata(metadata(128), 128),
        Rotation.from_euler("y", 180, degrees=True).as_matrix(),
        128,
    )
    frame = np.ones((128, 128, 3), np.uint16)
    with pytest.raises(StitchError, match="precision"):
        renderer.stitch([frame, frame.astype(np.uint8)], np.eye(3))
    with pytest.raises(StitchError, match="two uint"):
        renderer.stitch([frame.astype(float)] * 2, np.eye(3))
