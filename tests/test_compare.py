import json
import subprocess

import cv2
import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from a1_stitcher.compare import align_sphere, compare
from a1_stitcher.errors import StitchError
from a1_stitcher.process import binary
from a1_stitcher.reference import fit_spheres


def scene():
    rng = np.random.default_rng(521)
    pixels = rng.integers(0, 255, (512, 1024, 3), dtype=np.uint8)
    pixels = cv2.GaussianBlur(pixels, (0, 0), 2)
    return np.clip((pixels.astype(float) - 127) * 4 + 127, 0, 255).astype(np.uint8)


def test_reference_alignment_recovers_known_spherical_rotation():
    first = scene()
    expected = Rotation.from_euler("xyz", [2, -30, 3], degrees=True).as_matrix()
    target = align_sphere(first, expected)
    measured, report = fit_spheres(first, target)
    assert report["inliers"] > 100
    assert np.degrees((Rotation.from_matrix(measured.T @ expected)).magnitude()) < 0.1
    actual = align_sphere(first, measured)
    assert np.abs(actual.astype(float) - target).mean() < 1


@pytest.fixture
def reference_pair(tmp_path, synthetic_camera):
    # Unique texture per moment makes a wrong frame offset detectable.
    frames = [np.roll(scene(), 17 * index, axis=0) for index in range(4)]
    paths = [tmp_path / "candidate.mp4", tmp_path / "reference.mp4"]
    for path, images in zip(paths, [frames[1:], frames]):
        subprocess.run(
            [
                binary("ffmpeg"),
                "-v",
                "error",
                "-n",
                "-f",
                "rawvideo",
                "-pix_fmt",
                "bgr24",
                "-s",
                "1024x512",
                "-r",
                "10",
                "-i",
                "-",
                "-c:v",
                "libx264",
                "-threads",
                "1",
                "-crf",
                "0",
                "-pix_fmt",
                "yuv444p",
                str(path),
            ],
            input=b"".join(frame.tobytes() for frame in images),
            capture_output=True,
            check=True,
            timeout=30,
        )
    return paths


@pytest.mark.integration
def test_complete_reference_comparison_mapping_and_no_clobber(reference_pair, tmp_path):
    candidate, reference = reference_pair
    output = tmp_path / "review"
    result = compare(candidate, reference, [0, 2], 1, output, 1024)
    assert result["status"] == "compared"
    report = json.loads((output / "comparison.json").read_text())
    assert [(f["candidate_frame"], f["reference_frame"]) for f in report["frames"]] == [
        (0, 1),
        (2, 3),
    ]
    assert all(f["median_degrees"] < 0.01 for f in report["frames"])
    assert len(list(output.glob("*.png"))) == 6
    assert (output / "review.html").is_file()
    with pytest.raises(FileExistsError):
        compare(candidate, reference, [0], 1, output, 1024)


@pytest.mark.parametrize(
    "samples,offset,width", [([0, 0], 0, 1024), ([True], 0, 1024), ([0], -1, 1024), ([0], 0, 8192)]
)
def test_invalid_compare_settings_fail_before_writes(tmp_path, samples, offset, width):
    output = tmp_path / "review"
    with pytest.raises(StitchError):
        compare("missing.mp4", "missing.mp4", samples, offset, output, width)
    assert not output.exists()


@pytest.mark.integration
def test_out_of_range_mapping_does_not_create_report(reference_pair, tmp_path):
    output = tmp_path / "review"
    with pytest.raises(StitchError, match="mapping"):
        compare(*reference_pair, [2], 2, output, 1024)
    assert not output.exists()
