"""Bounded image observations shared by timing fits and moving comparisons."""

import subprocess
import tempfile
from contextlib import contextmanager

import cv2
import numpy as np

from .errors import StitchError
from .process import binary, read_exact, stop


@contextmanager
def video_frames(path, fps, first, count, width, *, height=None, step=1, paired=False):
    """Yield exact CFR frame indices; one decoder, bounded memory and pipe deadlines."""
    if (
        not np.isfinite(fps)
        or fps <= 0
        or any(type(v) is not int for v in [first, count, width, step])
        or first < 0
        or not 1 <= count <= 18000
        or not 64 <= width <= 4096
        or not 1 <= step <= count
    ):
        raise StitchError("Invalid bounded video observation range")
    height = width if height is None else height
    if type(height) is not int or not 32 <= height <= 4096:
        raise StitchError("Invalid observation height")
    select = f"select='not(mod(n,{step}))',scale={width}:{height},format=bgr24"
    command = [
        binary("ffmpeg"),
        "-v",
        "error",
        "-nostdin",
        "-threads",
        "2",
        "-ss",
        f"{first / fps:.12f}",
        "-i",
        str(path),
    ]
    if paired:
        command += [
            "-filter_complex_threads",
            "2",
            "-filter_complex",
            f"[0:v:0]{select}[a];[0:v:1]{select}[b];[a][b]hstack=shortest=1[out]",
            "-map",
            "[out]",
        ]
    else:
        command += ["-map", "0:v:0", "-vf", select]
    total = (count - 1) // step + 1
    command += [
        "-frames:v",
        str(total),
        "-fps_mode",
        "passthrough",
        "-pix_fmt",
        "bgr24",
        "-f",
        "rawvideo",
        "-",
    ]
    with tempfile.TemporaryFile() as errors:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=errors)

        def iterator():
            for offset in range(0, count, step):
                shape = (height, width * (2 if paired else 1), 3)
                pixels = np.frombuffer(read_exact(process.stdout, int(np.prod(shape))), np.uint8)
                image = pixels.reshape(shape)
                yield first + offset, [image[:, :width], image[:, width:]] if paired else image
            if process.wait(timeout=120):
                errors.seek(0)
                raise StitchError(errors.read()[-4000:].decode(errors="replace"))

        try:
            yield iterator()
        finally:
            stop(process)


def tracks(first, second, mask=None, maximum=400):
    """Forward/backward LK; no feature tracks inferred across failed matches."""
    gray = [cv2.cvtColor(f, cv2.COLOR_BGR2GRAY) if f.ndim == 3 else f for f in (first, second)]
    points = cv2.goodFeaturesToTrack(gray[0], maximum, 0.015, 10, mask=mask, blockSize=5)
    if points is None:
        return np.empty((0, 2)), np.empty((0, 2))
    args = dict(
        winSize=(21, 21),
        maxLevel=3,
        criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 0.01),
    )
    moved, good, _ = cv2.calcOpticalFlowPyrLK(*gray, points, None, **args)
    back, reverse, _ = cv2.calcOpticalFlowPyrLK(gray[1], gray[0], moved, None, **args)
    a, b = points[:, 0], moved[:, 0]
    valid = good[:, 0].astype(bool) & reverse[:, 0].astype(bool)
    valid &= np.isfinite(b).all(1) & (np.linalg.norm(back[:, 0] - a, axis=1) < 0.6)
    valid &= (b[:, 0] >= 2) & (b[:, 0] < gray[0].shape[1] - 2)
    valid &= (b[:, 1] >= 2) & (b[:, 1] < gray[0].shape[0] - 2)
    return a[valid], b[valid]


def rigid_rotation(first, second, threshold_degrees=0.6):
    """Robust row-vector rotation a @ R -> b; reject weak/one-direction matches."""
    first, second = np.asarray(first), np.asarray(second)
    if len(first) < 12 or first.shape != second.shape or first.shape[1:] != (3,):
        raise StitchError("Too few spherical tracks")
    if not np.isfinite(first).all() or not np.isfinite(second).all():
        raise StitchError("Nonfinite spherical tracks")

    def solve(a, b):
        u, _, vt = np.linalg.svd(a.T @ b)
        return u @ np.diag([1, 1, np.linalg.det(u @ vt)]) @ vt

    threshold = 2 * np.sin(np.radians(threshold_degrees) / 2)
    rng = np.random.default_rng(0)
    best = np.zeros(len(first), bool)
    for _ in range(80):
        index = rng.choice(len(first), 3, replace=False)
        rotation = solve(first[index], second[index])
        good = np.linalg.norm(first @ rotation - second, axis=1) < threshold
        if good.sum() > best.sum():
            best = good
    if best.sum() < max(12, len(first) * 0.4):
        raise StitchError("No dominant rigid background in spherical tracks")
    if np.linalg.svd(first[best], compute_uv=False)[-1] < 0.05:
        raise StitchError("Spherical tracks have insufficient spatial coverage")
    rotation = solve(first[best], second[best])
    errors = np.degrees(
        2 * np.arcsin(np.clip(np.linalg.norm(first @ rotation - second, axis=1) / 2, 0, 1))
    )
    return rotation, best, errors
