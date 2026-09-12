"""Frame-mapped reference comparisons, without changing either input video."""

from fractions import Fraction
from pathlib import Path

import cv2
import numpy as np
from scipy.spatial.transform import Rotation

from .errors import StitchError
from .process import probe
from .projection import decode_frame, sphere_rays
from .reference import fit_spheres
from .seam import periodic_sample
from .storage import identity, write_new_json


def align_sphere(sphere, rotation):
    """One global orientation change; no local warp or exposure fitting."""
    height, width = sphere.shape[:2]
    rays = sphere_rays(width) @ rotation
    u = (np.arctan2(rays[..., 0], rays[..., 2]) / (2 * np.pi) + 0.5) * width - 0.5
    v = (np.arcsin(np.clip(rays[..., 1], -1, 1)) / np.pi + 0.5) * height - 0.5
    return periodic_sample(sphere, u, v)


def compare(candidate, reference, samples, reference_first_frame, output_dir, width=2048):
    """samples index the candidate; reference_first_frame maps candidate zero."""
    if (
        not isinstance(reference_first_frame, int)
        or isinstance(reference_first_frame, bool)
        or reference_first_frame < 0
        or not isinstance(width, int)
        or isinstance(width, bool)
        or width < 512
        or width > 4096
        or width % 4
    ):
        raise StitchError("Invalid reference mapping or comparison width (512–4096)")
    if (
        not isinstance(samples, (list, tuple))
        or not 1 <= len(samples) <= 60
        or any(isinstance(x, bool) or not isinstance(x, int) or x < 0 for x in samples)
        or len(set(samples)) != len(samples)
    ):
        raise StitchError("Choose 1–60 unique nonnegative candidate sample frames")
    paths = [Path(p).resolve(strict=True) for p in (candidate, reference)]
    profiles = []
    for path in paths:
        streams = [s for s in probe(path)["streams"] if s["codec_type"] == "video"]
        if len(streams) != 1 or streams[0]["width"] != 2 * streams[0]["height"]:
            raise StitchError("Comparisons require one complete 2:1 sphere video per input")
        stream = streams[0]
        fps = Fraction(stream["r_frame_rate"])
        if fps <= 0 or Fraction(stream["avg_frame_rate"]) != fps:
            raise StitchError("Comparison requires constant, known frame rates")
        profiles.append(dict(fps=str(fps), frames=int(stream["nb_frames"])))
    if profiles[0]["fps"] != profiles[1]["fps"]:
        raise StitchError("Comparison frame rates differ; explicit matching source frames required")
    if max(samples) >= profiles[0]["frames"] or (
        reference_first_frame + max(samples) >= profiles[1]["frames"]
    ):
        raise StitchError("Comparison frame mapping exceeds an input video")
    output = Path(output_dir).absolute()
    identities = [identity(p) for p in paths]
    output.mkdir(parents=True, exist_ok=False)
    fps = float(Fraction(profiles[0]["fps"]))
    reports = []
    for index in sorted(samples):
        frames = [
            decode_frame(path, frame / fps, width=width, height=width // 2)
            for path, frame in zip(paths, [index, index + reference_first_frame])
        ]
        rotation, metrics = fit_spheres(*frames)
        if metrics["inliers"] < 100 or metrics["inliers"] / max(metrics["matches"], 1) < 0.2:
            raise StitchError("Insufficient common scene detail; check source-frame mapping")
        aligned = align_sphere(frames[0], rotation)
        for name, pixels in zip(["candidate", "reference", "aligned"], [*frames, aligned]):
            good, encoded = cv2.imencode(".png", pixels)
            if not good:
                raise StitchError("Could not encode comparison image")
            with (output / f"{index}-{name}.png").open("xb") as handle:
                handle.write(encoded.tobytes())
        first = reports[0]["alignment_rotation"] if reports else rotation
        change = Rotation.from_matrix(rotation) * Rotation.from_matrix(first).inv()
        reports.append(
            dict(
                candidate_frame=index,
                reference_frame=index + reference_first_frame,
                alignment_rotation=rotation.tolist(),
                alignment_change_degrees=float(np.degrees(change.magnitude())),
                **metrics,
            )
        )
    if [identity(p) for p in paths] != identities:
        raise StitchError("An input changed during comparison")
    result = dict(
        schema_version=1,
        status="complete",
        candidate=str(paths[0]),
        reference=str(paths[1]),
        input_identities=identities,
        profiles=profiles,
        reference_first_frame=reference_first_frame,
        analysis_width=width,
        frames=reports,
        scope="Geometric errors on matched inliers after per-frame global rotation; excludes unmatched pixels",
        limitations=[
            "Not a whole-image quality or stabilization score",
            "Per-frame alignment hides global attitude differences; inspect original images and alignment changes",
            "Reference quality, source-frame mapping and full-sphere content must be established separately",
            "No local warp, color fitting, upscaling detail synthesis or reference pixels used in candidate renders",
        ],
    )
    write_new_json(output / "comparison.json", result)
    options = "".join(f'<option value="{i}">Candidate frame {i}</option>' for i in sorted(samples))
    html = """<!doctype html><meta charset="utf-8"><title>A1 reference comparison</title>
<style>body{background:#15191f;color:#eee;font:16px system-ui;margin:24px}
img{width:100%;display:block}figure{margin:18px 0}select{font:inherit;padding:8px}
main{max-width:1600px;margin:auto}p{max-width:1000px;line-height:1.5}</style><main>
<h1>Studio / A1 Stitcher reference comparison</h1>
<p>Matching source moments. Alignment applies one global rotation per sampled frame,
so compare the original candidate too when assessing horizon or camera motion.
No local warp or color matching is applied here. These samples are not full-motion acceptance.</p>
<select id="frame">OPTIONS</select>
<figure><figcaption>Reference</figcaption><img id="reference"></figure>
<figure><figcaption>Candidate — orientation aligned</figcaption><img id="aligned"></figure>
<details><summary>Candidate with its original orientation</summary><img id="candidate"></details>
<p><a href="comparison.json">Frame mapping, measured errors and limitations</a></p></main>
<script>const frame=document.querySelector('#frame');
function show(){for(const n of ['reference','aligned','candidate'])
document.getElementById(n).src=frame.value+'-'+n+'.png'}
frame.addEventListener('change',show);show();</script>"""
    with (output / "review.html").open("x") as handle:
        handle.write(html.replace("OPTIONS", options))
    return dict(status="compared", output_dir=str(output), report=str(output / "comparison.json"))
