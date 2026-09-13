import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from scipy.spatial.transform import Rotation
from test_jobs import options

from a1_stitcher.automatic import fit_overlap
from a1_stitcher.calibration import validate_calibration
from a1_stitcher.errors import StitchError
from a1_stitcher.media import verify
from a1_stitcher.render import plan, stitch
from a1_stitcher.storage import digest


def mock_fits(monkeypatch, angles):
    values = iter(angles)

    def match(*args):
        value = next(values)
        if value is None:
            raise StitchError("insufficient matches")
        return Rotation.from_euler("y", value, degrees=True).as_matrix(), dict(
            inliers=70, valid=80, p95_error_degrees=0.4
        )

    monkeypatch.setattr("a1_stitcher.automatic.match_lenses", match)


def test_consensus_rejects_moving_outlier_without_averaging(monkeypatch):
    mock_fits(monkeypatch, [178.5, 180, 180.04])
    matrix, score = fit_overlap([[0, 0]] * 3, [], minimum=2)
    assert (
        np.degrees(
            (
                Rotation.from_matrix(matrix).inv() * Rotation.from_euler("y", 180, degrees=True)
            ).magnitude()
        )
        < 0.05
    )
    assert score["consistent_samples"] == 2
    assert score["rejected_geometric_outliers"] == 1


@pytest.mark.parametrize("angles", [[170, 180, 190], [None, 180, None], [180, 181]])
def test_automatic_rejects_inconsistent_or_insufficient_evidence(monkeypatch, angles):
    mock_fits(monkeypatch, angles)
    with pytest.raises(StitchError, match="agree"):
        fit_overlap([[0, 0]] * len(angles), [], minimum=2)


@pytest.mark.integration
def test_original_only_default_pilot_optout_and_sidecar_integrity(
    synthetic_camera, tmp_path, monkeypatch
):
    # Test the automatic video path with a known lens fit. Real SIFT recovery is
    # separately tested using the textured two-lens synthetic photo fixture.
    monkeypatch.setattr(
        "a1_stitcher.automatic.match_lenses",
        lambda *args: (
            Rotation.from_euler("y", 180, degrees=True).as_matrix(),
            dict(inliers=70, valid=80, p95_error_degrees=0.4),
        ),
    )
    cfg = replace(
        options(synthetic_camera, tmp_path / "pilot.mp4"), calibration=None, backend="cpu"
    )
    job = plan(cfg)
    assert job["calibration"]["schema_version"] == 4
    validate_calibration(job["calibration"], job["metadata"])
    for field, value in [("time_shift_seconds", 0.1), ("lens_mount", np.eye(3).tolist())]:
        with pytest.raises(StitchError, match="timing override"):
            validate_calibration(dict(job["calibration"], **{field: value}))
    assert job["recipe"]["rolling_shutter"]["readout_seconds"] == 0
    assert job["recipe"]["viewport"]["mode"] == "pilot"
    original = digest(cfg.source)
    output = stitch(cfg)
    assert digest(cfg.source) == original
    assert output["verification"]["full_decode"]
    side = Path(output["viewport_files"][0])
    data = json.loads(side.read_text())
    assert data["video_sha256"] == digest(cfg.output)
    assert [s["source_frame"] for s in data["samples"]] == [2, 3, 4, 5]
    assert data["samples"][0]["time"] == 0
    # The known fixture pilot view is fixed despite camera motion.
    q = Rotation.from_quat([s["quaternion"] for s in data["samples"]])
    assert np.max((q[0].inv() * q).magnitude()) < 1e-6
    assert stitch(replace(cfg, resume=True))["status"] == "reused"
    fixed = stitch(replace(cfg, view="fixed", output=str(tmp_path / "fixed.mp4")))
    assert fixed["viewport_files"] == []
    assert digest(fixed["output"]) == digest(
        cfg.output
    )  # camera path does not rotate/re-encode pixels
    side.write_text("{}")
    with pytest.raises(StitchError, match="sidecar"):
        verify(cfg.output, receipt=output["receipt"])
    with pytest.raises(StitchError, match="sidecar"):
        stitch(replace(cfg, resume=True))
    final = plan(replace(cfg, first_frame=7, frames=1))
    assert len(final["calibration"]["source_frames"]) >= 2


def test_pilot_sidecar_partial_publication_preserves_existing_file(
    synthetic_camera, tmp_path, monkeypatch
):
    import a1_stitcher.render as render

    cfg = options(synthetic_camera, tmp_path / "partial.mp4", backend="cpu")
    publish = render.publish_file
    foreign = Path(str(cfg.output) + ".view.html")

    def collision(src, dst):
        if Path(dst) == foreign:
            foreign.write_text("another writer")
        return publish(src, dst)

    monkeypatch.setattr(render, "publish_file", collision)
    with pytest.raises(StitchError, match="already exists"):
        stitch(cfg)
    assert list(tmp_path.iterdir()) == [foreign]
    assert foreign.read_text() == "another writer"
