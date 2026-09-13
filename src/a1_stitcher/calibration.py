"""Camera-specific calibration schema and reference-based attitude fitting."""

from __future__ import annotations

import hashlib
import json

import numpy as np
from scipy.optimize import least_squares
from scipy.spatial.transform import Rotation, Slerp

from .errors import StitchError
from .projection import orientation37
from .storage import load_json


def lens_fingerprint(metadata):
    return hashlib.sha256(
        json.dumps(
            [float(value) for value in metadata["offset_v3"]],
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()


def rotation_matrix(value, name):
    array = np.asarray(value, dtype=np.float64)
    if array.shape != (3, 3) or not np.isfinite(array).all():
        raise StitchError(f"{name} must be a finite 3x3 matrix")
    if not np.allclose(array.T @ array, np.eye(3), atol=1e-5) or not np.isclose(
        np.linalg.det(array), 1, atol=1e-5
    ):
        raise StitchError(f"{name} must be a proper rotation (no reflection or scale)")
    return array


def validate_calibration(data, metadata=None):
    if (
        not isinstance(data, dict)
        or type(data.get("schema_version")) is not int
        or data.get("schema_version") not in (1, 2, 3)
    ):
        raise StitchError("Unsupported calibration schema; expected schema_version 1, 2 or 3")
    if (data["schema_version"] == 2 and data.get("frame_clock") != "exposure-midpoint-v1") or (
        data["schema_version"] == 1 and data.get("frame_clock", "nominal") != "nominal"
    ):
        raise StitchError(
            "Calibration frame clock does not match its schema; refit exposure timing"
        )
    if data.get("camera_type") != "Antigravity A1":
        raise StitchError("Calibration is not for Antigravity A1")
    try:
        fingerprint = data["lens_fingerprint"]
        if len(fingerprint) != 64 or any(c not in "0123456789abcdef" for c in fingerprint):
            raise ValueError("invalid lens fingerprint")
        rotation_matrix(data["lens_mount"], "lens_mount")
        rotation_matrix(data["rotation_lens1_to_lens0"], "rotation_lens1_to_lens0")
        offset = data["time_shift_seconds"]
        if (
            isinstance(offset, bool)
            or not isinstance(offset, (int, float))
            or not np.isfinite(offset)
            or abs(offset) > 0.5
        ):
            raise ValueError("attitude time offset must be finite and within +/-0.5 seconds")
        if data.get("inverse") is not False:
            raise ValueError("only the measured non-inverse A1 attitude convention is supported")
        if metadata is not None and lens_fingerprint(metadata) != fingerprint:
            raise ValueError("calibration belongs to different embedded lens parameters")
        if data["schema_version"] == 3:
            sync = data["visual_sync"]
            if (
                data.get("frame_clock") not in ["nominal", "exposure-midpoint-v1"]
                or sync.get("kind") != "a1-image-row-sync-v1"
            ):
                raise ValueError("invalid image timing clock or model")
            for key in ["gyro_profile_fingerprint", "base_calibration_fingerprint"]:
                value = sync[key]
                if len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
                    raise ValueError("invalid timing dependency fingerprint")
            for key, lower, upper in [
                ("readout_scale", 0.5, 1.5),
                ("gyro_anchor_seconds", 0.02, 1),
            ]:
                value = sync[key]
                if (
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not np.isfinite(value)
                    or not lower <= value <= upper
                ):
                    raise ValueError(f"invalid image timing {key}")
    except (KeyError, TypeError, ValueError) as exc:
        raise StitchError(f"Invalid calibration: {exc}") from exc
    return data


def load_calibration(path, metadata=None):
    return validate_calibration(load_json(path), metadata)


def migrate_legacy(data):
    """Explicit migration of the initial local prototype's calibration document."""
    if data.get("frame_clock", "nominal") != "nominal" or data.get("schema_version", 1) in (2, 3):
        raise StitchError("Cannot migrate an exposure calibration to the legacy nominal clock")
    names = [
        "camera_type",
        "lens_fingerprint",
        "lens_mount",
        "time_shift_seconds",
        "inverse",
        "rotation_lens1_to_lens0",
        "training",
        "holdouts",
    ]
    result = {k: data[k] for k in names if k in data}
    result.update(
        schema_version=1,
        quality_status="experimental",
        warnings=["Migrated calibration retains its original sampled qualification limits"],
    )
    return validate_calibration(result)


def fit_gravity(reader, observations, frame_clock=None):
    if len(observations) < 6:
        raise StitchError("At least six matched observations are required for calibration")
    frames = np.asarray([r["raw_seconds"] for r in observations], dtype=float)
    if not np.isfinite(frames).all() or np.any(np.diff(frames) <= 0):
        raise StitchError("Calibration observation times must be finite and increasing")
    if frame_clock is not None:
        frames = frame_clock.at_video_times(frames)
    lens_down = (
        Rotation.from_matrix(
            [rotation_matrix(r["lens_to_reference"], "observation") for r in observations]
        )
        .inv()
        .apply([0, 1, 0])
    )
    if np.max(np.linalg.norm(lens_down - lens_down.mean(axis=0), axis=1)) < 0.015:
        raise StitchError(
            "Too little tilt variation to determine camera mounting; choose a varied reference interval"
        )
    times, poses = orientation37(reader)
    lower = max(-0.5, times[0] - frames[0])
    upper = min(0.5, times[-1] - frames[-1])
    if lower >= upper or not lower <= 0 <= upper:
        raise StitchError("Reference times are outside recorded attitude coverage")
    slerp = Slerp(times, poses)

    def residual(parameters):
        transformed = (slerp(frames + parameters[3]) * Rotation.from_rotvec(parameters[:3])).apply(
            lens_down
        )
        return (transformed - [0, 0, 1]).ravel()

    initial = np.r_[Rotation.from_euler("z", -90, degrees=True).as_rotvec(), 0.0]
    fit = least_squares(residual, initial, bounds=([-10] * 3 + [lower], [10] * 3 + [upper]))
    if not fit.success or np.linalg.matrix_rank(fit.jac, tol=1e-6) < 4:
        raise StitchError("Mounting/time fit is underconstrained; choose a more varied reference")
    return Rotation.from_rotvec(fit.x[:3]), float(fit.x[3])


def score_gravity(reader, observations, mount, shift, frame_clock=None):
    times, poses = orientation37(reader)
    frames = np.asarray([r["raw_seconds"] for r in observations], dtype=float)
    if frame_clock is not None:
        frames = frame_clock.at_video_times(frames)
    frames = frames + shift
    if not len(frames) or frames.min() < times[0] or frames.max() > times[-1]:
        raise StitchError("Scored observations exceed recorded attitude coverage")
    down = (
        Rotation.from_matrix(
            [rotation_matrix(r["lens_to_reference"], "observation") for r in observations]
        )
        .inv()
        .apply([0, 1, 0])
    )
    world = (Slerp(times, poses)(frames) * mount).apply(down)
    errors = np.degrees(np.arccos(np.clip(world[:, 2], -1, 1)))
    return dict(
        samples=len(frames),
        errors_degrees=errors.tolist(),
        rms_degrees=float(np.sqrt(np.mean(errors**2))),
        maximum_degrees=float(errors.max()),
    )
