"""Read-only camera ingest checks, explicitly separate from image qualification."""

import numpy as np

from .cameras import camera_adapter
from .errors import StitchError
from .insv import InsvReader
from .media import input_profile
from .projection import lenses_from_metadata
from .storage import identity


def imu_summary(reader, metadata):
    record = reader.records.get(3)
    if record is None or not metadata.get("is_raw_gyro"):
        return dict(status="absent-or-not-raw", orientation_qualified=False)
    if record.encoding != 0 or not 2000 <= record.size <= 64 * 1024 * 1024 or record.size % 20:
        raise StitchError("Unsupported indexed raw IMU layout")
    data = np.frombuffer(reader.payload(3), dtype=np.dtype([("time", "<u8"), ("raw", "<u2", (6,))]))
    stamps = data["time"]
    origin = metadata.get("first_frame_timestamp_us")
    if (
        type(origin) is not int
        or not 0 <= origin <= 2**53
        or np.any(stamps > 2**53)
        or np.any(stamps[1:] <= stamps[:-1])
    ):
        raise StitchError("Invalid raw IMU clock")
    steps = np.diff(stamps).astype(float) / 1e6
    if steps.max() > 0.010001 or not 200 <= 1 / np.median(steps) <= 2000:
        raise StitchError("Raw IMU cadence is unsupported or has gaps")
    return dict(
        status="indexed-20-byte-layout",
        samples=len(data),
        first_relative_seconds=(int(stamps[0]) - origin) / 1e6,
        last_relative_seconds=(int(stamps[-1]) - origin) / 1e6,
        median_rate_hz=float(1 / np.median(steps)),
        orientation_qualified=False,
        qualification="Raw sensor axes are not camera orientation; no integration or mount transform applied",
    )


def preflight(source):
    before = identity(source)
    reader = InsvReader(source)
    metadata = reader.metadata()
    adapter = camera_adapter(metadata)
    profile = input_profile(source, metadata)
    lenses_from_metadata(metadata, profile["width"])
    imu = imu_summary(reader, metadata)
    if identity(source) != before:
        raise StitchError("Source changed during camera preflight")
    blockers = (
        []
        if adapter.sphere_export
        else [
            "No measured X5 sensor-to-lens orientation and image-timing profile",
            "No independently rendered X5 native-resolution motion/seam qualification",
            "No X5 pilot-view interpretation; A1 records and profiles must not be reused",
        ]
    )
    return dict(
        kind="camera-input-preflight-v1",
        source=str(reader.path),
        source_identity=before,
        camera_type=adapter.name,
        adapter=adapter.identifier,
        status="input-contract-passed",
        trailer_version=reader.version,
        profile=profile,
        lens_geometry="observed two-lens 40-value MEI layout; structural validation only",
        imu=imu,
        embedded_orientation_records={str(k): k in reader.records for k in (32, 37)},
        sphere_export_available=adapter.sphere_export,
        export_blockers=blockers,
        quality_qualification="No pixels rendered; motion, seams and audio-content sync are unqualified",
    )
