"""Bounded, periodic seam placement; does not reconstruct occluded pixels."""

import cv2
import numpy as np

from .errors import StitchError


def closed_path(cost, step_penalty=0.08):
    """Minimum cost ring with at most one row of motion per column.

    Keep all possible starting rows in the dynamic program. The last column
    must return to that same row, so the longitude boundary cannot jump.
    """
    cost = np.asarray(cost, np.float32)
    if (
        cost.ndim != 2
        or not 2 <= cost.shape[0] <= 64
        or not 2 <= cost.shape[1] <= 2048
        or not np.isfinite(cost).all()
        or not np.isfinite(step_penalty)
        or step_penalty < 0
    ):
        raise StitchError("Invalid bounded seam cost grid")
    height, width = cost.shape
    rows = np.arange(height)
    scores = np.full((height, height), np.inf, np.float32)
    scores[rows, rows] = cost[:, 0]
    back = np.empty((width, height, height), np.int8)
    for x in range(1, width):
        choices = np.stack(
            [
                np.pad(scores[:, :-1], ((0, 0), (1, 0)), constant_values=np.inf) + step_penalty,
                scores,
                np.pad(scores[:, 1:], ((0, 0), (0, 1)), constant_values=np.inf) + step_penalty,
            ]
        )
        choice = np.argmin(choices, axis=0)
        back[x] = choice.astype(np.int8) - 1
        scores = np.take_along_axis(choices, choice[None], axis=0)[0] + cost[:, x]
    start = int(np.argmin(scores[rows, rows]))
    path = np.empty(width, np.int32)
    path[-1] = start
    for x in range(width - 1, 0, -1):
        path[x - 1] = path[x] + back[x, start, path[x]]
    return path


class AdaptivePath:
    """Conservative seam search within +/-4 degrees, limited to 6 degrees/sec."""

    def __init__(self, fps):
        if not np.isfinite(fps) or fps <= 0:
            raise StitchError("Invalid frame rate for adaptive seam")
        self.fps = fps
        self.latitude = None
        self.frames = 0
        self.before = self.after = self.motion = 0.0

    def update(self, first, second, valid, confidence, extent):
        height, width = valid.shape
        latitude = (np.arange(height) + 0.5) * (2 * extent / height) - extent
        middle = np.flatnonzero(np.abs(latitude) < np.radians(4))
        if not np.all(np.any(valid[middle], axis=0)):
            # No complete supported ring: retain the previous safe path, or the
            # fixed optical seam on the first frame. Never choose a lens edge.
            if self.latitude is None:
                self.latitude = np.zeros(512, np.float32)
            return self.latitude[None]
        # Residual is measured after correspondence and color matching. Prefer
        # agreement, supported correspondence and proximity to the optical seam.
        residual = np.abs(first.astype(np.float32) - second).mean(axis=2) / 32
        cost = residual + 0.25 * (1 - confidence)
        cost += (np.abs(latitude) / np.radians(4))[:, None] * 0.08
        cost[~valid] = 1000
        cost = cv2.resize(cost[middle], (512, 32), interpolation=cv2.INTER_AREA)
        levels = np.linspace(latitude[middle[0]], latitude[middle[-1]], 32)
        if self.latitude is not None:
            previous = cv2.resize(self.latitude[None], (512, 1))[0]
            search = cost + 0.15 * np.abs(levels[:, None] - previous) / np.radians(1)
        else:
            previous = np.zeros(512, np.float32)
            search = cost
        path = closed_path(search)
        target = levels[path].astype(np.float32)
        # Spatial smoothing and a bounded temporal step avoid seam crawling.
        padded = np.pad(target[None], ((0, 0), (12, 12)), mode="wrap")
        target = cv2.GaussianBlur(padded, (0, 0), 3, sigmaY=0)[0, 12:-12]
        if self.latitude is not None:
            limit = np.radians(6) / self.fps
            target = previous + np.clip(target - previous, -limit, limit)
        columns = np.arange(512)
        center = np.argmin(np.abs(levels))
        selected = np.clip(np.rint(np.interp(target, levels, np.arange(32))), 0, 31).astype(int)
        self.before += float(cost[center].mean())
        self.after += float(cost[selected, columns].mean())
        if self.latitude is not None:
            self.motion = max(self.motion, float(np.degrees(np.max(np.abs(target - previous)))))
        self.frames += 1
        self.latitude = target
        return target[None]

    def report(self):
        return dict(
            frames=self.frames,
            mean_fixed_path_cost=self.before / max(self.frames, 1),
            mean_adaptive_path_cost=self.after / max(self.frames, 1),
            max_step_degrees=self.motion,
            scope="overlap selection cost; not a whole-image quality or occlusion-removal score",
        )
