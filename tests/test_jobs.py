import json
import subprocess
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from a1_stitcher.cli import main
from a1_stitcher.errors import StitchError
from a1_stitcher.media import verify
from a1_stitcher.process import binary, run
from a1_stitcher.render import Options, plan, stitch
from a1_stitcher.storage import digest


def options(camera, output, **kwargs):
    return Options(
        str(camera["source"]),
        str(camera["calibration"]),
        str(output),
        first_frame=2,
        frames=4,
        width=256,
        lens_width=128,
        threads=1,
        **kwargs,
    )


@pytest.mark.integration
def test_complete_conversion_resume_metadata_and_stabilization(synthetic_camera, tmp_path):
    output = tmp_path / "complete.mp4"
    config = options(synthetic_camera, output)
    before = digest(synthetic_camera["source"])
    result = stitch(config)
    assert result["status"] == "created"
    assert result["verification"]["frames"] == 4
    assert result["verification"]["full_decode"]
    assert result["verification"]["projection"] == "equirectangular"
    assert digest(synthetic_camera["source"]) == before
    assert not list(tmp_path.glob(".a1-stitch-*"))
    assert not Path(str(output) + ".lock").exists()
    receipt = Path(result["receipt"])
    assert verify(output, receipt=receipt)["output_sha256"] == digest(output)
    assert stitch(replace(config, resume=True))["status"] == "reused"
    with pytest.raises(StitchError, match="already exists"):
        stitch(config)
    with pytest.raises(StitchError, match="changed"):
        stitch(replace(config, resume=True, frames=3))
    baseline = tmp_path / "baseline.mp4"
    stitch(replace(config, output=str(baseline), no_stabilization=True))

    def decoded(path):
        data = run(
            [
                binary("ffmpeg"),
                "-v",
                "error",
                "-i",
                str(path),
                "-pix_fmt",
                "rgb24",
                "-f",
                "rawvideo",
                "-",
            ]
        )
        return np.frombuffer(data, np.uint8).reshape(4, 128, 256, 3).astype(float)

    stable = decoded(output)
    raw = decoded(baseline)
    stable_change = np.abs(stable[1:] - stable[0]).mean()
    raw_change = np.abs(raw[1:] - raw[0]).mean()
    assert stable_change < raw_change * 0.4, (stable_change, raw_change)
    # Fast-start layout is material for local/browser seeking.
    data = output.read_bytes()
    assert data.index(b"moov") < data.index(b"mdat")


def test_dry_run_has_no_filesystem_side_effects(synthetic_camera, tmp_path):
    target = tmp_path / "uncreated" / "clip.mp4"
    result = stitch(options(synthetic_camera, target), dry_run=True)
    assert result["status"] == "planned"
    assert not target.parent.exists()


@pytest.mark.integration
def test_adaptive_seam_complete_job_and_cache_identity(synthetic_camera, tmp_path):
    target = tmp_path / "adaptive.mp4"
    settings = options(synthetic_camera, target, seam="adaptive")
    result = stitch(settings)
    receipt = json.loads(Path(result["receipt"]).read_text())
    assert result["verification"]["full_decode"]
    assert receipt["seam_diagnostics"]["adaptive_path"] is not None
    assert plan(settings)["recipe_sha256"] != plan(replace(settings, seam="flow"))["recipe_sha256"]
    assert stitch(replace(settings, resume=True))["status"] == "reused"


@pytest.mark.integration
def test_single_reader_pairs_the_requested_original_lens_frames(
    synthetic_camera, tmp_path, monkeypatch
):
    import a1_stitcher.render as module
    from a1_stitcher.projection import decode_frame

    original_read = module.read_exact
    captured = []

    def capture(stream, size, timeout):
        data = original_read(stream, size, timeout)
        captured.append(np.frombuffer(data, np.uint8).reshape(128, 256, 3))
        return data

    monkeypatch.setattr(module, "read_exact", capture)
    stitch(options(synthetic_camera, tmp_path / "paired.mp4", encoding="h264"))
    for ordinal in [0, 3]:
        for lens in range(2):
            expected = decode_frame(
                synthetic_camera["source"],
                (2 + ordinal) / synthetic_camera["fps"],
                stream=lens,
                width=128,
            )
            actual = captured[ordinal][:, lens * 128 : (lens + 1) * 128]
            assert np.array_equal(actual, expected)


@pytest.mark.parametrize(
    "changes",
    [
        {"first_frame": -1},
        {"frames": 0},
        {"frames": 100},
        {"width": 255},
        {"width": 9000},
        {"lens_width": 127},
        {"threads": 0},
        {"timeout": float("nan")},
        {"frames": True},
        {"no_stabilization": "yes"},
        {"seam": "guess"},
        {"rolling_shutter": "guess"},
    ],
)
def test_invalid_job_fails_before_writes(synthetic_camera, tmp_path, changes):
    target = tmp_path / "none" / "clip.mp4"
    with pytest.raises(StitchError):
        plan(replace(options(synthetic_camera, target), **changes))
    assert not target.parent.exists()


def test_source_or_profile_overwrite_rejected(synthetic_camera):
    for path in [synthetic_camera["source"], synthetic_camera["calibration"]]:
        with pytest.raises(StitchError, match="overwrite"):
            plan(options(synthetic_camera, path))


def test_failed_decode_reaps_processes_and_leaves_no_delivery(
    synthetic_camera, tmp_path, monkeypatch
):
    import a1_stitcher.render as module

    processes = []
    real = subprocess.Popen

    def track(*args, **kwargs):
        process = real(*args, **kwargs)
        processes.append(process)
        return process

    def fail(*args, **kwargs):
        raise StitchError("Injected decoder interruption")

    monkeypatch.setattr(module.subprocess, "Popen", track)
    monkeypatch.setattr(module, "read_exact", fail)
    output = tmp_path / "never.mp4"
    with pytest.raises(StitchError, match="Injected"):
        stitch(options(synthetic_camera, output))
    assert processes and all(process.poll() is not None for process in processes)
    assert not output.exists() and not list(tmp_path.iterdir())


def test_receipt_failure_rolls_back_only_new_output(synthetic_camera, tmp_path, monkeypatch):
    import a1_stitcher.render as module

    def fail(*args, **kwargs):
        raise OSError("Injected disk-full error")

    monkeypatch.setattr(module, "write_new_json", fail)
    output = tmp_path / "never.mp4"
    with pytest.raises(OSError, match="disk-full"):
        stitch(options(synthetic_camera, output))
    assert not list(tmp_path.iterdir())


def test_corrupt_completed_output_is_not_resumed(synthetic_camera, tmp_path):
    output = tmp_path / "output.mp4"
    config = options(synthetic_camera, output)
    result = stitch(config)
    receipt = Path(result["receipt"])
    data = json.loads(receipt.read_text())
    data["output_sha256"] = "0" * 64
    receipt.write_text(json.dumps(data))
    with pytest.raises(StitchError, match="checksum"):
        stitch(replace(config, resume=True))


def test_batch_dry_run_paths_resolve_against_manifest(synthetic_camera, tmp_path, capsys):
    manifest = tmp_path / "jobs.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "jobs": [
                    dict(
                        source=str(synthetic_camera["source"]),
                        calibration=str(synthetic_camera["calibration"]),
                        output="new/clip.mp4",
                        first_frame=1,
                        frames=2,
                        width=256,
                        lens_width=128,
                    )
                ],
            }
        )
    )
    assert main(["batch", str(manifest), "--dry-run"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["jobs"][0]["output"] == str(tmp_path / "new/clip.mp4")
    assert not (tmp_path / "new").exists()


def test_cli_inspect_error_is_json_and_no_overwrite(synthetic_camera, capsys):
    before = digest(synthetic_camera["source"])
    assert (
        main(
            [
                "inspect",
                str(synthetic_camera["source"]),
                "--output",
                str(synthetic_camera["source"]),
            ]
        )
        == 1
    )
    assert json.loads(capsys.readouterr().err)["status"] == "error"
    assert digest(synthetic_camera["source"]) == before


@pytest.mark.integration
def test_separate_exports_keep_same_heading_for_shared_source_frame(
    synthetic_camera, tmp_path, monkeypatch
):
    import a1_stitcher.render as module

    captured = []
    original = module.TiledStitcher.stitch

    def capture(self, frames, matrix, *args):
        captured.append(matrix.copy())
        return original(self, frames, matrix, *args)

    monkeypatch.setattr(module.TiledStitcher, "stitch", capture)
    config = options(synthetic_camera, tmp_path / "first.mp4", backend="cpu", seam="feather")
    stitch(config)
    stitch(replace(config, output=str(tmp_path / "second.mp4"), first_frame=4, frames=1))
    np.testing.assert_allclose(captured[2], captured[4], atol=1e-12)
