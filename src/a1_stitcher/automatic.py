"""Reference-free setup using embedded camera orientation and original overlap."""

from fractions import Fraction

import numpy as np
from scipy.spatial.transform import Rotation

from .calibration import lens_fingerprint
from .errors import StitchError
from .projection import lenses_from_metadata, match_lenses
from .viewpoint import Viewpoint
from .visual import video_frames


def fit_overlap(frames, lenses, *, minimum=1):
    candidates = []
    failures = []
    for pair in frames:
        try:
            rotation, score = match_lenses(*pair, lenses)
            if (
                score["inliers"] < 30
                or score["inliers"] < score["valid"] * 0.5
                or score["p95_error_degrees"] > 1.2
            ):
                raise StitchError("Lens alignment has too few consistent matches")
            candidates.append((rotation, score))
        except (StitchError, ValueError) as exc:
            failures.append(str(exc))
    if not candidates:
        raise StitchError(
            "Automatic lens alignment found insufficient overlap texture; try a different range or provide --calibration"
        )
    rotations = Rotation.from_matrix([c[0] for c in candidates])
    # Select an observed medoid rather than averaging incompatible scene fits.
    distance = np.array([np.degrees((r.inv() * rotations).magnitude()) for r in rotations])
    index = int(np.argmin(np.median(distance, axis=1)))
    consistent = distance[index] <= 0.75
    if consistent.sum() < max(minimum, len(candidates) // 2 + 1 if len(candidates) > 1 else 1):
        raise StitchError(
            "Too few original overlap fits agree within 0.75 degrees; use a better calibration interval"
        )
    return candidates[index][0], dict(
        samples=len(candidates),
        observations=[c[1] for c in candidates],
        rejected=failures,
        rejected_geometric_outliers=int((~consistent).sum()),
        consistent_samples=int(consistent.sum()),
        maximum_disagreement_degrees=float(np.max(distance[index][consistent])),
    )


def calibration_from_original(reader, profile, first_frame, *, progress=None):
    view = Viewpoint(reader)
    fps = Fraction(profile["fps"])
    width = min(1920, profile["width"])
    lenses = lenses_from_metadata(reader.metadata(), width)
    count = profile["frames"]
    indices = sorted(
        set(min(count - 1, first_frame + n) for n in [0, round(float(fps)), round(float(fps) * 3)])
    )
    # Near the end of a recording, use earlier original frames as well. A short
    # requested output must not require nonexistent forward calibration samples.
    for delta in [round(float(fps)), round(float(fps) * 3), first_frame]:
        if len(indices) >= 3:
            break
        indices = sorted(set([*indices, max(0, first_frame - delta)]))
    pairs = []
    for frame in indices:
        if progress:
            progress(dict(stage="automatic-lens-alignment", source_frame=frame))
        with video_frames(reader.path, float(fps), frame, 1, width, paired=True) as decoded:
            pairs.append(next(decoded)[1])
    relative, evidence = fit_overlap(pairs, lenses, minimum=2)
    return dict(
        schema_version=4,
        camera_type="Antigravity A1",
        lens_fingerprint=lens_fingerprint(reader.metadata()),
        orientation_source="a1-plane-view-camera-v1",
        rotation_lens1_to_lens0=relative.tolist(),
        method="original-only-overlap-and-embedded-orientation",
        quality_status="experimental",
        source_frames=indices,
        overlap=evidence,
        embedded_view=view.report(),
    )
