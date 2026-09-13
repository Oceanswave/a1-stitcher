"""Observed A1 exposure telemetry. Report timing without guessing gyro offsets."""

import numpy as np

from .errors import StitchError


def exposure_data(reader):
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
    return times, durations.copy()


def exposure_summary(reader):
    parsed = exposure_data(reader)
    if parsed is None:
        return None
    times, durations = parsed
    steps = np.diff(times)
    nominal = float(np.median(steps))
    return dict(
        samples=len(times),
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


class ExposureClock:
    """Frame-indexed exposure midpoint clock; requires a newly fitted calibration.

    The tested source embeds an exact first-video timestamp in its exposure list.
    Ordinal mapping is accepted only when every selected timestamp agrees with
    the constant-rate frame index. Missing records never shift later indices.
    """

    kind = "exposure-midpoint-v1"

    def __init__(self, reader, fps):
        parsed = exposure_data(reader)
        if parsed is None:
            raise StitchError("Exposure-aware sync requires exposure record 4")
        self.fps = float(fps)
        if not np.isfinite(self.fps) or not 1 <= self.fps <= 240:
            raise StitchError("Invalid exposure clock frame rate")
        times, durations = parsed
        zero = np.flatnonzero(np.abs(times) < 1e-9)
        if len(zero) != 1:
            raise StitchError("Exposure track lacks a unique exact first-video timestamp")
        self.first_record = int(zero[0])
        self.timestamps = times[self.first_record :]
        self.durations = durations[self.first_record :]
        expected = np.arange(len(self.timestamps)) / self.fps
        if np.any(np.abs(self.timestamps - expected) > 0.1 / self.fps):
            raise StitchError("Exposure/frame correspondence has a gap or unsupported timing drift")
        if np.any(self.durations > 1.01 / self.fps):
            raise StitchError("Exposure duration exceeds the video frame period")

    def at_frames(self, frames):
        frames = np.atleast_1d(frames)
        if (
            frames.dtype.kind not in "iu"
            or np.any(frames < 0)
            or np.any(frames >= len(self.timestamps))
        ):
            raise StitchError("Frame indices exceed exposure clock coverage")
        return self.timestamps[frames] - self.durations[frames] / 2

    def at_video_times(self, times):
        frames = np.asarray(times) * self.fps
        rounded = np.rint(frames)
        if not np.isfinite(frames).all() or np.any(np.abs(frames - rounded) > 1e-5):
            raise StitchError("Exposure sync needs exact source-frame observation times")
        return self.at_frames(rounded.astype(np.int64))

    def report(self):
        return dict(
            kind=self.kind,
            first_exposure_record=self.first_record,
            frames=len(self.timestamps),
            exposure_duration_applied=True,
            convention="frame exposure timestamp minus half shutter duration plus refitted attitude offset",
        )
