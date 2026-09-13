"""Experimental A1 lens geometry. No vendor-quality or stabilization claim.

Reads per-lens MEI parameters from the actual file, rather than X5 constants.
Coordinate convention: lens/image x right, y down, z out through the lens.
"""

import cv2
import numpy as np
from scipy.spatial.transform import Rotation

from .errors import StitchError
from .process import binary, run


def lenses_from_metadata(metadata, width):
    offsets = metadata["offset_v3"]
    if not np.isfinite(offsets).all() or width < 32:
        raise StitchError("Invalid lens calibration or decode width")
    if len(offsets) != 40 or offsets[0] != 2:
        raise ValueError("Only the observed two-lens 40-value A1 calibration is implemented")
    lenses = []
    for index in range(2):
        part = offsets[1 + 19 * index : 20 + 19 * index]
        xi, fx, fy, cx, cy = part[:5]
        sensor_width, sensor_height = part[16:18]
        if not sensor_width > 0 or not sensor_height > 0 or xi <= 1 or fx <= 0 or fy <= 0:
            raise StitchError("Unsupported lens geometry")
        sensor_width /= 2
        if sensor_width != sensor_height:
            raise StitchError("Only square A1 sensors are supported")
        if index:
            cx -= sensor_width
        sx, sy = width / sensor_width, width / sensor_height
        lenses.append(
            dict(
                xi=xi,
                K=np.array([[fx * sx, 0, cx * sx], [0, fy * sy, cy * sy], [0, 0, 1.0]]),
                distortion=np.array([part[11], part[12], part[14], part[15], part[13]]),
                extrinsics_degrees=part[5:8],
                translation=part[8:11],
                width=width,
                lens_type=part[18],
            )
        )
    return lenses


def decode_frame(source, seconds, stream=0, width=1440, height=None):
    height = height or width
    raw = run(
        [
            binary("ffmpeg"),
            "-v",
            "error",
            "-ss",
            str(seconds),
            "-i",
            str(source),
            "-map",
            f"0:v:{stream}",
            "-frames:v",
            "1",
            "-vf",
            f"scale={width}:{height}",
            "-pix_fmt",
            "bgr24",
            "-f",
            "rawvideo",
            "-",
        ]
    )
    if len(raw) != width * height * 3:
        raise ValueError("Incomplete decoded frame")
    return np.frombuffer(raw, np.uint8).reshape(height, width, 3)


def unproject(points, lens):
    # Remove Brown-Conrady distortion, then invert the unified sphere projection.
    points = np.asarray(points, np.float64).reshape(-1, 1, 2)
    criteria = (cv2.TERM_CRITERIA_COUNT | cv2.TERM_CRITERIA_EPS, 40, 1e-12)
    if hasattr(cv2, "undistortPointsIter"):
        xy = cv2.undistortPointsIter(points, lens["K"], lens["distortion"], None, None, criteria)
    else:  # OpenCV 5 consolidated the iterative overload into undistortPoints.
        xy = cv2.undistortPoints(points, lens["K"], lens["distortion"], criteria=criteria)
    xy = xy.reshape(-1, 2)
    r2 = (xy * xy).sum(axis=1)
    xi = lens["xi"]
    valid = 1 + (1 - xi * xi) * r2 >= 0
    lam = (xi + np.sqrt(np.maximum(0, 1 + (1 - xi * xi) * r2))) / (r2 + 1)
    rays = np.column_stack([xy[:, 0] * lam, xy[:, 1] * lam, lam - xi])
    rays /= np.linalg.norm(rays, axis=1)[:, None]
    return rays, valid


def project(rays, lens):
    shape = rays.shape[:-1]
    rays = rays.reshape(-1, 3)
    rays = rays / np.linalg.norm(rays, axis=1)[:, None]
    den = rays[:, 2] + lens["xi"]
    x, y = rays[:, 0] / den, rays[:, 1] / den
    r2 = x * x + y * y
    k1, k2, p1, p2, k3 = np.asarray(lens["distortion"], dtype=rays.dtype)
    radial = 1 + k1 * r2 + k2 * r2 * r2 + k3 * r2 * r2 * r2
    xd = x * radial + 2 * p1 * x * y + p2 * (r2 + 2 * x * x)
    yd = y * radial + p1 * (r2 + 2 * y * y) + 2 * p2 * x * y
    u = float(lens["K"][0, 0]) * xd + float(lens["K"][0, 2])
    v = float(lens["K"][1, 1]) * yd + float(lens["K"][1, 2])
    # Avoid the non-injective far branch of the xi>1 model.
    valid = (
        (rays[:, 2] > -1 / lens["xi"])
        & (den > 0)
        & (u >= 0)
        & (v >= 0)
        & (u < lens["width"] - 1)
        & (v < lens["width"] - 1)
    )
    return (
        u.reshape(shape).astype(np.float32),
        v.reshape(shape).astype(np.float32),
        valid.reshape(shape),
    )


def project_scan(rays, lens, angular_velocity=None, readout_seconds=0, row_quaternions=None):
    """Invert native top-to-bottom sensor timing with two row-map updates.

    Velocity is expressed in this lens's coordinates. The native sensor row,
    not the equirectangular output row, determines when a pixel was captured.
    """
    u, v, valid = project(rays, lens)
    if row_quaternions is not None and readout_seconds:
        from .motion import rotate_rows

        for _ in range(2):
            corrected = rotate_rows(rays, v / (lens["width"] - 1), row_quaternions)
            u, v, valid = project(corrected, lens)
        return u, v, valid
    if angular_velocity is None or readout_seconds == 0:
        return u, v, valid
    velocity = np.asarray(angular_velocity, np.float32)
    speed = float(np.linalg.norm(velocity))
    if speed < 1e-8:
        return u, v, valid
    axis = velocity / speed
    cross = np.cross(axis, rays)
    axial = np.sum(rays * axis, axis=-1)[..., None] * axis
    for _ in range(2):
        dt = (np.clip(v / (lens["width"] - 1), 0, 1) - 0.5) * readout_seconds
        angle = -speed * dt
        cosine, sine = np.cos(angle)[..., None], np.sin(angle)[..., None]
        corrected = rays * cosine + cross * sine + axial * (1 - cosine)
        u, v, valid = project(corrected, lens)
    return u, v, valid


def sample_pixels(frame, u, v):
    """Sample a compact list without exceeding OpenCV's remap dimension limit."""
    count = u.size
    if not count:
        return np.empty((0, 3), frame.dtype)
    columns = min(count, 4096)
    padding = (-count) % columns
    maps = [np.pad(m.ravel(), (0, padding)).reshape(-1, columns) for m in (u, v)]
    return cv2.remap(frame, *maps, cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE).reshape(-1, 3)[
        :count
    ]


def rotation_fit(source, target):
    # target = R @ source, row-vector implementation below.
    u, _, vh = np.linalg.svd(source.T @ target)
    correction = np.eye(3)
    correction[2, 2] = np.linalg.det(vh.T @ u.T)
    return vh.T @ correction @ u.T


def robust_rotation(source, target, degrees=1, iterations=3000):
    if len(source) < 6:
        raise ValueError("Insufficient ray correspondences")
    if (
        not np.isfinite(source).all()
        or not np.isfinite(target).all()
        or source.shape != target.shape
    ):
        raise StitchError("Invalid ray correspondences")
    rng = np.random.default_rng(20260912)
    best = np.zeros(len(source), bool)
    for _ in range(iterations):
        indices = rng.choice(len(source), 3, replace=False)
        rotation = rotation_fit(source[indices], target[indices])
        errors = np.arccos(np.clip(np.sum((source @ rotation.T) * target, axis=1), -1, 1))
        inliers = errors < np.radians(degrees)
        if inliers.sum() > best.sum():
            best = inliers
    if best.sum() < 6:
        raise ValueError("No consistent spherical rotation")
    rotation = rotation_fit(source[best], target[best])
    errors = np.degrees(np.arccos(np.clip(np.sum((source @ rotation.T) * target, axis=1), -1, 1)))
    return rotation, best, errors


def match_lenses(frame0, frame1, lenses):
    sift = cv2.SIFT_create(nfeatures=12000, contrastThreshold=0.025, edgeThreshold=12)
    k0, d0 = sift.detectAndCompute(frame0, None)
    k1, d1 = sift.detectAndCompute(frame1, None)
    if d0 is None or d1 is None or len(d0) < 2 or len(d1) < 2:
        raise StitchError("Insufficient texture to match lens overlap")
    pairs = cv2.BFMatcher().knnMatch(d1, d0, k=2)
    matches = [
        pair[0] for pair in pairs if len(pair) == 2 and pair[0].distance < 0.72 * pair[1].distance
    ]
    if len(matches) < 12:
        raise StitchError("Insufficient lens overlap matches; choose another reference frame")
    p0 = np.array([k0[m.trainIdx].pt for m in matches])
    p1 = np.array([k1[m.queryIdx].pt for m in matches])
    r0, v0 = unproject(p0, lenses[0])
    r1, v1 = unproject(p1, lenses[1])
    valid = v0 & v1
    rotation, inliers, errors = robust_rotation(r1[valid], r0[valid], degrees=1.5)
    return rotation, dict(
        matches=len(matches),
        valid=int(valid.sum()),
        inliers=int(inliers.sum()),
        median_error_degrees=float(np.median(errors[inliers])),
        p95_error_degrees=float(np.percentile(errors[inliers], 95)),
        rotation_lens1_to_lens0=rotation.tolist(),
    )


def sphere_rays(width):
    height = width // 2
    lon = ((np.arange(width) + 0.5) / width - 0.5) * 2 * np.pi
    lat = ((np.arange(height) + 0.5) / height - 0.5) * np.pi
    lon, lat = np.meshgrid(lon, lat)
    return np.stack(
        [np.sin(lon) * np.cos(lat), np.sin(lat), np.cos(lon) * np.cos(lat)], axis=-1
    ).astype(np.float32)


def blend_sphere(frames, lenses, lens1_to_lens0, world_to_lens0, width=2048):
    rays = sphere_rays(width) @ world_to_lens0.T
    result = np.zeros((width // 2, width, 3), np.float32)
    total = np.zeros((width // 2, width), np.float32)
    for i in range(2):
        local = rays if i == 0 else rays @ lens1_to_lens0
        u, v, valid = project(local, lenses[i])
        # Dominance depends on angle to the optical axis, not output longitude.
        weight = np.clip((local[:, :, 2] + 0.1) / 0.2, 0, 1) * valid
        warped = cv2.remap(
            frames[i], u, v, cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE
        ).astype(np.float32)
        result += warped * weight[:, :, None]
        total += weight
    covered = total > 1e-5
    result[covered] /= total[covered, None]
    return np.clip(result, 0, 255).astype(np.uint8), float(1 - covered.mean())


def orientation37(reader):
    data = reader.payload(37)
    if not data or len(data) % 36:
        raise ValueError("Unexpected orientation record size")
    dtype = np.dtype([("t", "<u8"), ("q", "<f4", (4,)), ("unknown", "<f4", (3,))])
    records = np.frombuffer(data, dtype=dtype)
    times = (records["t"].astype(np.float64) - reader.metadata()["first_frame_timestamp_us"]) / 1e6
    norms = np.linalg.norm(records["q"], axis=1)
    if (
        not np.all(np.diff(times) > 0)
        or not np.all(np.isfinite(norms))
        or np.max(np.abs(norms - 1)) > 0.001
    ):
        raise ValueError("Invalid candidate orientation data")
    return times, Rotation.from_quat(records["q"])


class TiledStitcher:
    """Bound memory use by projecting strips; retain the full sphere in one pass."""

    def __init__(
        self,
        lenses,
        relative,
        width,
        strip_height=64,
        seam="feather",
        fps=30,
        readout_seconds=0,
        occlusion=None,
    ):
        if width < 64 or width > 16384 or width % 4 or strip_height < 1:
            raise StitchError("Sphere width must be a multiple of 4 between 64 and 16384")
        self.lenses = lenses
        self.relative = np.asarray(relative, np.float32)
        self.width = width
        self.height = width // 2
        self.strip_height = strip_height
        if not np.isfinite(readout_seconds) or not 0 <= readout_seconds <= 0.1:
            raise StitchError("Invalid sensor readout duration")
        self.readout_seconds = readout_seconds
        self.visibility = None
        if occlusion is not None:
            from .occlusion import VisibilityMasks

            self.visibility = VisibilityMasks(occlusion, lenses)
        if seam not in ["feather", "flow", "adaptive", "multiband"]:
            raise StitchError("Seam must be flow, adaptive or feather")
        self.seam = None
        if seam in ["flow", "adaptive", "multiband"]:
            from .seam import OverlapSeam

            self.seam = OverlapSeam(
                lenses,
                self.relative,
                width,
                fps,
                adaptive=seam == "adaptive",
                multiband=seam == "multiband",
            )
        longitude = ((np.arange(width, dtype=np.float32) + 0.5) / width - 0.5) * (2 * np.pi)
        self.sinlon, self.coslon = np.sin(longitude), np.cos(longitude)

    def stitch(self, frames, world_to_lens, angular_velocity=None, row_quaternions=None):
        if len(frames) != 2 or frames[0].dtype not in (np.uint8, np.uint16):
            raise StitchError("Expected two uint8 or uint16 lens images")
        if any(
            frame.shape != (lens["width"], lens["width"], 3) or frame.dtype != frames[0].dtype
            for frame, lens in zip(frames, self.lenses)
        ):
            raise StitchError("Lens image shape or precision differs from the calibration")
        dtype = frames[0].dtype
        maximum = np.iinfo(dtype).max
        rotation = np.asarray(world_to_lens, np.float32)
        if angular_velocity is not None:
            angular_velocity = np.asarray(angular_velocity, np.float32)
            if angular_velocity.shape != (3,) or not np.isfinite(angular_velocity).all():
                raise StitchError("Angular velocity must be a finite three-vector")
        from .motion import validate_rows

        rows = validate_rows(row_quaternions)
        if self.visibility is not None:
            self.visibility.prepare(frames)
        if self.seam is not None:
            self.seam.prepare(frames, angular_velocity, self.readout_seconds, rows, self.visibility)
        output = np.empty((self.height, self.width, 3), dtype)
        missing = 0
        for top in range(0, self.height, self.strip_height):
            bottom = min(top + self.strip_height, self.height)
            latitude = (
                (np.arange(top, bottom, dtype=np.float32) + 0.5) / self.height - 0.5
            ) * np.pi
            shape = (bottom - top, self.width)
            rays = np.empty((*shape, 3), np.float32)
            rays[:, :, 0] = self.sinlon * np.cos(latitude)[:, None]
            rays[:, :, 1] = np.sin(latitude)[:, None]
            rays[:, :, 2] = self.coslon * np.cos(latitude)[:, None]
            rays = rays @ rotation.T
            result = np.zeros((*shape, 3), np.float32)
            total = np.zeros(shape, np.float32)
            if self.seam is not None:
                corrected, alpha, gains = self.seam.sample(rays)
            if self.visibility is not None:
                from .occlusion import visible_weights

                maps, preferred, eligibility = [], [], []
                for i, lens in enumerate(self.lenses):
                    basis = rays if self.seam is None else corrected[i]
                    local = basis if i == 0 else basis @ self.relative
                    velocity = angular_velocity
                    if i and velocity is not None:
                        velocity = np.asarray(velocity) @ self.relative
                    u, v, valid = project_scan(
                        local,
                        lens,
                        velocity,
                        self.readout_seconds,
                        None if rows is None else rows[i],
                    )
                    maps.append((u, v))
                    preferred.append(
                        np.clip((local[..., 2] + 0.1) / 0.2, 0, 1)
                        if self.seam is None
                        else (alpha if i == 0 else 1 - alpha)
                    )
                    eligibility.append(valid * self.visibility.sample(i, u, v))
                quality = np.array(
                    [self.visibility.sample_quality(i, u, v) for i, (u, v) in enumerate(maps)]
                )
                weights = visible_weights(np.array(preferred), np.array(eligibility), quality)
                for i, (u, v) in enumerate(maps):
                    warped = sample_pixels(frames[i], u, v).reshape(*shape, 3)
                    if self.seam is not None:
                        warped = warped * gains[i]
                    result += warped * weights[i, ..., None]
                total = weights.sum(axis=0)
                if np.any(total <= 1e-5):
                    raise StitchError(
                        "Visibility masks leave pixels unavailable in both lenses; no detail was invented"
                    )
                result /= total[..., None]
                if self.seam is not None and self.seam.multiband:
                    result += maximum * self.seam.multiband_correction(rays)
                output[top:bottom] = np.rint(np.clip(result, 0, maximum)).astype(dtype)
                continue
            for i, lens in enumerate(self.lenses):
                basis = rays if self.seam is None else corrected[i]
                local = basis if i == 0 else basis @ self.relative
                velocity = angular_velocity
                if i == 1 and velocity is not None:
                    velocity = np.asarray(velocity) @ self.relative
                weight = (
                    np.clip((local[..., 2] + 0.1) / 0.2, 0, 1)
                    if self.seam is None
                    else (alpha if i == 0 else 1 - alpha)
                )
                # An unused hemisphere cannot contribute to this output pixel.
                # Do not perform its expensive row-map iterations or interpolation.
                active = weight > 0
                if not active.any():
                    continue
                u, v, valid = project_scan(
                    local[active],
                    lens,
                    velocity,
                    self.readout_seconds,
                    None if rows is None else rows[i],
                )
                weight = weight[active] * valid
                warped = sample_pixels(frames[i], u, v)
                if self.seam is not None:
                    warped = warped * gains[i][active]
                result[active] += warped * weight[:, None]
                total[active] += weight
            covered = total > 1e-5
            missing += int((~covered).sum())
            result /= np.maximum(total[:, :, None], 1e-5)
            if self.seam is not None and self.seam.multiband:
                result += maximum * self.seam.multiband_correction(rays)
            result = np.clip(result, 0, maximum)
            output[top:bottom] = (np.rint(result) if dtype == np.uint16 else result).astype(dtype)
        return output, missing / (self.width * self.height)
