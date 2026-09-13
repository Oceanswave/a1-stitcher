"""Camera-bound native visibility masks; replacement uses the other real lens."""

import cv2
import numpy as np

from .calibration import lens_fingerprint
from .errors import StitchError
from .storage import load_json

MASK_SIZE = 512


def template(metadata):
    guard = metadata.get("propeller_guard_status")
    if (
        metadata.get("camera_type") != "Antigravity A1"
        or type(guard) is not int
        or guard not in range(4)
    ):
        raise StitchError(
            "Visibility profiles require A1 identity and known propeller-guard metadata"
        )
    return dict(
        schema_version=1,
        kind="a1-native-visibility-v1",
        lens_fingerprint=lens_fingerprint(metadata),
        propeller_guard_status=metadata["propeller_guard_status"],
        feather_pixels=3,
        lenses=[dict(max_angle_degrees=None, exclude_polygons=[]) for _ in range(2)],
    )


def validate(profile, metadata=None):
    try:
        if (
            type(profile.get("schema_version")) is not int
            or profile.get("schema_version") != 1
            or profile.get("kind") != "a1-native-visibility-v1"
        ):
            raise ValueError("unsupported schema")
        fingerprint = profile["lens_fingerprint"]
        if len(fingerprint) != 64 or any(c not in "0123456789abcdef" for c in fingerprint):
            raise ValueError("invalid lens fingerprint")
        guard = profile["propeller_guard_status"]
        if type(guard) is not int or guard not in range(4):
            raise ValueError("unknown propeller-guard configuration")
        feather = profile["feather_pixels"]
        if (
            isinstance(feather, bool)
            or not isinstance(feather, (int, float))
            or not np.isfinite(feather)
            or not 1 <= feather <= 16
        ):
            raise ValueError("feather_pixels must be 1 to 16 at the 512-pixel mask resolution")
        lenses = profile["lenses"]
        if not isinstance(lenses, list) or len(lenses) != 2:
            raise ValueError("two lens masks required")
        configured = False
        for lens in lenses:
            angle = lens["max_angle_degrees"]
            if angle is not None:
                if (
                    isinstance(angle, bool)
                    or not isinstance(angle, (int, float))
                    or not np.isfinite(angle)
                    or not 85 <= angle <= 110
                ):
                    raise ValueError("maximum lens angle must be 85 to 110 degrees")
                configured = True
            polygons = lens["exclude_polygons"]
            if not isinstance(polygons, list) or len(polygons) > 64:
                raise ValueError("too many exclusion polygons")
            for polygon in polygons:
                vertices = np.asarray(polygon, float)
                if (
                    vertices.ndim != 2
                    or vertices.shape[1] != 2
                    or not 3 <= len(vertices) <= 128
                    or not np.isfinite(vertices).all()
                    or np.any((vertices < 0) | (vertices > 1))
                ):
                    raise ValueError(
                        "polygon vertices must be normalized native-image x/y coordinates"
                    )
                if abs(cv2.contourArea(vertices.astype(np.float32))) < 1e-6:
                    raise ValueError("exclusion polygon has no area")
                configured = True
        if not configured:
            raise ValueError("empty template; supply lens angle limits or exclusion polygons")
        if metadata is not None:
            if (
                metadata.get("camera_type") != "Antigravity A1"
                or lens_fingerprint(metadata) != fingerprint
            ):
                raise ValueError("profile belongs to another camera's lens parameters")
            if metadata.get("propeller_guard_status") != guard:
                raise ValueError(
                    "source propeller-guard configuration differs from the mask profile"
                )
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise StitchError(f"Invalid visibility profile: {exc}") from exc
    return profile


def load_profile(path, metadata):
    return validate(load_json(path), metadata)


class VisibilityMasks:
    def __init__(self, profile, lenses):
        from .projection import unproject

        validate(profile)
        self.maps = []
        for description, lens in zip(profile["lenses"], lenses):
            keep = np.ones((MASK_SIZE, MASK_SIZE), np.uint8)
            limit = description["max_angle_degrees"]
            if limit is not None:
                x, y = np.meshgrid(
                    np.linspace(0, lens["width"] - 1, MASK_SIZE),
                    np.linspace(0, lens["width"] - 1, MASK_SIZE),
                )
                rays, valid = unproject(np.column_stack([x.ravel(), y.ravel()]), lens)
                allowed = valid & (rays[:, 2] >= np.cos(np.radians(limit)))
                keep = allowed.reshape(keep.shape).astype(np.uint8)
            for polygon in description["exclude_polygons"]:
                points = np.rint(np.array(polygon) * (MASK_SIZE - 1)).astype(np.int32)
                cv2.fillPoly(keep, [points], 0)
            distance = cv2.distanceTransform(keep, cv2.DIST_L2, cv2.DIST_MASK_PRECISE)
            amount = np.clip(distance / profile["feather_pixels"], 0, 1)
            self.maps.append((amount * amount * (3 - 2 * amount)).astype(np.float32))
        self.lenses = lenses

    def sample(self, index, u, v):
        scale = (MASK_SIZE - 1) / (self.lenses[index]["width"] - 1)
        shape = u.shape
        # remap accepts row maps too, while projection callers can use flat rays.
        return cv2.remap(
            self.maps[index],
            (u * scale).astype(np.float32).reshape(-1, shape[-1]),
            (v * scale).astype(np.float32).reshape(-1, shape[-1]),
            cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_REPLICATE,
        ).reshape(shape)


def visible_weights(preferred, eligibility):
    weights = preferred * eligibility
    fallback = weights.sum(axis=0) <= 1e-5
    weights[:, fallback] = eligibility[:, fallback]
    return weights


def preview(source, profile_path, frame, output_dir):
    """Show exclusion overlays on a bounded native-view sample, without stitching."""
    from fractions import Fraction
    from pathlib import Path

    from .insv import InsvReader
    from .media import source_profile
    from .projection import decode_frame, lenses_from_metadata
    from .storage import identity, write_new_json

    source = Path(source).resolve(strict=True)
    metadata = InsvReader(source).metadata()
    profile = load_profile(profile_path, metadata)
    video = source_profile(source, metadata)
    if isinstance(frame, bool) or not isinstance(frame, int) or not 0 <= frame < video["frames"]:
        raise StitchError("Preview frame is outside the source video")
    width = min(1024, video["width"])
    masks = VisibilityMasks(profile, lenses_from_metadata(metadata, width))
    before = identity(source)
    output = Path(output_dir).absolute()
    output.mkdir(parents=True, exist_ok=False)
    x, y = np.meshgrid(np.arange(width, dtype=np.float32), np.arange(width, dtype=np.float32))
    files = []
    for index in range(2):
        image = decode_frame(
            source, frame / float(Fraction(video["fps"])), stream=index, width=width
        )
        amount = (1 - masks.sample(index, x, y))[..., None] * 0.65
        overlay = np.rint(image * (1 - amount) + np.array([0, 0, 255]) * amount).astype(np.uint8)
        for name, pixels in [("source", image), ("mask", overlay)]:
            path = output / f"lens-{index}-{name}.png"
            good, encoded = cv2.imencode(".png", pixels)
            if not good:
                raise StitchError("Could not encode visibility preview")
            with path.open("xb") as stream:
                stream.write(encoded.tobytes())
            files.append(str(path))
    if identity(source) != before:
        raise StitchError("Source changed during visibility preview")
    result = dict(
        status="previewed",
        source=str(source),
        source_identity=before,
        source_frame=frame,
        profile=profile,
        images=files,
        scope="Red overlay marks excluded native pixels; one sampled frame, not motion acceptance",
    )
    write_new_json(output / "preview.json", result)
    return result
