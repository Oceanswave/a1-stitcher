"""Synthetic body masks; every replacement is sourced from another real image."""

import copy
import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from conftest import metadata
from scipy.spatial.transform import Rotation
from test_jobs import options

from a1_stitcher.cli import main
from a1_stitcher.errors import StitchError
from a1_stitcher.occlusion import VisibilityMasks, template, validate
from a1_stitcher.projection import TiledStitcher, lenses_from_metadata
from a1_stitcher.render import plan, stitch


def profile():
    data = template(metadata())
    for lens in data["lenses"]:
        lens["max_angle_degrees"] = 94
    return data


def test_mask_template_binds_camera_and_accessory(tmp_path, synthetic_camera):
    output = tmp_path / "visibility.json"
    assert main(["mask-template", str(synthetic_camera["source"]), "--output", str(output)]) == 0
    empty = json.loads(output.read_text())
    assert empty["propeller_guard_status"] == 0
    with pytest.raises(StitchError, match="empty template"):
        validate(empty)
    assert main(["mask-template", str(synthetic_camera["source"]), "--output", str(output)]) == 1
    other = metadata()
    other["propeller_guard_status"] = 1
    with pytest.raises(StitchError, match="guard configuration differs"):
        validate(profile(), other)
    other["offset_v3"][1] += 0.01
    with pytest.raises(StitchError, match="another camera"):
        validate(profile(), other)


@pytest.mark.parametrize(
    "change",
    [
        {"feather_pixels": 0},
        {"propeller_guard_status": True},
        {"lenses": []},
        {"lens_fingerprint": "invalid"},
        {"schema_version": 2},
    ],
)
def test_invalid_mask_configuration(change):
    data = profile()
    data.update(change)
    with pytest.raises(StitchError):
        validate(data)


def test_polygon_is_native_image_space_and_softens_only_visible_side():
    data = profile()
    data["lenses"][0] = dict(
        max_angle_degrees=None,
        exclude_polygons=[
            [[0.4, 0.4], [0.6, 0.4], [0.6, 0.6], [0.4, 0.6]],
        ],
    )
    masks = VisibilityMasks(data, lenses_from_metadata(metadata(), 128))
    values = masks.sample(0, np.array([63.5, 46.0, 50.3, 52.0]), np.full(4, 63.5))
    assert values[0] == values[3] == 0
    assert values[1] == 1
    assert 0 < values[2] < 1
    data["lenses"][0]["exclude_polygons"][0][0][0] = -1
    with pytest.raises(StitchError, match="normalized"):
        validate(data)


def test_obstructed_lens_is_replaced_without_inventing_pixels():
    lenses = lenses_from_metadata(metadata(), 128)
    relative = Rotation.from_euler("y", 180, degrees=True).as_matrix()
    # The first lens contains a synthetic red body; lens two sees solid green scene.
    frames = [
        np.full((128, 128, 3), [0, 0, 255], np.uint8),
        np.full((128, 128, 3), [0, 200, 0], np.uint8),
    ]
    data = profile()
    data["lenses"][0]["max_angle_degrees"] = 89
    output, missing = TiledStitcher(lenses, relative, 256, occlusion=data).stitch(frames, np.eye(3))
    baseline, _ = TiledStitcher(lenses, relative, 256).stitch(frames, np.eye(3))
    # Rays slightly beyond the first optical hemisphere still received red in legacy feather.
    from a1_stitcher.projection import sphere_rays

    z = sphere_rays(256)[:, :, 2]
    region = (z < -0.025) & (z > -0.07)
    assert (baseline[region, 2] > 0).mean() > 0.9
    np.testing.assert_array_equal(output[region], np.tile([0, 200, 0], (region.sum(), 1)))
    assert missing == 0
    # Excluding both hemisphere rims creates a real gap; do not silently output black pixels.
    data["lenses"][1]["max_angle_degrees"] = 89
    with pytest.raises(StitchError, match="both lenses"):
        TiledStitcher(lenses, relative, 256, occlusion=data).stitch(frames, np.eye(3))


@pytest.mark.integration
def test_mask_profile_participates_in_plan_receipt_and_reuse(synthetic_camera, tmp_path):
    path = tmp_path / "mask.json"
    path.write_text(json.dumps(profile()))
    config = options(synthetic_camera, tmp_path / "masked.mp4", occlusion_profile=str(path))
    job = plan(config)
    assert job["recipe"]["occlusion_profile"] == profile()
    result = stitch(config)
    assert result["verification"]["full_decode"]
    receipt = json.loads(Path(result["receipt"]).read_text())
    assert "other real lens" in receipt["limitations"][3]
    assert stitch(replace(config, resume=True))["status"] == "reused"
    data = copy.deepcopy(profile())
    data["feather_pixels"] = 4
    path.write_text(json.dumps(data))
    with pytest.raises(StitchError, match="changed"):
        stitch(replace(config, resume=True))
    with pytest.raises(StitchError, match="overwrite"):
        plan(replace(config, output=str(path)))


@pytest.mark.integration
def test_preview_displays_exclusions_and_keeps_existing_files(synthetic_camera, tmp_path):
    import cv2

    from a1_stitcher.occlusion import preview

    path = tmp_path / "mask.json"
    path.write_text(json.dumps(profile()))
    directory = tmp_path / "preview"
    result = preview(synthetic_camera["source"], path, 3, directory)
    assert result["source_frame"] == 3
    original = cv2.imread(str(directory / "lens-0-source.png"))
    marked = cv2.imread(str(directory / "lens-0-mask.png"))
    assert np.any(original != marked)
    np.testing.assert_array_equal(original[64, 64], marked[64, 64])
    with pytest.raises(FileExistsError):
        preview(synthetic_camera["source"], path, 3, directory)
    with pytest.raises(StitchError, match="outside"):
        preview(synthetic_camera["source"], path, -1, tmp_path / "invalid")
    assert not (tmp_path / "invalid").exists()


def test_batch_resolves_mask_path_and_prevents_collision(synthetic_camera, tmp_path, monkeypatch):
    import a1_stitcher.render as render

    path = tmp_path / "mask.json"
    path.write_text(json.dumps(profile()))
    job = dict(
        source=str(synthetic_camera["source"]),
        calibration=str(synthetic_camera["calibration"]),
        first_frame=2,
        frames=2,
        width=256,
        output="batch.mp4",
        occlusion_profile="mask.json",
    )
    manifest = tmp_path / "jobs.json"
    manifest.write_text(json.dumps(dict(schema_version=1, jobs=[job])))
    calls = []
    monkeypatch.setattr(render, "stitch", lambda opts, **kwargs: calls.append(opts))
    assert main(["batch", str(manifest), "--dry-run"]) == 0
    assert calls[0].occlusion_profile == str(path)
    job["output"] = "mask.json"
    manifest.write_text(json.dumps(dict(schema_version=1, jobs=[job])))
    assert main(["batch", str(manifest), "--dry-run"]) == 1
    assert len(calls) == 1


@pytest.mark.integration
def test_uncovered_mask_never_publishes_a_video(synthetic_camera, tmp_path):
    data = profile()
    for lens in data["lenses"]:
        lens["max_angle_degrees"] = 85
    mask = tmp_path / "blocked.json"
    mask.write_text(json.dumps(data))
    output = tmp_path / "blocked.mp4"
    with pytest.raises(StitchError, match="both lenses"):
        stitch(options(synthetic_camera, output, occlusion_profile=str(mask), backend="cpu"))
    assert not output.exists()
    assert not Path(str(output) + ".receipt.json").exists()
    assert not list(tmp_path.glob(".a1-stitch-*"))
