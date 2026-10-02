"""Independent V6 ray diagnostics; deliberately absent from sphere rendering.

Read-only inspection of Studio 6.0.5 identifies a unified projection with five
radial terms, four tangential terms and four prism terms. The implementation
below derives the polynomial and inverse independently. No vendor code/runtime
or per-unit constants are included. Native motion/seam qualification is pending.
"""

import numpy as np

from .errors import StitchError


def distort(points, coefficients, jacobian=False):
    """Apply the observed 13-slot polynomial in normalized lens coordinates."""
    q = np.asarray(points, dtype=np.float64)
    c = np.asarray(coefficients, dtype=np.float64)
    if q.ndim != 2 or q.shape[1] != 2 or c.shape != (13,):
        raise StitchError("V6 distortion requires N by 2 points and 13 coefficients")
    if not np.isfinite(q).all() or not np.isfinite(c).all():
        raise StitchError("Non-finite V6 distortion input")
    # Bound untrusted metadata/numerical inputs before high polynomial powers.
    if np.any(np.abs(q) > 100) or np.any(np.abs(c) > 1e6):
        raise StitchError("V6 distortion inputs exceed diagnostic numerical bounds")
    x, y = q.T
    r = x * x + y * y
    radial = 1 + sum(c[i] * r ** (i + 1) for i in range(5))
    a, b = c[5] + c[7] * r, c[6] + c[8] * r
    px, py = c[9] * r + c[11] * r * r, c[10] * r + c[12] * r * r
    result = np.column_stack(
        [
            x * radial + a * (r + 2 * x * x) + 2 * b * x * y + px,
            y * radial + b * (r + 2 * y * y) + 2 * a * x * y + py,
        ]
    )
    if not jacobian:
        return result
    slope = sum((i + 1) * c[i] * r**i for i in range(5))
    prism_x, prism_y = c[9] + 2 * c[11] * r, c[10] + 2 * c[12] * r
    xx = (
        radial
        + 2 * x * x * slope
        + 2 * x * c[7] * (r + 2 * x * x)
        + 6 * x * a
        + 4 * x * x * y * c[8]
        + 2 * y * b
        + 2 * x * prism_x
    )
    xy = (
        2 * x * y * slope
        + 2 * y * c[7] * (r + 2 * x * x)
        + 2 * y * a
        + 4 * x * y * y * c[8]
        + 2 * x * b
        + 2 * y * prism_x
    )
    yx = (
        2 * x * y * slope
        + 2 * x * c[8] * (r + 2 * y * y)
        + 2 * x * b
        + 4 * x * x * y * c[7]
        + 2 * y * a
        + 2 * x * prism_y
    )
    yy = (
        radial
        + 2 * y * y * slope
        + 2 * y * c[8] * (r + 2 * y * y)
        + 6 * y * b
        + 4 * x * y * y * c[7]
        + 2 * x * a
        + 2 * y * prism_y
    )
    return result, np.stack([xx, xy, yx, yy], axis=1).reshape(-1, 2, 2)


def undistort(points, coefficients):
    """Damped Newton inversion, retaining a validity mask for failed/folded rays."""
    target = np.asarray(points, dtype=np.float64)
    q = target.copy()
    # Validation also covers an empty input without special-casing its shape.
    distort(q, coefficients)
    for _ in range(40):
        value, derivative = distort(q, coefficients, jacobian=True)
        residual = value - target
        determinant = np.linalg.det(derivative)
        stable = determinant > 1e-12
        step = np.zeros_like(q)
        if np.any(stable):
            step[stable] = np.linalg.solve(derivative[stable], residual[stable, :, None])[:, :, 0]
        step = np.clip(step, -0.2, 0.2)
        error = np.sum(residual * residual, axis=1)
        for divisor in (1, 2, 4, 8, 16, 32):
            candidate = q - step / divisor
            trial = distort(candidate, coefficients) - target
            improved = stable & (np.sum(trial * trial, axis=1) < error)
            q[improved] = candidate[improved]
            stable[improved] = False
        if not len(error) or np.max(error) < 1e-24:
            break
    value, derivative = distort(q, coefficients, jacobian=True)
    valid = (np.linalg.norm(value - target, axis=1) < 1e-10) & (np.linalg.det(derivative) > 1e-12)
    return q, valid


def diagnostic_lens(parameters, index):
    """Observed bare/square V6 crop mapping; never a rendering profile."""
    if type(index) is not int or index not in (0, 1):
        raise StitchError("V6 ray diagnostics require lens 0 or 1")
    if parameters["guard_detected_value"] != 3:
        raise StitchError("V6 ray diagnostics currently require explicit guards OFF")
    if parameters["offset_v6"] != parameters["original_offset_v6"]:
        raise StitchError("V6 ray diagnostics do not interpret edited lens parameters")
    lens = parameters["offset_v6"]["lenses"][index]
    height = lens["sensor_height"]
    crop = parameters["window_crop_info"]
    width = parameters["capture"]["width"]
    if (
        not crop
        or set(crop) != {"src_width", "src_height", "dst_width", "dst_height"}
        or crop["src_width"] != crop["src_height"]
        or crop["src_width"] != height
        or crop["dst_width"] != crop["dst_height"]
        or any(type(v) is not int for v in crop.values())
        or not 32 <= width <= crop["dst_width"] <= height
        or (height - crop["dst_width"]) % 2
    ):
        raise StitchError("V6 ray diagnostics require the observed centered square crop")
    intrinsics = lens["sensor_intrinsics"]
    center = np.array([intrinsics["cx"] - index * height, intrinsics["cy"]])
    # OffsetConvert removes a centered crop; GeometryWrapper resizes endpoints.
    scale = (width - 1) / (crop["dst_width"] - 1)
    center = (center - (height - crop["dst_width"]) / 2) * scale
    focal = np.array([intrinsics["fx"], intrinsics["fy"]]) * scale
    return dict(
        xi=lens["xi"],
        center=center,
        focal=focal,
        distortion=np.asarray(lens["distortion_slots"]),
        width=width,
    )


def unproject(points, lens):
    """Decode-pixel centers to near-branch unit rays in one lens's coordinates."""
    points = np.asarray(points, dtype=np.float64)
    if points.ndim != 2 or points.shape[1] != 2 or not np.isfinite(points).all():
        raise StitchError("V6 pixels must be finite N by 2 coordinates")
    covered = np.all((points >= 0) & (points <= lens["width"] - 1), axis=1)
    rays = np.zeros((len(points), 3))
    valid = np.zeros(len(points), dtype=bool)
    if not np.any(covered):
        return rays, valid
    xy, solved = undistort((points[covered] - lens["center"]) / lens["focal"], lens["distortion"])
    r = np.sum(xy * xy, axis=1)
    xi = lens["xi"]
    discriminant = 1 + (1 - xi * xi) * r
    valid[covered] = solved & (discriminant > 1e-12)
    scale = (xi + np.sqrt(np.maximum(0, discriminant))) / (1 + r)
    rays[covered] = np.column_stack([xy * scale[:, None], scale - xi])
    rays[~valid] = 0
    return rays, valid


def project(rays, lens):
    """Lens-coordinate rays to decoded pixel centers, with explicit validity."""
    rays = np.asarray(rays, dtype=np.float64)
    if rays.ndim != 2 or rays.shape[1] != 3 or not np.isfinite(rays).all():
        raise StitchError("V6 rays must be finite N by 3 coordinates")
    # Normalize through the largest component to avoid overflow or underflow.
    magnitude = np.max(np.abs(rays), axis=1)
    if np.any(magnitude == 0):
        raise StitchError("V6 rays must be nonzero")
    direction = rays / magnitude[:, None]
    direction /= np.linalg.norm(direction, axis=1)[:, None]
    xi = lens["xi"]
    xy = direction[:, :2] / (direction[:, 2, None] + xi)
    value, derivative = distort(xy, lens["distortion"], jacobian=True)
    pixels = value * lens["focal"] + lens["center"]
    valid = (
        (direction[:, 2] > -1 / xi)
        & (np.linalg.det(derivative) > 1e-12)
        & np.all((pixels >= 0) & (pixels <= lens["width"] - 1), axis=1)
    )
    return pixels, valid


def ray_diagnostic(parameters, lens_index, ray):
    lens = diagnostic_lens(parameters, lens_index)
    pixels, valid = project(np.asarray(ray, dtype=float).reshape(1, 3), lens)
    if not valid[0]:
        raise StitchError("Ray has no in-bounds, unfolded near-branch V6 pixel")
    report = pixel_diagnostic(parameters, lens_index, pixels[0].tolist())
    # A positive local Jacobian alone cannot exclude another distant solution.
    direction = np.asarray(ray, dtype=float) / np.max(np.abs(ray))
    direction /= np.linalg.norm(direction)
    if not np.allclose(report["unit_ray"], direction, rtol=0, atol=1e-8):
        raise StitchError("V6 projected ray does not match the diagnostic inverse")
    report["operation"] = "lens ray to decoded pixel"
    return report


def pixel_diagnostic(parameters, lens_index, pixel):
    lens = diagnostic_lens(parameters, lens_index)
    rays, valid = unproject(np.asarray(pixel, dtype=float).reshape(1, 2), lens)
    if not valid[0]:
        raise StitchError("Pixel has no converged, in-bounds near-branch V6 ray")
    return dict(
        lens=lens_index,
        decoded_pixel=list(pixel),
        unit_ray=rays[0].tolist(),
        coordinate_system="lens x right, y down, z through lens; no extrinsic or gyro transform",
        model="unified-xi / radial5-tangential4-prism4",
        crop_convention="centered sensor crop followed by endpoint resize",
        applied_to_renderer=False,
        qualification="Experimental recorded-parameter ray diagnostic; native motion/seams and image timing unqualified",
    )
