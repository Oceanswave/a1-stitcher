import itertools

import numpy as np
import pytest

from a1_stitcher.adaptive import AdaptivePath, closed_path
from a1_stitcher.errors import StitchError


def test_closed_path_matches_exhaustive_search():
    rng = np.random.default_rng(51)
    cost = rng.uniform(0, 4, (3, 7)).astype(np.float32)
    path = closed_path(cost, step_penalty=0.13)

    def score(p):
        return sum(cost[y, x] for x, y in enumerate(p)) + 0.13 * np.abs(np.diff(p)).sum()

    possible = [
        p
        for p in itertools.product(range(3), repeat=7)
        if p[0] == p[-1] and np.max(np.abs(np.diff(p))) <= 1
    ]
    assert score(path) == pytest.approx(min(map(score, possible)), abs=1e-5)


def test_closed_seam_avoids_mismatched_object_and_joins_longitude():
    cost = np.zeros((32, 512), np.float32)
    cost[10:22, 210:300] = 20
    cost += np.abs(np.arange(32)[:, None] - 16) * 0.01
    path = closed_path(cost)
    assert cost[path, np.arange(512)].mean() < cost[16].mean() / 10
    assert path[0] == path[-1]
    assert np.max(np.abs(np.diff(path))) <= 1


@pytest.mark.parametrize("cost", [np.zeros(4), np.zeros((65, 10)), np.full((4, 10), np.nan)])
def test_invalid_cost_grids_rejected(cost):
    with pytest.raises(StitchError, match="cost"):
        closed_path(cost)


def test_path_motion_is_bounded_when_disagreement_moves():
    path = AdaptivePath(30)
    first = np.full((64, 512, 3), 100, np.float32)
    second = first.copy()
    valid = np.ones((64, 512), bool)
    confidence = np.ones_like(valid, np.float32)
    previous = path.update(first, second, valid, confidence, np.radians(8))
    second[30:44] = 240
    current = path.update(first, second, valid, confidence, np.radians(8))
    assert np.max(np.abs(current - previous)) <= np.radians(6 / 30) + 1e-7
    assert np.max(np.abs(current)) <= np.radians(4)
    assert abs(current[0, 0] - current[0, -1]) < np.radians(0.1)


def test_unsupported_belt_does_not_choose_an_arbitrary_edge():
    path = AdaptivePath(30)
    frame = np.full((64, 512, 3), 100, np.float32)
    value = path.update(frame, frame, np.zeros((64, 512), bool), np.zeros((64, 512)), np.radians(8))
    assert np.array_equal(value, np.zeros((1, 512)))
