"""Recorded X5 parameters, without guessing a vendor projection or IMU mounting.

The installed Studio schema identifies fields 104, 111/112, 136 and 64.
Field 145's observed named double/integer entries remain explicitly undocumented.
This reader does not import vendor software or produce a rendering calibration.
"""

import hashlib
import json
import struct
from fractions import Fraction

import numpy as np

from .errors import StitchError
from .insv import InsvReader, protobuf_fields
from .media import input_profile
from .storage import identity

GUARDS = {0: "unknown", 1: "A", 2: "S", 3: "OFF", 4: "A_S"}
PROFILE_NAMES = {1: "ProtectorA", 2: "ProtectorS", 3: "bare", 4: "ProtectorAS"}


def singular(fields, number, wire, default=None):
    entries = fields.get(number)
    if entries is None:
        return default
    if len(entries) != 1 or entries[0][0] != wire:
        raise StitchError(
            f"Invalid recorded parameter field {number}: singular wire {wire} required"
        )
    return entries[0][1]


def lens_record(payload):
    try:
        values = [float(v) for v in payload.decode("utf-8").split("_")]
    except (ValueError, UnicodeError) as exc:
        raise StitchError("Invalid offset_v6 numeric string") from exc
    if len(values) != 56 or values[0] != 2 or not np.isfinite(values).all():
        raise StitchError(
            "Only the observed finite two-lens 56-value offset_v6 layout is supported"
        )
    lenses = []
    for index in range(2):
        v = values[1 + 27 * index : 28 + 27 * index]
        if (
            v[0] <= 1
            or min(v[1:3]) <= 0
            or v[24] != 2 * v[25]
            or v[25] < 32
            or v[26] != 113
            or not index * v[25] <= v[3] <= (index + 1) * v[25]
            or not 0 <= v[4] <= v[25]
        ):
            raise StitchError("Unsupported offset_v6 lens geometry/type")
        lenses.append(
            dict(
                xi=v[0],
                sensor_intrinsics=dict(fx=v[1], fy=v[2], cx=v[3], cy=v[4]),
                extrinsic_angle_values=v[5:8],
                translation_values=v[8:11],
                distortion_slots=v[11:24],
                concatenated_sensor_width=v[24],
                sensor_height=v[25],
                lens_type=v[26],
            )
        )
    return dict(
        layout="two lenses, 27 values per lens, trailing flag",
        lenses=lenses,
        trailing_flag=values[-1],
        interpretation="Recorded values; distortion ordering/equation and crop/extrinsic conventions are not qualified",
    )


def accessory_candidates(payload):
    if payload is None:
        return {}
    fields = protobuf_fields(payload)
    if not set(fields) <= {1, 2, 3} or 1 not in fields:
        raise StitchError("Unsupported field-145 accessory entry list")
    result = {}
    for group, entries in fields.items():
        if not 1 <= len(entries) <= 32:
            raise StitchError("Accessory entry count exceeds supported bounds")
        result[str(group)] = parsed = []
        for wire, value in entries:
            if wire != 2:
                raise StitchError("Invalid accessory entry wire")
            entry = protobuf_fields(value)
            name = singular(entry, 1, 2)
            if name is None or not 1 <= len(name) <= 64 or set(entry) != {1, 2}:
                raise StitchError("Invalid accessory entry name or fields")
            try:
                name = name.decode("ascii")
            except UnicodeError as exc:
                raise StitchError("Accessory entry name must be ASCII") from exc
            if not name.replace("_", "").isalnum() or any(p["name"] == name for p in parsed):
                raise StitchError("Invalid or duplicate accessory entry name")
            count, expected = (6, 1) if group == 1 else (1, 1 if group == 2 else 0)
            if len(entry[2]) != count or any(w != expected for w, _ in entry[2]):
                raise StitchError("Unsupported accessory slot count or wire")
            slots = [struct.unpack("<d", v)[0] if w == 1 else v for w, v in entry[2]]
            if not np.isfinite(slots).all():
                raise StitchError("Non-finite accessory parameters")
            parsed.append(dict(name=name, slots=slots))
    return result


def exposure_clock(reader, metadata, profile, frame=None):
    fps = float(Fraction(profile["fps"]))
    record = reader.records.get(4)
    if (
        record is None
        or record.encoding != 0
        or not 32 <= record.size <= 64 * 1024 * 1024
        or record.size % 16
    ):
        raise StitchError("Recorded X5 clock requires the observed exposure record-4 layout")
    data = np.frombuffer(reader.payload(4), dtype=[("t", "<u8"), ("duration", "<f8")])
    stamps, durations = data["t"], data["duration"]
    origin = metadata.get("first_frame_timestamp_us")
    if (
        type(origin) is not int
        or not 0 <= origin <= 2**53
        or np.any(stamps > 2**53)
        or np.any(stamps[1:] <= stamps[:-1])
        or not np.isfinite(durations).all()
        or np.any(durations <= 0)
        or np.any(durations > 1.01 / fps)
    ):
        raise StitchError("Invalid recorded X5 exposure clock")
    zero = np.flatnonzero(stamps == origin)
    if len(zero) != 1 or len(stamps) - zero[0] < profile["frames"]:
        raise StitchError("Exposure clock lacks exact frame zero or complete video coverage")
    start = int(zero[0])
    times = (stamps[start : start + profile["frames"]].astype(float) - origin) / 1e6
    if len(times) > 1 and np.max(np.diff(times)) > 1.1 / fps:
        raise StitchError("Exposure clock has missing frames or unsupported cadence")
    residual = times - np.arange(len(times)) / fps
    result = dict(
        first_exposure_record=start,
        mapped_frames=len(times),
        mapping="ordinal records from a unique exact frame-zero timestamp; not an image-edge qualification",
        playback_residual_seconds=dict(
            minimum=float(residual.min()), maximum=float(residual.max())
        ),
        applied_to_renderer=False,
        qualification="Exposure edge, gyro offset sign and image timing remain unqualified",
    )
    if frame is not None:
        if type(frame) is not int or not 0 <= frame < len(times):
            raise StitchError("Frame exceeds recorded exposure clock coverage")
        duration = float(durations[start + frame])
        result["selected_frame"] = dict(
            source_frame=frame,
            exposure_record=start + frame,
            relative_timestamp_seconds=float(times[frame]),
            shutter_seconds=duration,
            candidate_midpoint_seconds=float(times[frame] - duration / 2),
            midpoint_applied=False,
        )
    return result


def recorded_calibration(source, frame=None):
    before = identity(source)
    reader = InsvReader(source)
    metadata = reader.metadata()
    if metadata.get("camera_type") != "Insta360 X5":
        raise StitchError("Recorded-calibration interpretation is currently X5 only")
    profile = input_profile(source, metadata)
    fields = protobuf_fields(reader.payload(1))
    version = singular(fields, 136, 0)
    current, original = singular(fields, 111, 2), singular(fields, 112, 2)
    if version != 4 or current is None or original is None:
        raise StitchError(
            "An explicit captured OFFSET_V6 and current/original lens records are required"
        )
    lenses, original_lenses = lens_record(current), lens_record(original)
    candidates = accessory_candidates(singular(fields, 145, 2))
    detected = singular(fields, 104, 0)
    matched_name = PROFILE_NAMES.get(detected)
    # The detection label can identify a candidate. It cannot establish that
    # Studio used it, or that its six slots implement a known optical equation.
    matched = next((p for p in candidates.get("1", []) if p["name"] == matched_name), None)
    clock = exposure_clock(reader, metadata, profile, frame)
    parameters = dict(
        capture=dict(
            camera_type=metadata["camera_type"],
            firmware=metadata.get("firmware"),
            fps=profile["fps"],
            width=profile["width"],
            color=profile["color"],
            recording_mode=profile["recording_mode"],
        ),
        offset_v6=lenses,
        original_offset_v6=original_lenses,
        captured_offset_version=version,
        guard_detected_value=detected,
        accessory_candidates=candidates,
        window_crop_info=metadata.get("window_crop_info"),
        gyro_configuration=metadata.get("gyro_configuration"),
        gyro_calibration_values=metadata.get("gyro_calibration_values"),
        gyro_calibration_semantics="Six recorded slots; units and bias/rotation meaning are not established",
        gyro_calibration_payload_sha256=(
            hashlib.sha256(singular(fields, 31, 2)).hexdigest() if 31 in fields else None
        ),
        gyro_timestamp_parameter=metadata.get("gyro_timestamp_ms"),
        has_gyro_timestamp=metadata.get("has_gyro_timestamp"),
        gyro_timestamp_applied=False,
        rolling_shutter_ms=metadata.get("rolling_shutter_ms"),
        pts_type=singular(fields, 64, 0),
        orientation_calib_present=37 in fields,
        orientation_calib_payload_sha256=(
            hashlib.sha256(singular(fields, 37, 2)).hexdigest() if 37 in fields else None
        ),
    )
    fingerprint = hashlib.sha256(
        json.dumps(parameters, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()
    if identity(source) != before:
        raise StitchError("Source changed during recorded calibration inspection")
    return dict(
        kind="x5-recorded-parameters-v1",
        source=str(reader.path),
        source_identity=before,
        camera_type=metadata["camera_type"],
        firmware=metadata.get("firmware"),
        parameter_fingerprint=fingerprint,
        parameters=parameters,
        current_equals_original=current == original,
        guard_detection=dict(
            label=GUARDS.get(detected, "unsupported"),
            matched_candidate=matched["name"] if matched else None,
            applied=False,
            qualification="Recorded detection/candidate only; not Standard/Premium identification or Studio override state",
        ),
        exposure_clock=clock,
        sphere_export_available=False,
        qualification="Recorded parameter recovery only; no vendor coefficients/axis transform guessed or calibration capture used for this report",
    )
