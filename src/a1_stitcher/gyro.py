"""Per-unit rigid gyro calibration and drift-bounded interpolation of recorded attitude.

Calibration deliberately uses slow motion. It does not qualify high-frequency
sensor-to-image timing; the optional trajectory remains experimental.
"""

import numpy as np
from scipy.signal import butter, sosfiltfilt
from scipy.spatial.transform import Rotation, Slerp

from .calibration import lens_fingerprint, rotation_matrix
from .errors import StitchError
from .insv import InsvReader
from .projection import orientation37
from .storage import identity, load_json, write_new_json


def raw_gyro(reader):
    meta = reader.metadata()
    if meta.get("camera_type") != "Antigravity A1":
        raise StitchError("Raw gyro calibration requires an Antigravity A1 source")
    if 3 not in reader.records or reader.records[3].encoding != 0:
        raise StitchError("Missing or encoded raw gyro record")
    payload = reader.payload(3)
    scale = meta.get("gyro_configuration", {}).get("gyro_range_dps")
    if not payload or len(payload) % 20 or scale not in (250, 500, 1000, 2000, 4000):
        raise StitchError("Unsupported raw gyro layout or range")
    data = np.frombuffer(
        payload, dtype=np.dtype([("t", "<u8"), ("acc", "<u2", (3,)), ("gyro", "<u2", (3,))])
    )
    times = (data["t"].astype(float) - meta["first_frame_timestamp_us"]) / 1e6
    if (
        len(times) < 100
        or not np.isfinite(times).all()
        or np.any(np.diff(times) <= 0)
        or np.max(np.diff(times)) > 0.010001
    ):
        raise StitchError("Raw gyro timestamps contain gaps or invalid ordering")
    rate = 1 / np.median(np.diff(times))
    if not 200 <= rate <= 2000:
        raise StitchError("Unsupported raw gyro sample rate")
    if np.any(data["gyro"] < 8) or np.any(data["gyro"] > 65527):
        raise StitchError("Raw gyro saturation prevents reliable reconstruction")
    return times, np.radians((data["gyro"].astype(float) - 32768) * scale / 32768)


def dataset(reader):
    rt, values = raw_gyro(reader)
    times, pose = orientation37(reader)
    if np.max(np.diff(times)) > 0.050001:
        raise StitchError("Recorded attitude contains gaps")
    pt = (times[1:] + times[:-1]) / 2
    omega = (pose[:-1].inv() * pose[1:]).as_rotvec() / np.diff(times)[:, None]

    def lowpass(data, clock):
        return sosfiltfilt(
            butter(3, 2, fs=1 / np.median(np.diff(clock)), output="sos"), data, axis=0
        )

    values, omega = lowpass(values, rt), lowpass(omega, pt)
    valid = (pt > max(30, rt[0] + 5)) & (pt < min(rt[-1], pt[-1]) - 5)
    ts, target = pt[valid][::5], omega[valid][::5]
    if len(ts) < 200:
        raise StitchError("Need at least 55 seconds of overlapping gyro and recorded attitude")
    train = (ts.astype(int) // 10 % 2) == 0
    if min(train.sum(), (~train).sum()) < 50:
        raise StitchError("Insufficient independent motion blocks")
    return rt, values, ts, target, train


def interpolate(times, values, query):
    return np.column_stack([np.interp(query, times, values[:, c]) for c in range(3)])


def rms(error):
    return float(np.degrees(np.sqrt(np.mean(np.sum(error * error, axis=1)))))


def fit(reader):
    rt, values, ts, target, train = dataset(reader)
    best = None
    for shift in np.linspace(-0.06, 0.06, 121):
        vals = interpolate(rt, values, ts + shift)
        a, b = vals[train], target[train]
        ac, bc = a - a.mean(0), b - b.mean(0)
        singular = np.linalg.svd(ac, compute_uv=False)
        if singular[-1] / np.sqrt(len(a)) < np.radians(0.5):
            raise StitchError("Too little motion across all three axes to fit gyro calibration")
        u, _, vh = np.linalg.svd(ac.T @ bc)
        matrix = u @ np.diag([1, 1, np.linalg.det(u @ vh)]) @ vh
        bias = b.mean(0) - a.mean(0) @ matrix
        error = vals @ matrix + bias - target
        cost = rms(error[train])
        if best is None or cost < best[0]:
            best = (cost, shift, matrix, bias, error)
    cost, shift, matrix, bias, error = best
    if abs(shift) >= 0.06 or rms(error[~train]) > 3 or np.linalg.norm(bias) > np.radians(5):
        raise StitchError("Gyro fit failed timing, bias or held-out residual bounds")
    return dict(
        schema_version=1,
        kind="a1-rigid-gyro-v1",
        lens_fingerprint=lens_fingerprint(reader.metadata()),
        raw_query_shift_seconds=float(shift),
        raw_to_body_row_matrix=matrix.tolist(),
        body_bias_radians_per_second=bias.tolist(),
        qualification=dict(
            cutoff_hz=2,
            train_rms_dps=cost,
            holdout_rms_dps=rms(error[~train]),
            training_samples=int(train.sum()),
            holdout_samples=int((~train).sum()),
        ),
        quality_status="experimental; slow-motion calibration is not high-frequency image qualification",
    )


def validate(profile, metadata):
    try:
        if profile["schema_version"] != 1 or profile["kind"] != "a1-rigid-gyro-v1":
            raise ValueError("unsupported gyro profile schema")
        if profile["lens_fingerprint"] != lens_fingerprint(metadata):
            raise ValueError("gyro profile belongs to different embedded lens parameters")
        rotation_matrix(profile["raw_to_body_row_matrix"], "gyro axis rotation")
        bias = np.asarray(profile["body_bias_radians_per_second"])
        shift = profile["raw_query_shift_seconds"]
        if (
            bias.shape != (3,)
            or not np.isfinite(bias).all()
            or np.linalg.norm(bias) > np.radians(5)
        ):
            raise ValueError("invalid gyro bias")
        if isinstance(shift, bool) or not np.isfinite(shift) or abs(shift) > 0.06:
            raise ValueError("invalid gyro timing offset")
    except (KeyError, TypeError, ValueError) as exc:
        raise StitchError(f"Invalid gyro calibration: {exc}") from exc
    return profile


def calibrate(source, validation_source, output):
    reader, other = InsvReader(source), InsvReader(validation_source)
    if reader.path == other.path:
        raise StitchError("Choose a different recording for gyro transfer validation")
    identities = [identity(r.path) for r in (reader, other)]
    profile = validate(fit(reader), other.metadata())
    rt, values, ts, target, _ = dataset(other)
    predicted = (
        interpolate(rt, values, ts + profile["raw_query_shift_seconds"])
        @ np.array(profile["raw_to_body_row_matrix"])
        + profile["body_bias_radians_per_second"]
    )
    transfer = rms(predicted - target)
    if transfer > 3:
        raise StitchError(f"Gyro calibration did not transfer: {transfer:.3f} degrees/second RMS")
    profile["qualification"]["transfer_rms_dps"] = transfer
    profile["qualification"]["transfer_samples"] = len(ts)
    if identities != [identity(r.path) for r in (reader, other)]:
        raise StitchError("Source changed during gyro calibration")
    profile["sources"] = [
        dict(path=str(r.path), identity=identity(r.path)) for r in (reader, other)
    ]
    write_new_json(output, profile)
    return profile


class AnchoredGyro:
    """Integrate within each attitude interval, matching both recorded endpoints.

    Each query integrates at <=1 ms. Endpoint error is distributed smoothly in
    rotation space, bounding drift to one recorded interval instead of a flight.
    No extrapolation or gaps are permitted.
    """

    def __init__(self, times, poses, raw_times, values, profile):
        self.times, self.poses = np.asarray(times), poses
        self.raw_times = np.asarray(raw_times) - profile["raw_query_shift_seconds"]
        self.values = (
            np.asarray(values) @ np.array(profile["raw_to_body_row_matrix"])
            + profile["body_bias_radians_per_second"]
        )
        if len(times) < 2 or np.any(np.diff(times) <= 0) or np.max(np.diff(times)) > 1.000001:
            raise StitchError("Recorded attitude contains gaps or invalid ordering")
        if np.any(np.diff(raw_times) <= 0) or np.max(np.diff(raw_times)) > 0.010001:
            raise StitchError("Raw gyro contains gaps or invalid ordering")
        self.recorded = Slerp(times, poses)
        # np.interp otherwise copies a strided column of the entire flight on
        # every integration step. Row sampling needs many short queries.
        self.components = [np.ascontiguousarray(self.values[:, c]) for c in range(3)]
        self.anchor_errors = np.full((len(times) - 1, 3), np.nan)

    def rates(self, query):
        return np.column_stack([np.interp(query, self.raw_times, c) for c in self.components])

    def integrate(self, start, end):
        steps = np.maximum(1, np.ceil((end - start) / 0.001).astype(int))
        result = Rotation.identity(len(start))
        dt = (end - start) / steps
        for index in range(int(steps.max())):
            active = index < steps
            a = start + np.minimum(index, steps) * dt
            b = start + np.minimum(index + 1, steps) * dt
            omega = (self.rates(a) + self.rates(b)) / 2
            increment = Rotation.from_rotvec(omega * ((b - a) * active)[:, None])
            result = result * increment
        return result

    def __call__(self, query):
        query = np.atleast_1d(np.asarray(query, float))
        if (
            not len(query)
            or not np.isfinite(query).all()
            or query.min() < self.times[0]
            or query.max() > self.times[-1]
        ):
            raise StitchError("Gyro query exceeds recorded attitude coverage")
        indices = np.clip(
            np.searchsorted(self.times, query, side="right") - 1, 0, len(self.times) - 2
        )
        start, end = self.times[indices], self.times[indices + 1]
        if start.min() < self.raw_times[0] or end.max() > self.raw_times[-1]:
            raise StitchError("Raw gyro does not cover the requested attitude intervals")
        local = self.integrate(start, query)
        missing = np.unique(indices[np.isnan(self.anchor_errors[indices, 0])])
        if len(missing):
            complete = self.integrate(self.times[missing], self.times[missing + 1])
            desired = self.poses[missing].inv() * self.poses[missing + 1]
            self.anchor_errors[missing] = (complete.inv() * desired).as_rotvec()
        amount = (query - start) / (end - start)
        return (
            self.poses[indices]
            * local
            * Rotation.from_rotvec(self.anchor_errors[indices] * amount[:, None])
        )


def trajectory(reader, profile_path, anchor_seconds=0.1):
    profile = validate(load_json(profile_path), reader.metadata())
    times, poses = orientation37(reader)
    rt, values = raw_gyro(reader)
    if (
        isinstance(anchor_seconds, bool)
        or not np.isfinite(anchor_seconds)
        or not 0.02 <= anchor_seconds <= 1
    ):
        raise StitchError("Gyro anchor interval must be 0.02 to 1 second")
    if np.max(np.diff(times)) > 0.050001:
        raise StitchError("Recorded attitude contains gaps")
    if anchor_seconds > 0.02:
        anchor_times = np.arange(times[0], times[-1], anchor_seconds)
        anchor_times = np.r_[anchor_times, times[-1]]
        poses = Slerp(times, poses)(anchor_times)
        times = anchor_times
    return AnchoredGyro(times, poses, rt, values, profile), profile
