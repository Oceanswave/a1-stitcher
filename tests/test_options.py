import json
from pathlib import Path

import pytest

from a1_stitcher.cli import main, parser
from a1_stitcher.errors import StitchError
from a1_stitcher.render import Options, plan


def test_finishing_defaults_keep_native_input_precision(synthetic_camera, tmp_path):
    config = Options(
        str(synthetic_camera["source"]),
        str(synthetic_camera["calibration"]),
        str(tmp_path / "master.mp4"),
        2,
        3,
        backend="cpu",
    )
    recipe = plan(config)["recipe"]
    assert recipe["settings"]["width"] == 8192
    assert recipe["settings"]["lens_width"] == 128
    assert recipe["encoding"]["pixel_format"] == "yuv420p10le"
    assert recipe["encoding"]["raw"] == "bgr48le"
    assert recipe["settings"]["seam"] == "flow"
    assert recipe["gyro_profile"] is None
    args = parser().parse_args(
        [
            "stitch",
            "in.insv",
            "--calibration",
            "c.json",
            "--first-frame",
            "2",
            "--frames",
            "3",
            "--output",
            "m.mp4",
        ]
    )
    assert (args.width, args.lens_width, args.encoding, args.backend) == (8192, 0, "hevc10", "auto")


def test_cannot_upscale_lens_or_use_fake_backend(synthetic_camera, tmp_path):
    values = dict(
        source=str(synthetic_camera["source"]),
        calibration=str(synthetic_camera["calibration"]),
        output=str(tmp_path / "m.mp4"),
        first_frame=2,
        frames=3,
        backend="cpu",
    )
    with pytest.raises(StitchError, match="native"):
        plan(Options(**values, lens_width=256))
    with pytest.raises(StitchError, match="Backend"):
        plan(Options(**(values | dict(backend="fake"))))


def test_batch_resolves_gyro_profile_and_preserves_job_resume(tmp_path, monkeypatch, capsys):
    import a1_stitcher.render as module

    seen = []
    monkeypatch.setattr(module, "plan", lambda o: None)
    monkeypatch.setattr(module, "stitch", lambda o, **kw: seen.append(o) or {"status": "planned"})
    manifest = tmp_path / "jobs.json"
    manifest.write_text(
        json.dumps(
            dict(
                schema_version=1,
                jobs=[
                    dict(
                        source="a.insv",
                        calibration="c.json",
                        gyro_profile="gyro.json",
                        output="out.mp4",
                        first_frame=0,
                        frames=3,
                        resume=True,
                    )
                ],
            )
        )
    )
    assert main(["batch", str(manifest), "--dry-run"]) == 0
    assert Path(seen[0].gyro_profile) == tmp_path / "gyro.json"
    assert seen[0].resume is True
    data = json.loads(manifest.read_text())
    data["jobs"][0]["gyro_profile"] = "out.mp4"
    manifest.write_text(json.dumps(data))
    assert main(["batch", str(manifest), "--dry-run"]) == 1
    assert "collide" in capsys.readouterr().err


def test_backend_auto_fallback_is_explicit_and_metal_request_fails(monkeypatch):
    from a1_stitcher import metal

    monkeypatch.setattr(metal.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(metal.shutil, "which", lambda name: "/swiftc")

    def unavailable(*args, **kwargs):
        raise StitchError("GPU unavailable")

    monkeypatch.setattr(metal, "MetalStitcher", unavailable)
    result = metal.select_backend("auto")
    assert result["name"] == "cpu" and "GPU unavailable" in result["reason"]
    with pytest.raises(StitchError, match="GPU unavailable"):
        metal.select_backend("metal")
    with pytest.raises(StitchError, match="Backend"):
        metal.select_backend("unknown")
    assert metal.select_backend("cpu")["name"] == "cpu"


@pytest.mark.parametrize(
    "changes",
    [
        {"heading_reference_frame": -2},
        {"heading_reference_frame": True},
        {"heading_reference_frame": 1.5},
        {"heading_reference_frame": 10000},
        {"rolling_shutter_model": "guess"},
    ],
)
def test_motion_options_reject_invalid_values_before_writing(synthetic_camera, tmp_path, changes):
    values = dict(
        source=str(synthetic_camera["source"]),
        calibration=str(synthetic_camera["calibration"]),
        output=str(tmp_path / "new" / "m.mp4"),
        first_frame=2,
        frames=3,
        backend="cpu",
    )
    with pytest.raises(StitchError):
        plan(Options(**(values | changes)))
    assert not (tmp_path / "new").exists()


def test_motion_recipe_captures_fixed_heading_and_algorithm(synthetic_camera, tmp_path):
    from dataclasses import replace

    a = Options(
        str(synthetic_camera["source"]),
        str(synthetic_camera["calibration"]),
        str(tmp_path / "m.mp4"),
        2,
        3,
        backend="cpu",
    )
    b = replace(a, first_frame=4)
    assert plan(a)["recipe"]["heading_reference"] == plan(b)["recipe"]["heading_reference"]
    assert (
        plan(replace(b, heading_reference_frame=-1))["recipe"]["heading_reference"]["source_frame"]
        == 4
    )
    assert (
        plan(a)["recipe_sha256"]
        != plan(replace(a, rolling_shutter_model="trajectory"))["recipe_sha256"]
    )
