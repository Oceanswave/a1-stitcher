"""Independent image-to-trajectory timing and native-row readout fitting."""

from fractions import Fraction
from pathlib import Path

import numpy as np
from scipy.optimize import least_squares
from scipy.spatial.transform import Rotation, Slerp

from .calibration import load_calibration, validate_calibration
from .errors import StitchError
from .storage import fingerprint, identity, write_new_json


def fit_timing(first, second, times, rows, groups, pose, mount, readout):
    """Fit two timing parameters; hold out entire temporal blocks, not random tracks."""
    first, second, times, rows = [np.asarray(v, float) for v in [first, second, times, rows]]
    groups = np.asarray(groups)
    n = len(first)
    if (
        n < 200
        or first.shape != (n, 3)
        or second.shape != (n, 3)
        or times.shape != (n, 2)
        or rows.shape != (n, 2)
        or groups.shape != (n,)
        or not all(np.isfinite(v).all() for v in [first, second, times, rows, groups])
        or not 0 < readout <= 0.1
        or (np.abs(rows) > 0.5).any()
        or (times[:, 1] <= times[:, 0]).any()
        or not np.allclose(np.linalg.norm(first, axis=1), 1, atol=1e-4)
        or not np.allclose(np.linalg.norm(second, axis=1), 1, atol=1e-4)
    ):
        raise StitchError("Invalid image timing observations")
    unique = np.unique(groups)
    if len(unique) < 20 or np.std(rows) < 0.12:
        raise StitchError("Insufficient temporal or native-row coverage for a joint timing fit")
    # Four contiguous blocks: 0,2 train; 1,3 holdout. Adjacent tracks never straddle splits.
    block = np.minimum(3, np.searchsorted(unique, groups) * 4 // len(unique))
    train = block % 2 == 0

    def residual(parameters):
        query = times + parameters[0] + rows * readout * parameters[1]
        transforms = pose(query[:, 1]).inv() * pose(query[:, 0])
        predicted = (mount.inv() * transforms * mount).apply(first)
        return predicted - second

    result = least_squares(
        lambda p: residual(p)[train].ravel(),
        [0.0, 1.0],
        bounds=([-0.04, 0.5], [0.04, 1.5]),
        x_scale=[0.01, 0.2],
        loss="soft_l1",
        f_scale=0.002,
        max_nfev=80,
    )
    baseline, fitted = residual([0, 1]), residual(result.x)

    def score(v, selection):
        angles = np.degrees(2 * np.arcsin(np.clip(np.linalg.norm(v[selection], axis=1) / 2, 0, 1)))
        return dict(
            median_degrees=float(np.median(angles)), p95_degrees=float(np.percentile(angles, 95))
        )

    before, after = score(baseline, ~train), score(fitted, ~train)
    singular = np.linalg.svd(result.jac * [0.01, 0.2], compute_uv=False)
    reasons = []
    if not result.success:
        reasons.append("optimizer did not converge")
    if singular[-1] < 0.001 or singular[0] / max(singular[-1], 1e-12) > 100:
        reasons.append("timing/readout are weakly observable or confounded")
    if abs(result.x[0]) > 0.039 or not 0.51 < result.x[1] < 1.49:
        reasons.append("fit reached its search boundary")
    if after["median_degrees"] >= before["median_degrees"] * 0.99:
        reasons.append("held-out median did not improve by at least one percent")
    if after["p95_degrees"] > before["p95_degrees"] * 1.01:
        reasons.append("held-out tail error worsened")
    return dict(
        status="rejected" if reasons else "qualified_on_interval",
        reasons=reasons,
        delta_seconds=float(result.x[0]),
        readout_scale=float(result.x[1]),
        tracks=n,
        train_tracks=int(train.sum()),
        holdout_tracks=int((~train).sum()),
        temporal_groups=len(unique),
        split="four contiguous blocks; alternating train/holdout",
        before_holdout=before,
        after_holdout=after,
        before_train=score(baseline, train),
        after_train=score(fitted, train),
        scaled_jacobian_singular_values=singular.tolist(),
    )


def calibrate(
    source,
    calibration_path,
    gyro_path,
    first_frame,
    frames,
    output,
    evidence_dir,
    step=3,
    anchor_seconds=0.1,
):
    from .exposure import ExposureClock
    from .gyro import trajectory
    from .insv import InsvReader
    from .media import source_profile
    from .projection import lenses_from_metadata, unproject
    from .render import sensor_readout
    from .visual import rigid_rotation, tracks, video_frames

    if (
        any(type(v) is not int for v in [first_frame, frames, step])
        or first_frame < 0
        or not 60 <= frames <= 1800
        or not 1 <= step <= 10
    ):
        raise StitchError("Visual sync needs 60–1800 original frames and a step of 1–10")
    source = Path(source).resolve(strict=True)
    paths = [
        source,
        Path(calibration_path).resolve(strict=True),
        Path(gyro_path).resolve(strict=True),
    ]
    target = Path(output).absolute()
    if target.exists() or target.is_symlink() or target.resolve() in paths:
        raise StitchError("Visual sync output already exists or collides with an input")
    ids = [identity(p) for p in paths]
    reader = InsvReader(source)
    meta = reader.metadata()
    cal = load_calibration(calibration_path, meta)
    if cal["schema_version"] == 3:
        raise StitchError(
            "Refit from the original nominal or exposure calibration, not a visual refit"
        )
    video = source_profile(source, meta)
    if first_frame + frames > video["frames"]:
        raise StitchError("Visual sync exceeds the source video")
    fps = float(Fraction(video["fps"]))
    clock = ExposureClock(reader, fps) if cal.get("frame_clock") == "exposure-midpoint-v1" else None

    def frame_time(indices):
        return (clock.at_frames(indices) if clock else np.asarray(indices) / fps) + cal[
            "time_shift_seconds"
        ]

    readout = sensor_readout(meta, fps, "auto")
    motion, gyro = trajectory(reader, gyro_path, anchor_seconds)
    bounds = frame_time([first_frame, first_frame + frames - 1]) + [-0.04 - readout, 0.04 + readout]
    grid = np.linspace(*bounds, int(np.ceil(np.diff(bounds)[0] * 1000)) + 1)
    pose = Slerp(grid, motion(grid))
    width = 768
    lenses = lenses_from_metadata(meta, width)
    relative = np.array(cal["rotation_lens1_to_lens0"])
    collected = [[], [], [], [], []]
    rejected, previous = 0, None
    with video_frames(source, fps, first_frame, frames, width, step=step, paired=True) as stream:
        for frame, images in stream:
            if previous is not None:
                old_frame, old_images = previous
                for i in range(2):
                    a, b = tracks(old_images[i], images[i])
                    if len(a) < 12:
                        rejected += 1
                        continue
                    ra, va = unproject(a, lenses[i])
                    rb, vb = unproject(b, lenses[i])
                    good = va & vb & (ra[:, 2] > -0.15) & (rb[:, 2] > -0.15)
                    a, b, ra, rb = a[good], b[good], ra[good], rb[good]
                    if i == 1:
                        ra, rb = ra @ relative.T, rb @ relative.T
                    try:
                        _, keep, _ = rigid_rotation(ra, rb, threshold_degrees=0.45)
                    except StitchError:
                        rejected += 1
                        continue
                    indices = np.flatnonzero(keep)[:: max(1, int(keep.sum()) // 120)]
                    collected[0].extend(ra[indices])
                    collected[1].extend(rb[indices])
                    collected[2].extend(np.tile(frame_time([old_frame, frame]), (len(indices), 1)))
                    collected[3].extend(
                        np.column_stack([a[indices, 1], b[indices, 1]]) / (width - 1) - 0.5
                    )
                    collected[4].extend([old_frame] * len(indices))
            previous = frame, images
    evidence = Path(evidence_dir).absolute()
    evidence.mkdir(parents=True, exist_ok=False)
    try:
        fit = fit_timing(*collected, pose, Rotation.from_matrix(cal["lens_mount"]), readout)
    except StitchError as exc:
        fit = dict(status="rejected", reasons=[str(exc)])
    report = dict(
        schema_version=1,
        source=str(source),
        input_identities=ids,
        first_frame=first_frame,
        frames=frames,
        step=step,
        analysis_lens_width=width,
        rejected_lens_pairs=rejected,
        fit=fit,
        base_calibration_fingerprint=fingerprint(cal),
        gyro_profile_fingerprint=fingerprint(gyro),
        gyro_anchor_seconds=anchor_seconds,
        scope="Image tracks on selected interval; requires separate transfer and whole-motion review",
    )
    if [identity(p) for p in paths] != ids:
        raise StitchError("An input changed during visual sync")
    write_new_json(evidence / "fit.json", report)
    if fit["status"] == "rejected":
        return dict(status="rejected", report=str(evidence / "fit.json"), reasons=fit["reasons"])
    result = dict(
        cal,
        schema_version=3,
        frame_clock=cal.get("frame_clock", "nominal"),
        time_shift_seconds=cal["time_shift_seconds"] + fit["delta_seconds"],
        visual_sync=dict(
            kind="a1-image-row-sync-v1",
            readout_scale=fit["readout_scale"],
            gyro_profile_fingerprint=fingerprint(gyro),
            gyro_anchor_seconds=anchor_seconds,
            capture_mode=dict(fps=video["fps"], readout_seconds=readout),
            base_calibration_fingerprint=fingerprint(cal),
            qualification=fit,
        ),
        quality_status="experimental_image_timing",
    )
    validate_calibration(result, meta)
    write_new_json(target, result)
    return dict(status="calibrated", output=str(target), report=str(evidence / "fit.json"), fit=fit)
