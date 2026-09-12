"""One-time calibration against a user-supplied stitched reference interval."""

from fractions import Fraction
from pathlib import Path

import cv2
import numpy as np
from scipy.spatial.transform import Rotation

from .calibration import fit_gravity, lens_fingerprint, score_gravity, validate_calibration
from .errors import StitchError
from .insv import InsvReader
from .media import source_profile
from .process import probe
from .projection import (
    blend_sphere,
    decode_frame,
    lenses_from_metadata,
    match_lenses,
    robust_rotation,
)
from .storage import identity, write_new_json


def cube_features(sphere, size=640):
    sift = cv2.SIFT_create(nfeatures=2500, contrastThreshold=0.025)
    rays_all = []
    descriptors = []
    grid = (np.arange(size) + 0.5 - size / 2) / (size / 2)
    x, y = np.meshgrid(grid, grid)
    local = np.stack([x, y, np.ones_like(x)], axis=-1)
    rotations = [
        Rotation.from_euler("y", angle, degrees=True).as_matrix() for angle in [0, 90, 180, 270]
    ]
    rotations += [Rotation.from_euler("x", angle, degrees=True).as_matrix() for angle in [90, -90]]
    for rotation in rotations:
        rays = local @ rotation.T
        rays /= np.linalg.norm(rays, axis=2)[:, :, None]
        u = (np.arctan2(rays[:, :, 0], rays[:, :, 2]) / (2 * np.pi) + 0.5) * sphere.shape[1] - 0.5
        v = (np.arcsin(rays[:, :, 1]) / np.pi + 0.5) * sphere.shape[0] - 0.5
        flat = cv2.remap(
            sphere,
            u.astype(np.float32),
            v.astype(np.float32),
            cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_WRAP,
        )
        points, desc = sift.detectAndCompute(flat, None)
        if desc is None:
            continue
        xy = np.array([point.pt for point in points])
        rays = (
            np.column_stack(
                [
                    (xy[:, 0] + 0.5 - size / 2) / (size / 2),
                    (xy[:, 1] + 0.5 - size / 2) / (size / 2),
                    np.ones(len(xy)),
                ]
            )
            @ rotation.T
        )
        rays /= np.linalg.norm(rays, axis=1)[:, None]
        rays_all.append(rays)
        descriptors.append(desc)
    if not rays_all:
        raise StitchError("Insufficient reference texture")
    return np.concatenate(rays_all), np.concatenate(descriptors)


def fit_spheres(source, target):
    sr, sd = cube_features(source)
    tr, td = cube_features(target)
    pairs = cv2.BFMatcher().knnMatch(sd, td, k=2)
    matches = [
        pair[0] for pair in pairs if len(pair) == 2 and pair[0].distance < 0.72 * pair[1].distance
    ]
    source_rays = np.array([sr[m.queryIdx] for m in matches])
    target_rays = np.array([tr[m.trainIdx] for m in matches])
    rot, inliers, errors = robust_rotation(source_rays, target_rays, degrees=0.8, iterations=1000)
    return rot, dict(
        matches=len(matches),
        inliers=int(inliers.sum()),
        median_degrees=float(np.median(errors[inliers])),
        p95_degrees=float(np.percentile(errors[inliers], 95)),
    )


def calibrate(
    source, reference, first_source_frame, samples, holdouts, output, evidence=None, progress=None
):
    source, reference = Path(source).resolve(strict=True), Path(reference).resolve(strict=True)
    output = Path(output).absolute()
    if output.exists() or output.is_symlink() or output.resolve() in [source, reference]:
        raise StitchError("Calibration output must be a new file")
    if len(samples) < 6 or len(holdouts) < 2 or set(samples) & set(holdouts):
        raise StitchError("Use at least six training frames and two separate holdout frames")
    if any(
        isinstance(x, bool) or not isinstance(x, int) or x < 0
        for x in [first_source_frame, *samples, *holdouts]
    ):
        raise StitchError("Frame indices must be nonnegative integers")
    if len(set(samples)) != len(samples) or len(set(holdouts)) != len(holdouts):
        raise StitchError("Duplicate calibration/holdout frame indices")
    reader = InsvReader(source)
    metadata = reader.metadata()
    profile = source_profile(source, metadata)
    reference_info = probe(reference)
    refs = [s for s in reference_info["streams"] if s["codec_type"] == "video"]
    if len(refs) != 1 or refs[0]["width"] != refs[0]["height"] * 2:
        raise StitchError("Reference must contain one complete 2:1 equirectangular video")
    fps = Fraction(profile["fps"])
    if Fraction(refs[0]["r_frame_rate"]) != fps:
        raise StitchError("Original and reference frame rates differ")
    indices = sorted(samples + holdouts)
    if (
        indices[-1] >= int(refs[0]["nb_frames"])
        or first_source_frame + indices[-1] >= profile["frames"]
    ):
        raise StitchError("Calibration frame indices exceed the original or reference")
    identities = (identity(source), identity(reference))
    if evidence is not None:
        evidence = Path(evidence)
        evidence.mkdir(parents=True, exist_ok=False)
    lenses = lenses_from_metadata(metadata, 1440)
    provisional = Rotation.from_euler("x", 90, degrees=True).as_matrix()
    observations = []
    relative = None
    for index in indices:
        original_time = (first_source_frame + index) / float(fps)
        frames = [decode_frame(source, original_time, stream=i, width=1440) for i in range(2)]
        if relative is None:
            relative, lens_report = match_lenses(*frames, lenses)
            if (
                lens_report["inliers"] < 30
                or lens_report["inliers"] / max(lens_report["matches"], 1) < 0.25
            ):
                raise StitchError(
                    "Lens alignment has too few consistent matches; choose a clearer interval"
                )
        target = decode_frame(reference, index / float(fps), width=2048, height=1024)
        sphere, missing = blend_sphere(frames, lenses, relative, provisional, width=2048)
        if missing > 0.001:
            raise StitchError("Lens alignment does not cover the sphere")
        rotation, match = fit_spheres(sphere, target)
        if match["inliers"] < 100:
            raise StitchError(
                "Insufficient original/reference matches; check frame mapping and reference projection"
            )
        row = dict(
            raw_seconds=original_time,
            reference_frame=index,
            lens_to_reference=(rotation @ provisional.T).tolist(),
            alignment=match,
        )
        observations.append(row)
        if evidence is not None:
            cv2.imwrite(str(evidence / f"{index:08d}-original-sphere.jpg"), sphere)
            cv2.imwrite(str(evidence / f"{index:08d}-reference.jpg"), target)
        if progress:
            progress(dict(event="calibration_frame", frame=index, **match))
    training = [r for r in observations if r["reference_frame"] in samples]
    held = [r for r in observations if r["reference_frame"] in holdouts]
    mount, shift = fit_gravity(reader, training)
    train_score = score_gravity(reader, training, mount, shift)
    held_score = score_gravity(reader, held, mount, shift)
    warnings = ["Sampled geometry checks do not establish complete motion or seam quality"]
    if held_score["maximum_degrees"] > 1:
        warnings.append(
            "Holdout vertical error exceeds 1 degree; inspect rapid motion, time alignment and rolling shutter"
        )
    result = dict(
        schema_version=1,
        camera_type="Antigravity A1",
        lens_fingerprint=lens_fingerprint(metadata),
        lens_mount=mount.as_matrix().tolist(),
        rotation_lens1_to_lens0=relative.tolist(),
        inverse=False,
        time_shift_seconds=shift,
        quality_status="experimental",
        warnings=warnings,
        training=train_score,
        holdout=held_score,
        lens_alignment=lens_report,
        reference_mapping=dict(
            first_source_frame=first_source_frame,
            fps=str(fps),
            training_frames=samples,
            holdout_frames=holdouts,
        ),
    )
    validate_calibration(result, metadata)
    if identities != (identity(source), identity(reference)):
        raise StitchError("Calibration inputs changed during processing")
    write_new_json(output, result)
    if evidence is not None:
        write_new_json(
            evidence / "observations.json",
            dict(source=str(source), reference=str(reference), observations=observations),
        )
    return result
