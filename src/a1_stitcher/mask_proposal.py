"""Conservative camera-fixed obstruction proposals; activation requires review."""

from fractions import Fraction
from pathlib import Path

import cv2
import numpy as np

from .calibration import load_calibration
from .errors import StitchError
from .occlusion import template, validate
from .storage import fingerprint, identity, load_json, write_new_json


def detect_obstructions(images, alternate, eligible):
    """Persistent dark disagreement plus fixed texture; abstain in static scenes."""
    gray = np.array([cv2.cvtColor(i, cv2.COLOR_BGR2GRAY) for i in images], np.float32) / 255
    other = np.array([cv2.cvtColor(i, cv2.COLOR_BGR2GRAY) for i in alternate], np.float32) / 255
    median = np.median(gray, axis=0)
    # Black outside-image pixels are camera-fixed too; they are not housing.
    # Erode the observed image support before finding edges or expanding seeds.
    illuminated = (np.quantile(gray, 0.1, axis=0) > 0.025).astype(np.uint8)
    illuminated = cv2.erode(illuminated, np.ones((5, 5), np.uint8)) > 0
    eligible = eligible & illuminated
    variation = np.median(np.abs(gray - median), axis=0)
    scene_motion = float(np.median(variation[eligible])) if eligible.any() else 0
    if scene_motion < 0.015:
        return [], dict(
            status="abstained", reason="insufficient scene movement", scene_variation=scene_motion
        )
    gradient = np.hypot(
        cv2.Sobel(median, cv2.CV_32F, 1, 0) / 8, cv2.Sobel(median, cv2.CV_32F, 0, 1) / 8
    )
    disagreement = np.median(other - gray, axis=0)
    persistence = np.mean(other - gray > 0.06, axis=0)
    fixed = (variation < min(0.035, scene_motion * 0.5)) & (gradient > 0.012)
    seeds = eligible & fixed & (disagreement > 0.08) & (persistence > 0.8)
    mask = cv2.morphologyEx(seeds.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    mask = cv2.dilate(mask, np.ones((5, 5), np.uint8)) * eligible
    contours, _ = cv2.findContours(
        mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    polygons = []
    for contour in contours:
        if not 25 <= cv2.contourArea(contour) <= mask.size * 0.025:
            continue
        vertices = cv2.approxPolyDP(contour, 1.5, True)[:, 0]
        if 3 <= len(vertices) <= 128:
            polygons.append((vertices / (np.array(mask.shape[::-1]) - 1)).tolist())
    if len(polygons) > 32:
        return [], dict(
            status="abstained", reason="fragmented evidence", scene_variation=scene_motion
        )
    return polygons, dict(
        status="proposed" if polygons else "abstained",
        scene_variation=scene_motion,
        seed_pixels=int(seeds.sum()),
        polygons=len(polygons),
        reason="persistent camera-fixed dark mismatch; object identity needs review",
    )


def propose(source, calibration_path, first_frame, frames, samples, output, evidence_dir):
    from .insv import InsvReader
    from .media import source_profile
    from .projection import lenses_from_metadata, project, unproject
    from .visual import video_frames

    if (
        any(type(v) is not int for v in [first_frame, frames, samples])
        or first_frame < 0
        or not 60 <= frames <= 1800
        or not 12 <= samples <= 60
        or samples > frames
    ):
        raise StitchError("Mask proposals require 60–1800 source frames and 12–60 samples")
    source = Path(source).resolve(strict=True)
    paths = [source, Path(calibration_path).resolve(strict=True)]
    target = Path(output).absolute()
    if target.exists() or target.is_symlink() or target.resolve() in paths:
        raise StitchError("Mask proposal output exists or collides with an input")
    ids = [identity(p) for p in paths]
    metadata = InsvReader(source).metadata()
    cal = load_calibration(calibration_path, metadata)
    video = source_profile(source, metadata)
    if first_frame + frames > video["frames"]:
        raise StitchError("Mask proposal range exceeds source")
    size = 512
    lenses = lenses_from_metadata(metadata, size)
    relative = np.array(cal["rotation_lens1_to_lens0"])
    step = max(1, (frames - 1) // (samples - 1))
    pixels, indices = [], []
    with video_frames(
        source, float(Fraction(video["fps"])), first_frame, frames, size, paired=True, step=step
    ) as stream:
        for frame, pair in stream:
            pixels.append(pair)
            indices.append(frame)
            if len(pixels) == samples:
                break
    profile = template(metadata)
    profile.update(
        schema_version=2,
        alternate_quality="clipping-contrast-v1",
        proposal=dict(
            status="needs_review",
            source_identity=ids[0],
            sampled_frames=indices,
            calibration_fingerprint=fingerprint(cal),
            limitations=[
                "Sparse multi-frame proposal, not a proven object segmentation",
                "Moving propeller tips, shadows and pale housings can be missed",
                "Inspect native overlays throughout the interval before approval",
            ],
        ),
    )
    x, y = np.meshgrid(np.arange(size), np.arange(size))
    reports = []
    for i in range(2):
        rays, valid = unproject(np.column_stack([x.ravel(), y.ravel()]), lenses[i])
        rays = rays.reshape(size, size, 3)
        alternate_rays = rays @ (relative if i == 0 else relative.T)
        u, v, available = project(alternate_rays, lenses[1 - i])
        # Native outer overlap only, where a real alternate view exists.
        eligible = valid.reshape(size, size) & available & (rays[..., 2] < np.cos(np.radians(82)))
        eligible &= rays[..., 2] > np.cos(np.radians(108))
        native = [pair[i] for pair in pixels]
        alternate = [cv2.remap(pair[1 - i], u, v, cv2.INTER_LINEAR) for pair in pixels]
        polygons, report = detect_obstructions(native, alternate, eligible)
        profile["lenses"][i]["exclude_polygons"] = polygons
        reports.append(report)
    evidence = Path(evidence_dir).absolute()
    evidence.mkdir(parents=True, exist_ok=False)
    for i in range(2):
        panels = []
        mask = np.zeros((size, size), np.uint8)
        for polygon in profile["lenses"][i]["exclude_polygons"]:
            cv2.fillPoly(mask, [np.rint(np.array(polygon) * (size - 1)).astype(np.int32)], 1)
        for j in np.linspace(0, len(pixels) - 1, 6).astype(int):
            image = pixels[j][i].copy()
            image[mask > 0] = (
                np.rint(image[mask > 0] * 0.45 + [0, 0, 140]).clip(0, 255).astype(np.uint8)
            )
            cv2.putText(
                image, str(indices[j]), (12, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2
            )
            panels.append(image)
        image = np.vstack([np.hstack(panels[:3]), np.hstack(panels[3:])])
        if not cv2.imwrite(str(evidence / f"lens-{i}-proposals.png"), image):
            raise StitchError("Could not write mask proposal overlay")
    if [identity(p) for p in paths] != ids:
        raise StitchError("An input changed during mask proposal")
    profile["proposal"]["detection"] = reports
    write_new_json(target, profile)
    write_new_json(evidence / "proposal.json", profile)
    return dict(
        status="needs_review", output=str(target), evidence_dir=str(evidence), detection=reports
    )


def approve(path, output, notes):
    if not isinstance(notes, str) or not 8 <= len(notes.strip()) <= 4000:
        raise StitchError("Record meaningful native-overlay review notes (8–4000 characters)")
    profile = load_json(path)
    validate(profile, allow_unreviewed=True)
    if profile["schema_version"] != 2 or profile["proposal"]["status"] != "needs_review":
        raise StitchError("Only an unreviewed schema-2 proposal can be approved")
    profile["proposal"].update(
        status="reviewed",
        review_notes=notes.strip(),
        proposal_fingerprint=fingerprint(load_json(path)),
    )
    validate(profile)
    write_new_json(output, profile)
    return dict(status="approved", output=str(Path(output).absolute()))
