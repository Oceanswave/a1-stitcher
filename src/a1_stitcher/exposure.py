"""Observed A1 exposure telemetry. Report timing without guessing gyro offsets."""

import numpy as np

from .errors import StitchError


def exposure_summary(reader):
    """Inspect the observed uint64-microsecond / float64-second record-4 layout.

    These timestamps are reported relative to the first video timestamp. Their
    shutter-edge convention is not a license to change a fitted frame clock.
    """
    record = reader.records.get(4)
    if record is None:
        return None
    metadata = reader.metadata()
    if (
        metadata.get("camera_type") != "Antigravity A1"
        or "first_frame_timestamp_us" not in metadata
        or record.encoding != 0
        or not 32 <= record.size <= 64 * 1024 * 1024
        or record.size % 16
    ):
        raise StitchError("Unsupported A1 exposure record layout")
    data = np.frombuffer(reader.payload(4), dtype=[("timestamp", "<u8"), ("seconds", "<f8")])
    stamps, durations = data["timestamp"], data["seconds"]
    if (
        np.any(stamps[1:] <= stamps[:-1])
        or np.any(stamps > 2**53)
        or not np.isfinite(durations).all()
        or np.any(durations <= 0)
        or np.any(durations > 1)
    ):
        raise StitchError("Invalid exposure timestamps or durations")
    times = (stamps.astype(np.float64) - metadata["first_frame_timestamp_us"]) / 1e6
    steps = np.diff(times)
    nominal = float(np.median(steps))
    if not 0.001 <= nominal <= 1:
        raise StitchError("Unsupported exposure sample cadence")
    return dict(
        samples=len(data),
        first_relative_seconds=float(times[0]),
        last_relative_seconds=float(times[-1]),
        median_sample_interval_seconds=nominal,
        gaps_over_two_intervals=int(np.count_nonzero(steps > 2 * nominal)),
        shutter_seconds=dict(
            minimum=float(durations.min()),
            median=float(np.median(durations)),
            p95=float(np.percentile(durations, 95)),
            maximum=float(durations.max()),
        ),
        half_exposure_variation_seconds=float(np.ptp(durations) / 2),
        applied_to_frame_clock=False,
        timing_convention="Record timestamps minus first video timestamp; exposure edge semantics not yet calibrated",
    )
