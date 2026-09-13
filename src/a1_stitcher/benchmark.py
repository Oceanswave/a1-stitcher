"""Contiguous Studio comparisons, with a fixed alignment and visible coverage."""

import subprocess
import tempfile
from fractions import Fraction
from pathlib import Path

import cv2
import numpy as np
from scipy.spatial.transform import Rotation

from .compare import align_sphere
from .errors import StitchError
from .process import binary, probe, stop, write_all
from .reference import fit_spheres
from .seam import periodic_sample
from .storage import identity, write_new_json
from .visual import rigid_rotation, tracks, video_frames


def face_rays(size):
    x, y = np.meshgrid(
        (np.arange(size) + 0.5) / size * 2 - 1, (np.arange(size) + 0.5) / size * 2 - 1
    )
    base = np.stack([x, y, np.ones_like(x)], -1)
    base /= np.linalg.norm(base, axis=2, keepdims=True)
    rotations = [Rotation.from_euler("y", angle, degrees=True) for angle in [0, 90, 180, -90]]
    rotations += [Rotation.from_euler("x", angle, degrees=True) for angle in [90, -90]]
    return [
        rotation.apply(base.reshape(-1, 3)).reshape(base.shape).astype(np.float32)
        for rotation in rotations
    ]


def faces(image, rays):
    height, width = image.shape[:2]
    return [
        periodic_sample(
            image,
            (np.arctan2(r[..., 0], r[..., 2]) / (2 * np.pi) + 0.5) * width - 0.5,
            (np.arcsin(r[..., 1]) / np.pi + 0.5) * height - 0.5,
        )
        for r in rays
    ]


def observe(previous, current, rays):
    a, b = [], []
    count = []
    for before, after, directions in zip(previous, current, rays):
        first, second = tracks(before, after, maximum=160)
        count.append(len(first))
        for points, dest in [(first, a), (second, b)]:
            if len(points):
                r = cv2.remap(
                    directions,
                    points[:, 0].astype(np.float32)[None],
                    points[:, 1].astype(np.float32)[None],
                    cv2.INTER_LINEAR,
                )[0]
                dest.extend(r / np.linalg.norm(r, axis=1, keepdims=True))
    try:
        rotation, inliers, errors = rigid_rotation(a, b)
        return dict(
            status="measured",
            tracks_per_face=count,
            inliers=int(inliers.sum()),
            rotation_vector_degrees=np.degrees(Rotation.from_matrix(rotation).as_rotvec()).tolist(),
            local_residual_p95_degrees=float(np.percentile(errors[inliers], 95)),
            unmatched_fraction=float(1 - inliers.mean()),
        )
    except StitchError as exc:
        return dict(status="unmeasured", tracks_per_face=count, reason=str(exc))


def benchmark(candidate, reference, reference_first_frame, frames, output_dir, width=1024):
    if any(type(v) is not int for v in [reference_first_frame, frames, width]) or (
        reference_first_frame < 0
        or not 2 <= frames <= 1800
        or not 512 <= width <= 2048
        or width % 4
    ):
        raise StitchError(
            "Benchmark requires 2–1800 frames, nonnegative mapping and width 512–2048"
        )
    paths = [Path(p).resolve(strict=True) for p in [candidate, reference]]
    profiles = []
    for path in paths:
        streams = [s for s in probe(path)["streams"] if s["codec_type"] == "video"]
        if len(streams) != 1 or streams[0]["width"] != 2 * streams[0]["height"]:
            raise StitchError("Benchmark requires two complete 2:1 spheres")
        s = streams[0]
        fps = Fraction(s["r_frame_rate"])
        if not 0 < fps <= 120 or Fraction(s["avg_frame_rate"]) != fps:
            raise StitchError("Benchmark requires known constant frame rates")
        profiles.append(dict(fps=str(fps), frames=int(s["nb_frames"])))
    if profiles[0]["fps"] != profiles[1]["fps"]:
        raise StitchError("Benchmark frame rates differ")
    if frames > profiles[0]["frames"] or reference_first_frame + frames > profiles[1]["frames"]:
        raise StitchError("Benchmark mapping exceeds an input")
    ids = [identity(p) for p in paths]
    output = Path(output_dir).absolute()
    output.mkdir(parents=True, exist_ok=False)
    fps = float(Fraction(profiles[0]["fps"]))
    size = 256
    rays = face_rays(size)
    observations, previous, alignment = [], None, None
    video = output / "six-view-comparison.mp4"
    command = [
        binary("ffmpeg"),
        "-v",
        "error",
        "-nostdin",
        "-n",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "bgr24",
        "-s",
        f"{size * 6}:{size * 2}",
        "-r",
        profiles[0]["fps"],
        "-i",
        "-",
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "20",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(video),
    ]
    with (
        video_frames(paths[0], fps, 0, frames, width, height=width // 2) as a,
        video_frames(paths[1], fps, reference_first_frame, frames, width, height=width // 2) as b,
        tempfile.TemporaryFile() as errors,
    ):
        encoder = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=errors)
        try:
            for (index, first), (_, second) in zip(a, b, strict=True):
                if alignment is None:
                    alignment, matches = fit_spheres(first, second)
                    if matches["inliers"] < 100 or matches["inliers"] < 0.2 * matches["matches"]:
                        raise StitchError(
                            "Initial alignment lacks common detail; check source mapping"
                        )
                views = [faces(align_sphere(first, alignment), rays), faces(second, rays)]
                row = dict(candidate_frame=index, reference_frame=reference_first_frame + index)
                for j, name in enumerate(["candidate", "reference"]):
                    row[name] = dict(
                        luminance=[
                            float(cv2.cvtColor(v, cv2.COLOR_BGR2GRAY).mean()) / 255
                            for v in views[j]
                        ],
                        detail=[
                            float(
                                cv2.Laplacian(cv2.cvtColor(v, cv2.COLOR_BGR2GRAY), cv2.CV_32F).var()
                            )
                            for v in views[j]
                        ],
                        motion=observe(previous[j], views[j], rays) if previous else None,
                    )
                observations.append(row)
                panels = []
                for j, label in enumerate(["A1 STITCHER", "STUDIO"]):
                    panel = np.vstack([np.hstack(views[j][:3]), np.hstack(views[j][3:])])
                    cv2.putText(
                        panel,
                        f"{label} | frame {index}",
                        (12, 26),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.6,
                        (0, 0, 0),
                        4,
                        cv2.LINE_AA,
                    )
                    cv2.putText(
                        panel,
                        f"{label} | frame {index}",
                        (12, 26),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.6,
                        (255, 255, 255),
                        1,
                        cv2.LINE_AA,
                    )
                    panels.append(panel)
                write_all(encoder.stdin, np.hstack(panels).tobytes())
                previous = views
            encoder.stdin.close()
            if encoder.wait(timeout=120):
                errors.seek(0)
                raise StitchError(errors.read()[-4000:].decode(errors="replace"))
        finally:
            stop(encoder)
    if [identity(p) for p in paths] != ids:
        raise StitchError("An input changed during benchmark")
    summary = {}
    for name in ["candidate", "reference"]:
        measured = [
            r[name]["motion"] for r in observations[1:] if r[name]["motion"]["status"] == "measured"
        ]
        # Only consecutive valid pairs contribute acceleration; never bridge missing observations.
        acceleration = []
        for a, b in zip(observations[1:-1], observations[2:]):
            x, y = a[name]["motion"], b[name]["motion"]
            if x["status"] == y["status"] == "measured":
                acceleration.append(
                    np.linalg.norm(
                        np.array(y["rotation_vector_degrees"]) - x["rotation_vector_degrees"]
                    )
                )
        luminance = np.array([r[name]["luminance"] for r in observations])
        summary[name] = dict(
            measured_pairs=len(measured),
            total_pairs=frames - 1,
            angular_acceleration_p95_degrees_per_frame_squared=float(
                np.percentile(acceleration, 95)
            )
            if acceleration
            else None,
            local_residual_p95_degrees=float(
                np.percentile([m["local_residual_p95_degrees"] for m in measured], 95)
            )
            if measured
            else None,
            brightness_second_difference_p95=float(
                np.percentile(np.abs(np.diff(luminance, n=2, axis=0)), 95)
            )
            if frames > 2
            else None,
        )
    result = dict(
        schema_version=1,
        status="complete",
        inputs=list(map(str, paths)),
        input_identities=ids,
        profiles=profiles,
        frames=observations,
        summary=summary,
        analysis_width=width,
        face_size=size,
        alignment_rotation=alignment.tolist(),
        coverage=dict(
            decoded_frames_each=frames,
            motion_pairs_attempted_each=frames - 1,
            human_playback_review="not_recorded",
        ),
        limitations=[
            "One global alignment on frame zero; no per-frame motion hiding",
            "Reduced-resolution six-face diagnostics are not native-resolution seam or horizon acceptance",
            "Scene movement, parallax and real exposure changes affect these measures",
            "No absolute horizon reference; inspect horizon and subject geometry in playback",
            "No single quality score or automatic acceptance",
        ],
    )
    write_new_json(output / "benchmark.json", result)
    (output / "review.html").write_text(
        '<!doctype html><meta charset="utf-8"><title>A1 moving comparison</title>'
        "<style>body{background:#15191f;color:#eee;font:17px system-ui;margin:24px}video{width:100%}</style>"
        "<h1>A1 Stitcher / Studio — continuous comparison</h1><p>Left: independent CLI. Right: Studio. "
        "Six fixed 90° views each, one alignment at the beginning. Review seams, motion, horizon and geometry separately.</p>"
        '<video controls loop src="six-view-comparison.mp4"></video>'
        "<p>Automated coverage does not establish human playback acceptance. "
        '<a href="benchmark.json">Per-frame diagnostics and limitations</a></p>'
    )
    return dict(status="benchmarked", output_dir=str(output), summary=summary)
