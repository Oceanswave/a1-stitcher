import json

import numpy as np
import pytest
from conftest import metadata
from scipy.spatial.transform import Rotation
from test_compare import reference_pair  # noqa: F401

from a1_stitcher.benchmark import benchmark, face_rays, faces, observe
from a1_stitcher.errors import StitchError
from a1_stitcher.mask_proposal import approve, detect_obstructions
from a1_stitcher.occlusion import VisibilityMasks, template, validate, visible_weights
from a1_stitcher.projection import TiledStitcher, lenses_from_metadata
from a1_stitcher.storage import write_new_json
from a1_stitcher.visual import rigid_rotation, tracks, video_frames
from a1_stitcher.visual_sync import fit_timing


def pose(t):
    t = np.asarray(t)
    return Rotation.from_euler(
        "xyz", np.column_stack([0.12 * np.sin(t * 11), 0.16 * np.sin(t * 7), 0.2 * np.sin(t * 3)])
    )


def timing_data(delta=0.011, scale=1.22, moving=True):
    rng = np.random.default_rng(17)
    groups = np.repeat(np.arange(80), 20)
    times = np.column_stack([groups * 0.05 + 1, groups * 0.05 + 1.06])
    rows = rng.uniform(-0.5, 0.5, (len(groups), 2))
    first = rng.normal(size=(len(groups), 3))
    first /= np.linalg.norm(first, axis=1, keepdims=True)
    trajectory = pose if moving else lambda t: Rotation.from_rotvec(np.zeros((len(t), 3)))
    mount = Rotation.from_euler("xyz", [0.1, 0.2, -0.3])
    query = times + delta + rows * 0.021 * scale
    second = (mount.inv() * trajectory(query[:, 1]).inv() * trajectory(query[:, 0]) * mount).apply(
        first
    )
    return first, second, times, rows, groups, trajectory, mount, 0.021


def test_image_fit_recovers_offset_and_row_readout_on_temporal_holdouts():
    result = fit_timing(*timing_data())
    assert result["status"] == "qualified_on_interval"
    assert result["delta_seconds"] == pytest.approx(0.011, abs=2e-5)
    assert result["readout_scale"] == pytest.approx(1.22, abs=0.002)
    assert result["after_holdout"]["median_degrees"] < 1e-4
    assert result["holdout_tracks"] == 800


@pytest.mark.parametrize(
    "moving,delta,scale", [(False, 0.011, 1.22), (True, 0, 1), (True, 0.065, 1.22)]
)
def test_image_fit_rejects_static_no_gain_and_out_of_bounds(moving, delta, scale):
    result = fit_timing(*timing_data(delta, scale, moving))
    assert result["status"] == "rejected"
    assert result["reasons"]


def test_spherical_rotation_ignores_outliers_and_blank_tracks():
    rng = np.random.default_rng(5)
    a = rng.normal(size=(100, 3))
    a /= np.linalg.norm(a, axis=1, keepdims=True)
    rotation = Rotation.from_euler("xyz", [0.03, -0.01, 0.02]).as_matrix()
    b = a @ rotation
    b[:25] = np.roll(b[:25], 1, axis=0)
    fitted, inliers, _ = rigid_rotation(a, b)
    np.testing.assert_allclose(fitted, rotation, atol=1e-8)
    assert inliers.sum() == 75
    image = np.zeros((128, 128, 3), np.uint8)
    assert len(tracks(image, image)[0]) == 0
    with pytest.raises(StitchError):
        rigid_rotation([], [])


def test_mask_proposal_finds_fixed_dark_body_and_abstains_in_static_scene():
    rng = np.random.default_rng(1)
    images = [rng.integers(70, 200, (128, 128, 3), dtype=np.uint8) for _ in range(20)]
    alternate = [i.copy() for i in images]
    for image in images:
        image[50:61, 45:64] = 20
    polygons, info = detect_obstructions(images, alternate, np.ones((128, 128), bool))
    assert info["status"] == "proposed"
    assert len(polygons) > 0
    assert any(np.min(np.array(p)[:, 0]) < 45 / 127 < np.max(np.array(p)[:, 0]) for p in polygons)
    polygons, info = detect_obstructions([images[0]] * 20, alternate, np.ones((128, 128), bool))
    assert not polygons
    assert "movement" in info["reason"]


def test_proposal_review_and_quality_fallback(tmp_path):
    profile = template(metadata(128))
    profile.update(
        schema_version=2,
        alternate_quality="clipping-contrast-v1",
        proposal=dict(status="needs_review"),
    )
    profile["lenses"][0]["exclude_polygons"] = [[[0.4, 0.4], [0.6, 0.4], [0.6, 0.6], [0.4, 0.6]]]
    with pytest.raises(StitchError, match="needs native-overlay review"):
        validate(profile)
    path, out = tmp_path / "proposal.json", tmp_path / "approved.json"
    write_new_json(path, profile)
    approve(path, out, "Reviewed every native overlay; exclusions cover housing only.")
    masks = VisibilityMasks(
        validate(json.loads(out.read_text())), lenses_from_metadata(metadata(128), 128)
    )
    masks.prepare([np.full((128, 128, 3), 255, np.uint8)] * 2)
    assert not np.any(masks.quality)
    preferred = np.array([[1.0, 0.0], [0.0, 1.0]])
    eligible = np.array([[0.0, 1.0], [1.0, 1.0]])
    quality = np.array([[1.0, 0.0], [0.0, 0.0]])
    result = visible_weights(preferred, eligible, quality)
    assert result[:, 0].sum() == 0  # Alternate is clipped, so do not invent coverage.
    assert result[:, 1].sum() == 1  # Quality gate only applies to forced replacements.
    with pytest.raises(StitchError, match="already exists"):
        approve(path, out, "Reviewed every native overlay again.")


@pytest.mark.parametrize("dtype", [np.uint8, np.uint16])
def test_multiband_keeps_identical_signals_and_native_detail(dtype):
    lenses = lenses_from_metadata(metadata(128), 128)
    relative = Rotation.from_euler("y", 180, degrees=True).as_matrix()
    frames = [np.full((128, 128, 3), np.iinfo(dtype).max // 2, dtype)] * 2
    renderer = TiledStitcher(lenses, relative, 256, seam="multiband")
    result, missing = renderer.stitch(frames, np.eye(3))
    assert result.dtype == dtype
    assert missing == 0
    assert not np.any(renderer.seam.correction)
    assert np.max(np.abs(result.astype(float) - frames[0][0, 0])) <= 1


@pytest.mark.integration
def test_contiguous_benchmark_exact_mapping_no_clobber_and_decode(reference_pair, tmp_path):  # noqa: F811
    candidate, reference = reference_pair
    output = tmp_path / "moving"
    result = benchmark(candidate, reference, 1, 3, output)
    assert result["status"] == "benchmarked"
    report = json.loads((output / "benchmark.json").read_text())
    assert [r["reference_frame"] for r in report["frames"]] == [1, 2, 3]
    assert report["coverage"]["motion_pairs_attempted_each"] == 2
    with video_frames(output / "six-view-comparison.mp4", 10, 0, 3, 192, height=64) as stream:
        assert len(list(stream)) == 3
    with pytest.raises(FileExistsError):
        benchmark(candidate, reference, 1, 3, output)
    with pytest.raises(StitchError, match="mapping"):
        benchmark(candidate, reference, 2, 3, tmp_path / "bad")
    assert not (tmp_path / "bad").exists()


def test_blank_benchmark_views_mark_motion_unmeasured():
    rays = face_rays(64)
    views = faces(np.zeros((128, 256, 3), np.uint8), rays)
    assert observe(views, views, rays)["status"] == "unmeasured"


@pytest.mark.integration
def test_bounded_paired_decoder_preserves_selected_frames(synthetic_camera):
    source = synthetic_camera["source"]
    with video_frames(source, 10, 1, 5, 128, paired=True, step=2) as stream:
        rows = list(stream)
    assert [r[0] for r in rows] == [1, 3, 5]
    assert all(len(r[1]) == 2 and r[1][0].shape == (128, 128, 3) for r in rows)


def test_refitted_calibration_enforces_gyro_and_readout_dependencies(
    synthetic_camera, tmp_path, monkeypatch
):
    from a1_stitcher import gyro
    from a1_stitcher.calibration import migrate_legacy, validate_calibration
    from a1_stitcher.render import Options, plan
    from a1_stitcher.storage import fingerprint

    profile = json.loads(synthetic_camera["calibration"].read_text())
    base = fingerprint(profile)
    sensor = {"synthetic": True}
    profile.update(
        schema_version=3,
        frame_clock="nominal",
        visual_sync=dict(
            kind="a1-image-row-sync-v1",
            readout_scale=0.9,
            gyro_profile_fingerprint=fingerprint(sensor),
            base_calibration_fingerprint=base,
            gyro_anchor_seconds=0.1,
            capture_mode=dict(fps="10", readout_seconds=0.02),
        ),
    )
    path = tmp_path / "image-clock.json"
    write_new_json(path, profile)
    with pytest.raises(StitchError):
        migrate_legacy(profile)
    validate_calibration(profile)
    config = dict(
        source=str(synthetic_camera["source"]),
        calibration=str(path),
        output=str(tmp_path / "output.mp4"),
        first_frame=2,
        frames=3,
        backend="cpu",
    )
    from a1_stitcher import render

    monkeypatch.setattr(render, "sensor_readout", lambda *a: 0.02)
    with pytest.raises(StitchError, match="requires its gyro"):
        plan(Options(**config))
    gyro_path = tmp_path / "gyro.json"
    write_new_json(gyro_path, sensor)
    monkeypatch.setattr(gyro, "trajectory", lambda *a: (pose, sensor))
    from a1_stitcher import render

    monkeypatch.setattr(render, "sensor_readout", lambda *a: 0.02)
    config.update(gyro_profile=str(gyro_path), rolling_shutter_model="trajectory")
    recipe = plan(Options(**config))["recipe"]
    assert recipe["rolling_shutter"]["readout_seconds"] == pytest.approx(0.018)
    monkeypatch.setattr(render, "sensor_readout", lambda *a: 0.0201)
    assert plan(Options(**config))["recipe"]["rolling_shutter"]["readout_seconds"] == pytest.approx(
        0.01809
    )
    monkeypatch.setattr(render, "sensor_readout", lambda *a: 0.02)
    with pytest.raises(StitchError, match="different gyro"):
        plan(Options(**config, gyro_anchor_seconds=0.2))
    monkeypatch.setattr(render, "sensor_readout", lambda *a: 0.018)
    with pytest.raises(StitchError, match="different frame-rate/readout"):
        plan(Options(**config))
    monkeypatch.setattr(render, "sensor_readout", lambda *a: 0.02)
    sensor["synthetic"] = False
    with pytest.raises(StitchError, match="different gyro"):
        plan(Options(**config))


@pytest.mark.parametrize(
    "field,value",
    [
        ("readout_scale", float("nan")),
        ("readout_scale", True),
        ("gyro_anchor_seconds", 0),
        ("gyro_profile_fingerprint", "x"),
    ],
)
def test_invalid_visual_schema_rejected(synthetic_camera, field, value):
    from a1_stitcher.calibration import validate_calibration

    profile = json.loads(synthetic_camera["calibration"].read_text())
    profile.update(
        schema_version=3,
        frame_clock="nominal",
        visual_sync=dict(
            kind="a1-image-row-sync-v1",
            readout_scale=1,
            gyro_profile_fingerprint="a" * 64,
            base_calibration_fingerprint="b" * 64,
            gyro_anchor_seconds=0.1,
            capture_mode=dict(fps="10", readout_seconds=0.02),
        ),
    )
    profile["visual_sync"][field] = value
    with pytest.raises(StitchError):
        validate_calibration(profile)


def test_black_rim_is_not_an_obstruction_proposal():
    rng = np.random.default_rng(5)
    images = [rng.integers(70, 200, (128, 128, 3), dtype=np.uint8) for _ in range(20)]
    alternate = [i.copy() for i in images]
    for image in images:
        image[:10] = 0
    polygons, _ = detect_obstructions(images, alternate, np.ones((128, 128), bool))
    assert polygons == []


def test_empty_mask_template_can_be_previewed_but_not_rendered():
    meta = metadata(128)
    profile = template(meta)
    with pytest.raises(StitchError, match="empty template"):
        VisibilityMasks(profile, lenses_from_metadata(meta, 128))
    preview = VisibilityMasks(profile, lenses_from_metadata(meta, 128), preview=True)
    assert all(np.all(m == 1) for m in preview.maps)


@pytest.mark.integration
def test_multiband_receipt_and_full_decode(synthetic_camera, tmp_path):
    from test_jobs import options

    from a1_stitcher.render import stitch

    result = stitch(
        options(synthetic_camera, tmp_path / "bands.mp4", seam="multiband", backend="cpu")
    )
    assert result["verification"]["full_decode"]
    data = json.loads(open(result["receipt"]).read())
    assert data["recipe"]["seam"] == "three-band-flow-local-balance-v1"


def test_image_fit_rejects_insufficient_row_coverage():
    data = list(timing_data())
    data[3] = np.zeros_like(data[3])
    with pytest.raises(StitchError, match="row coverage"):
        fit_timing(*data)


def test_sync_command_abstains_on_blank_recording_without_writing_profile(
    synthetic_camera, tmp_path, monkeypatch
):
    from contextlib import contextmanager

    from a1_stitcher import gyro, media, visual
    from a1_stitcher.visual_sync import calibrate

    actual = media.source_profile
    monkeypatch.setattr(media, "source_profile", lambda *a: actual(*a) | dict(frames=100))
    monkeypatch.setattr(gyro, "trajectory", lambda *a: (pose, {"synthetic": True}))

    @contextmanager
    def blank(*args, **kwargs):
        yield iter((n, [np.zeros((768, 768, 3), np.uint8)] * 2) for n in range(60))

    monkeypatch.setattr(visual, "video_frames", blank)
    sensor = tmp_path / "gyro.json"
    write_new_json(sensor, {"synthetic": True})
    output, evidence = tmp_path / "refit.json", tmp_path / "evidence"
    result = calibrate(
        synthetic_camera["source"], synthetic_camera["calibration"], sensor, 0, 60, output, evidence
    )
    assert result["status"] == "rejected"
    assert not output.exists()
    assert (evidence / "fit.json").exists()


def test_multiband_limits_temporal_gain_change_and_resets_unsupported_analysis(monkeypatch):
    import a1_stitcher.seam as seam

    lenses = lenses_from_metadata(metadata(128), 128)
    model = seam.OverlapSeam(
        lenses, Rotation.from_euler("y", 180, degrees=True).as_matrix(), 256, multiband=True
    )
    state = dict(value=0.1, supported=True)
    monkeypatch.setattr(
        seam,
        "color_ratio",
        lambda *a: (np.full((1, model.width, 3), state["value"], np.float32), state["supported"]),
    )
    frames = [np.full((128, 128, 3), 120, np.uint16)] * 2
    model.prepare(frames)
    previous = model.log_ratio.copy()
    state["value"] = -0.4
    model.prepare(frames)
    assert np.max(np.abs(model.log_ratio - previous)) <= 0.010001
    state["supported"] = False
    old = np.linalg.norm(model.log_ratio)
    model.prepare(frames)
    assert np.linalg.norm(model.log_ratio) < old
    assert not model.correction.any()


@pytest.mark.parametrize("focal_scale", [1.0, 0.9])
def test_multiband_reduces_broad_brightness_step_without_changing_distant_pixels(
    monkeypatch, focal_scale
):
    import a1_stitcher.seam as seam

    # Isolate image fusion from correspondence and gain estimation: two known
    # uniform signals with valid overlap and an unresolved brightness mismatch.
    def correspondence(a, b, valid, pixel):
        return [np.zeros((*valid.shape, 2), np.float32)] * 2, [valid.astype(np.float32)] * 2

    monkeypatch.setattr(seam, "matched_flow", correspondence)
    monkeypatch.setattr(
        seam, "color_ratio", lambda a, b, v: (np.zeros((1, a.shape[1], 3), np.float32), False)
    )
    meta = metadata(128)
    for index in [2, 3, 21, 22]:
        meta["offset_v3"][index] *= focal_scale
    lenses = lenses_from_metadata(meta, 128)
    relative = Rotation.from_euler("y", 180, degrees=True).as_matrix()
    frames = [np.full((128, 128, 3), value, np.uint16) for value in [30000, 36000]]
    outputs = [
        TiledStitcher(lenses, relative, 1024, seam=mode).stitch(frames, np.eye(3))[0]
        for mode in ["flow", "multiband"]
    ]
    edges = [np.max(np.abs(np.diff(image[256, 225:288, 0].astype(float)))) for image in outputs]
    assert edges[1] < edges[0] * 0.5
    # Stay away from the poles, where this camera-fixed seam crosses longitude.
    np.testing.assert_array_equal(outputs[0][200:312, 480:544], outputs[1][200:312, 480:544])
