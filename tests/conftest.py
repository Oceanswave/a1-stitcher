"""Synthetic fixtures only: no recorded footage or camera-specific metadata."""

import json
import shutil
import struct
import subprocess

import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from a1_stitcher.calibration import lens_fingerprint
from a1_stitcher.insv import MAGIC
from a1_stitcher.projection import lenses_from_metadata, unproject


def varint(value):
    result = bytearray()
    while value > 127:
        result.append((value & 127) | 128)
        value >>= 7
    return bytes(result) + bytes([value])


def pb(number, value):
    if isinstance(value, int):
        return varint(number << 3) + varint(value)
    if isinstance(value, str):
        value = value.encode()
    return varint(number << 3 | 2) + varint(len(value)) + value


def trailer(records, version=3, headers=False):
    body = bytearray()
    index = []
    for kind, payload in records:
        encoding = 1 if kind == 1 else 0
        index.append((kind, encoding, len(payload), len(body)))
        body.extend(payload)
        if headers:
            body.extend(struct.pack("<BBI", encoding, kind, len(payload)))
    table = b"".join(struct.pack("<BBII", *entry) for entry in index)
    body.extend(table)
    body.extend(struct.pack("<BBI", 0, 0, len(table)))
    body.extend(bytes(32) + struct.pack("<II", len(body) + 72, version) + MAGIC)
    return body


def metadata(width=128):
    def lens(i):
        return [
            1.5,
            0.71 * width,
            0.71 * width,
            (i + 0.5) * width,
            0.5 * width,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            width * 2,
            width,
            155,
        ]

    return dict(
        camera_type="Antigravity A1",
        offset_v3=[2, *lens(0), *lens(1), 0],
        dimension=dict(x=width, y=width),
        first_frame_timestamp_us=10_000_000,
    )


def scene(rays):
    x, y, z = rays.T
    lon = np.arctan2(x, z)
    lat = np.arcsin(np.clip(y, -1, 1))
    return np.clip(
        np.column_stack(
            [
                128 + 85 * np.sin(lon * 4),
                128 + 85 * np.cos(lat * 7),
                128 + 85 * np.sin(lon * 3 + lat * 5),
            ]
        ),
        0,
        255,
    ).astype(np.uint8)


def pose_at(t):
    return Rotation.from_euler(
        "xyz", [15 * np.sin(t * 6), 12 * np.sin(t * 9), t * 35], degrees=True
    )


@pytest.fixture(scope="session")
def synthetic_camera(tmp_path_factory):
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg or not shutil.which("ffprobe"):
        pytest.skip("FFmpeg integration prerequisites are unavailable")
    encoders = subprocess.check_output(
        [ffmpeg, "-hide_banner", "-encoders"], stderr=subprocess.DEVNULL
    )
    if b"libx265" not in encoders or b"libx264" not in encoders:
        pytest.skip("Synthetic fixture requires libx265 and libx264 encoders")
    root = tmp_path_factory.mktemp("synthetic-camera")
    width, count, fps = 128, 8, 10
    meta = metadata(width)
    lenses = lenses_from_metadata(meta, width)
    relative = Rotation.from_euler("y", 180, degrees=True).as_matrix()
    mount = Rotation.from_euler("z", -90, degrees=True)
    world = Rotation.from_matrix([[0, 1, 0], [0, 0, 1], [1, 0, 0]])
    xx, yy = np.meshgrid(np.arange(width), np.arange(width))
    points = np.column_stack([xx.ravel(), yy.ravel()])
    raw_files = []
    for index in range(2):
        path = root / f"lens-{index}.raw"
        raw_files.append(path)
        rays, valid = unproject(points, lenses[index])
        if index:
            rays = rays @ relative.T
        with path.open("wb") as stream:
            for frame in range(count):
                rotated = (world * pose_at(frame / fps) * mount).apply(rays)
                pixels = scene(rotated)
                pixels[~valid] = 0
                stream.write(pixels.reshape(width, width, 3).tobytes())
    source = root / "synthetic.insv"
    args = [ffmpeg, "-v", "error", "-n"]
    for path in raw_files:
        args += [
            "-f",
            "rawvideo",
            "-pix_fmt",
            "bgr24",
            "-video_size",
            f"{width}x{width}",
            "-r",
            str(fps),
            "-i",
            str(path),
        ]
    filters = ";".join(
        f"[{i}:v]scale=out_color_matrix=bt709:out_range=pc,format=yuv420p[v{i}]" for i in range(2)
    )
    args += [
        "-filter_complex",
        filters,
        "-map",
        "[v0]",
        "-map",
        "[v1]",
        "-c:v",
        "libx265",
        "-x265-params",
        "pools=1:frame-threads=1:log-level=error:lossless=1:colorprim=bt709:transfer=bt709:colormatrix=bt709:range=full",
        "-threads",
        "1",
        "-color_range",
        "pc",
        "-colorspace",
        "bt709",
        "-color_trc",
        "bt709",
        "-color_primaries",
        "bt709",
        "-f",
        "mp4",
        str(source),
    ]
    subprocess.run(args, check=True, capture_output=True, timeout=60)
    times = np.arange(0, 1.01, 0.02)
    attitudes = b"".join(
        struct.pack("<Q7f", 10_000_000 + round(t * 1e6), *pose_at(t).as_quat(), 0, 0, 0)
        for t in times
    )
    record = b"".join(
        [
            pb(2, meta["camera_type"]),
            pb(19, pb(1, width) + pb(2, width)),
            pb(20, fps),
            pb(24, meta["first_frame_timestamp_us"]),
            pb(54, "_".join(map(str, meta["offset_v3"]))),
        ]
    )
    with source.open("ab") as stream:
        stream.write(trailer([(1, record), (37, attitudes)]))
    calibration = dict(
        schema_version=1,
        camera_type=meta["camera_type"],
        lens_fingerprint=lens_fingerprint(meta),
        lens_mount=mount.as_matrix().tolist(),
        rotation_lens1_to_lens0=relative.tolist(),
        inverse=False,
        time_shift_seconds=0,
        quality_status="synthetic test data",
    )
    profile = root / "synthetic-calibration.json"
    profile.write_text(json.dumps(calibration))
    return dict(root=root, source=source, calibration=profile, metadata=meta, fps=fps, frames=count)
