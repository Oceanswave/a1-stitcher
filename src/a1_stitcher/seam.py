"""Conservative overlap alignment and local color balancing.

Estimate correspondence in a camera-fixed equatorial belt, then modify the lens
sampling coordinates. Final pixels still come directly from the original lenses;
the low-resolution belt is never pasted into the output sphere.
"""

import cv2
import numpy as np

from .projection import project, project_scan


def smoothstep(value):
    value = np.clip(value, 0, 1)
    return value * value * (3 - 2 * value)


def periodic_sample(array, x, y):
    """Wrap longitude only; latitude must never wrap into the opposite edge."""
    padded = np.concatenate([array[:, -1:], array, array[:, :1]], axis=1)
    return cv2.remap(
        padded,
        (np.mod(x, array.shape[1]) + 1).astype(np.float32),
        np.clip(y, 0, array.shape[0] - 1).astype(np.float32),
        cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_REPLICATE,
    )


def matched_flow(first, second, valid, angular_pixel):
    """Bidirectional flow with correspondence, texture and displacement checks."""
    height, width = valid.shape
    gray = [cv2.cvtColor(f, cv2.COLOR_BGR2GRAY) for f in (first, second)]
    clahe = cv2.createCLAHE(clipLimit=2, tileGridSize=(max(4, width // 64), 4))
    gray = [clahe.apply(g) for g in gray]
    pad = min(64, width // 8)
    padded = [np.pad(g, ((0, 0), (pad, pad)), mode="wrap") for g in gray]
    flows = []
    for i in range(2):
        estimator = cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_MEDIUM)
        estimator.setFinestScale(0)
        # The overlap is already calibrated. Do not search distant image regions.
        if hasattr(estimator, "setCoarsestScale"):
            estimator.setCoarsestScale(2)
        initial = np.zeros((*padded[i].shape, 2), np.float32)
        flows.append(estimator.calc(padded[i], padded[1 - i], initial)[:, pad:-pad].copy())
    x, y = np.meshgrid(np.arange(width, dtype=np.float32), np.arange(height, dtype=np.float32))
    confidence = []
    finite = [np.isfinite(flow).all(axis=2) for flow in flows]
    for flow, good in zip(flows, finite):
        flow[~good] = 0
    for i, flow in enumerate(flows):
        destination = (x + flow[:, :, 0], y + flow[:, :, 1])
        reverse = periodic_sample(flows[1 - i], *destination)
        error = np.linalg.norm(flow + reverse, axis=2)
        magnitude = np.linalg.norm(flow * angular_pixel, axis=2)
        gx = cv2.Sobel(gray[i], cv2.CV_32F, 1, 0, ksize=3) / 8
        gy = cv2.Sobel(gray[i], cv2.CV_32F, 0, 1, ksize=3) / 8
        texture = cv2.GaussianBlur(gx * gx + gy * gy, (0, 0), 2)
        supported = (
            valid
            & finite[i]
            & (periodic_sample(valid.astype(np.float32), *destination) > 0.99)
            & (destination[1] >= 2)
            & (destination[1] < height - 3)
            & (magnitude < np.radians(2))
        )
        trust = smoothstep((1.5 - error) / 1.0) * smoothstep((texture - 1) / 12)
        trust *= supported
        # Soft support avoids abrupt warping boundaries; invalid vectors stay zero.
        trust = cv2.GaussianBlur(trust.astype(np.float32), (0, 0), 1) * supported
        confidence.append(trust)
    return flows, confidence


def color_ratio(first, second, valid, sectors=32):
    """Bounded robust log ratios; sparse, clipped and black sectors abstain."""
    height, width = valid.shape
    values = np.zeros((sectors, 3), np.float32)
    support = np.zeros(sectors, np.float32)
    for index, columns in enumerate(np.array_split(np.arange(width), sectors)):
        a, b = first[:, columns].astype(np.float32), second[:, columns].astype(np.float32)
        good = valid[:, columns] & ((a > 16) & (b > 16) & (a < 239) & (b < 239)).all(2)
        if good.sum() < max(16, height * len(columns) // 10):
            continue
        values[index] = np.clip(np.median(np.log(b[good] / a[good]), axis=0), -np.log(2), np.log(2))
        support[index] = 1
    if support.sum() < sectors // 4:
        return np.zeros((1, width, 3), np.float32), False
    # Never infer a color correction across a large unmeasured arc (e.g. clear
    # sky). Interpolating between distant supported sectors can paint false color
    # into a lens that was already clean. A single missing sector may bridge.
    centers = (np.arange(sectors) + 0.5) * width / sectors - 0.5
    good = support > 0
    interpolated = np.stack(
        [
            np.interp(np.arange(width), centers[good], values[good, c], period=width)
            for c in range(3)
        ],
        axis=1,
    )[None].astype(np.float32)
    supported_sectors = good | (np.roll(good, 1) & np.roll(good, -1))
    local_support = np.interp(
        np.arange(width), centers, supported_sectors.astype(float), period=width
    )[None, :, None]
    interpolated *= local_support
    radius = max(4, width // sectors)
    padded = np.pad(interpolated, ((0, 0), (radius * 3, radius * 3), (0, 0)), mode="wrap")
    smoothed = cv2.GaussianBlur(padded, (0, 0), radius, sigmaY=0)
    return smoothed[:, radius * 3 : -radius * 3], True


class OverlapSeam:
    """One stateful seam estimator per contiguous conversion job."""

    def __init__(self, lenses, relative, output_width, fps=30, adaptive=False, multiband=False):
        self.lenses = lenses
        self.width = max(512, min(2048, output_width // 2))
        self.height = max(64, round(self.width * 16 / 360))
        self.extent = np.radians(8)
        self.pixel = np.array([2 * np.pi / self.width, 2 * self.extent / self.height], np.float32)
        self.relative = np.asarray(relative, np.float32)
        self.fps = fps
        self.multiband = multiband
        self.correction = None
        self.path = None
        if adaptive:
            from .adaptive import AdaptivePath

            self.path = AdaptivePath(fps)
        self.path_latitude = None
        azimuth, latitude = np.meshgrid(
            (np.arange(self.width) + 0.5) * self.pixel[0] - np.pi,
            (np.arange(self.height) + 0.5) * self.pixel[1] - self.extent,
        )
        self.rays = self.directions(azimuth, latitude)
        self.maps = [
            project(self.rays if i == 0 else self.rays @ self.relative, lens)
            for i, lens in enumerate(lenses)
        ]
        self.valid = self.maps[0][2] & self.maps[1][2]
        self.log_ratio = None
        self.frames = 0
        self.measured_frames = 0
        self.totals = dict(confident_fraction=0.0, residual_before=0.0, residual_after=0.0)

    @staticmethod
    def directions(azimuth, latitude):
        return np.stack(
            [
                np.cos(azimuth) * np.cos(latitude),
                np.sin(azimuth) * np.cos(latitude),
                np.sin(latitude),
            ],
            axis=-1,
        ).astype(np.float32)

    def prepare(
        self,
        frames,
        angular_velocity=None,
        readout_seconds=0,
        row_quaternions=None,
        visibility=None,
    ):
        native = frames
        # Flow/CLAHE analyze 8-bit proxies; final remapping retains the original
        # 16-bit signal when a finishing encode is requested.
        if frames[0].dtype == np.uint16:
            frames = [np.rint(frame.astype(np.float32) / 257).astype(np.uint8) for frame in frames]
        maps = self.maps
        if (angular_velocity is not None or row_quaternions is not None) and readout_seconds:
            maps = [
                project_scan(
                    self.rays if i == 0 else self.rays @ self.relative,
                    lens,
                    angular_velocity
                    if i == 0 or angular_velocity is None
                    else np.asarray(angular_velocity) @ self.relative,
                    readout_seconds,
                    None if row_quaternions is None else row_quaternions[i],
                )
                for i, lens in enumerate(self.lenses)
            ]
        valid = maps[0][2] & maps[1][2]
        if visibility is not None:
            for i, (u, v, _) in enumerate(maps):
                valid &= visibility.sample(i, u, v) >= 0.999
        bands = [cv2.remap(frame, u, v, cv2.INTER_CUBIC) for frame, (u, v, _) in zip(frames, maps)]
        self.flows, self.confidence = matched_flow(*bands, valid, self.pixel)
        x, y = np.meshgrid(
            np.arange(self.width, dtype=np.float32), np.arange(self.height, dtype=np.float32)
        )
        flow = self.flows[0]
        aligned = periodic_sample(bands[1], x + flow[:, :, 0], y + flow[:, :, 1])
        middle = np.abs(y - (self.height - 1) / 2) < self.height / 4
        trusted = (self.confidence[0] > 0.5) & valid & middle
        ratio, supported = color_ratio(bands[0], aligned, trusted)
        if supported:
            if self.log_ratio is None:
                self.log_ratio = ratio
            else:
                amount = 1 - np.exp(-1 / (self.fps * 0.25))
                delta = amount * (ratio - self.log_ratio)
                self.log_ratio += np.clip(delta, -0.01, 0.01) if self.multiband else delta
        elif self.log_ratio is not None:
            # Do not hold a previous scene's balance through unsupported footage.
            self.log_ratio *= np.exp(-1 / (self.fps * 0.25))
        self.frames += 1
        if self.multiband:
            # Three frequency bands: native high-frequency detail keeps the narrow
            # seam. Two lower-frequency differences use wider angular transitions.
            # Never average pixels across time, which would trail moving objects.
            signals = [
                cv2.remap(f, u, v, cv2.INTER_CUBIC).astype(np.float32) / np.iinfo(f.dtype).max
                for f, (u, v, _) in zip(native, maps)
            ]
            signals[1] = periodic_sample(signals[1], x + flow[..., 0], y + flow[..., 1])
            balance = self.log_ratio if self.log_ratio is not None else ratio
            latitude = (y + 0.5) * self.pixel[1] - self.extent
            taper = 1 - smoothstep(np.abs(latitude) / self.extent)
            corrected = [
                s * np.exp(np.minimum(sign * balance, 0) * taper[..., None])
                for s, sign in zip(signals, [1, -1])
            ]
            support = valid & (self.confidence[0] > 0.2)
            support &= (
                (signals[0] > 0.02)
                & (signals[0] < 0.98)
                & (signals[1] > 0.02)
                & (signals[1] < 0.98)
            ).all(2)
            support &= np.max(np.abs(corrected[0] - corrected[1]), axis=2) < 0.2
            difference = corrected[0] - corrected[1]
            alphas = [smoothstep((latitude / np.radians(d) + 1) / 2) for d in [1.2, 2.4, 4.8]]
            correction = np.zeros_like(difference)
            for k, sigma in enumerate([1.2, 3.5]):
                # Pad only longitude periodically; latitude uses edge replication.
                pad = int(np.ceil(sigma * 4))

                def blur(value):
                    padded = np.pad(
                        value, ((0, 0), (pad, pad)) + ((0, 0),) * (value.ndim - 2), mode="wrap"
                    )
                    return cv2.GaussianBlur(padded, (0, 0), sigma, borderType=cv2.BORDER_REPLICATE)[
                        :, pad:-pad
                    ]

                weight = blur(support.astype(np.float32))
                low = blur(difference * support[..., None]) / np.maximum(weight[..., None], 1e-5)
                correction += (
                    (alphas[k + 1] - alphas[k])[..., None] * low * (weight > 0.9)[..., None]
                )
            self.correction = (np.clip(correction, -0.1, 0.1) * support[..., None]).astype(
                np.float32
            )
        if self.path is not None:
            balance = self.log_ratio if self.log_ratio is not None else ratio
            gain0, gain1 = np.exp(np.minimum(balance, 0)), np.exp(np.minimum(-balance, 0))
            self.path_latitude = self.path.update(
                bands[0] * gain0, aligned * gain1, valid, self.confidence[0], self.extent
            )
        self.totals["confident_fraction"] += float(trusted.sum() / max(1, middle.sum()))
        if trusted.any():
            self.measured_frames += 1
            balance = self.log_ratio if self.log_ratio is not None else ratio
            gain0, gain1 = np.exp(np.minimum(balance, 0)), np.exp(np.minimum(-balance, 0))
            before = np.abs(bands[0].astype(np.float32) - bands[1])
            after = np.abs(bands[0] * gain0 - aligned * gain1)
            self.totals["residual_before"] += float(before[trusted].mean())
            self.totals["residual_after"] += float(after[trusted].mean())

    def sample(self, rays):
        azimuth = np.arctan2(rays[:, :, 1], rays[:, :, 0])
        latitude = np.arcsin(np.clip(rays[:, :, 2], -1, 1))
        x = (azimuth + np.pi) / self.pixel[0] - 0.5
        y = (latitude + self.extent) / self.pixel[1] - 0.5
        # A narrow detail transition reduces double images when flow must abstain.
        offset = 0
        if self.path_latitude is not None:
            px = (azimuth + np.pi) / (2 * np.pi) * self.path_latitude.shape[1] - 0.5
            offset = periodic_sample(self.path_latitude, px, np.zeros_like(px))
        alpha = smoothstep(((latitude - offset) / np.radians(1.2) + 1) / 2)
        active = np.abs(latitude - offset) < np.radians(1.2)
        directions = []
        for i in range(2):
            if not active.any():
                directions.append(rays)
                continue
            flow = periodic_sample(self.flows[i], x, y)
            trust = periodic_sample(self.confidence[i], x, y) * active
            amount = (1 - alpha if i == 0 else alpha) * trust
            directions.append(
                self.directions(
                    azimuth - flow[:, :, 0] * self.pixel[0] * amount,
                    latitude - flow[:, :, 1] * self.pixel[1] * amount,
                )
            )
            directions[-1][~active] = rays[~active]
        if self.log_ratio is None:
            gains = [np.ones((*alpha.shape, 3), np.float32)] * 2
        else:
            balance = periodic_sample(self.log_ratio, x, np.zeros_like(x))
            # Measurement spans only this overlap belt. Extrapolating its color
            # into the wider sphere created dark arcs in otherwise clean sky.
            taper = 1 - smoothstep(np.abs(latitude) / self.extent)
            # Prefer the lower signal in each channel. Brightening the hazier
            # lens's partner would spread veiling glare into otherwise clean detail.
            gains = [np.exp(np.minimum(sign * balance, 0) * taper[:, :, None]) for sign in [1, -1]]
        return directions, alpha, gains

    def multiband_correction(self, rays):
        if self.correction is None:
            return np.zeros_like(rays)
        azimuth = np.arctan2(rays[..., 1], rays[..., 0])
        latitude = np.arcsin(np.clip(rays[..., 2], -1, 1))
        x = (azimuth + np.pi) / self.pixel[0] - 0.5
        y = (latitude + self.extent) / self.pixel[1] - 0.5
        return periodic_sample(self.correction, x, y) * (np.abs(latitude) < self.extent)[..., None]

    def report(self):
        return {
            key: (
                value / max(self.frames, 1)
                if key == "confident_fraction"
                else value / self.measured_frames
                if self.measured_frames
                else None
            )
            for key, value in self.totals.items()
        } | {
            "frames": self.frames,
            "measured_frames": self.measured_frames,
            "flow_analysis_width": self.width,
            "multiband": self.multiband,
            "adaptive_path": self.path.report() if self.path is not None else None,
            "diagnostic_scope": "trusted central overlap pixels; not a whole-image quality score",
        }
