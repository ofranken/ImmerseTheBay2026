import cv2
import numpy as np

from app.services.matching import crop_target, haversine_m, match


def _artwork(seed: int, size=(400, 300)) -> np.ndarray:
    rng = np.random.default_rng(seed)
    w, h = size
    img = np.full((h, w, 3), 240, np.uint8)
    for _ in range(120):
        c = tuple(int(v) for v in rng.integers(0, 255, 3))
        p = tuple(int(v) for v in (rng.integers(0, w), rng.integers(0, h)))
        if rng.random() < 0.5:
            cv2.circle(img, p, int(rng.integers(5, 40)), c, -1)
        else:
            q = tuple(int(v) for v in (rng.integers(0, w), rng.integers(0, h)))
            cv2.line(img, p, q, c, int(rng.integers(1, 6)))
    return img


def _gallery_photo(art: np.ndarray) -> np.ndarray:
    """The artwork hung on a wall, seen at an angle from a different distance."""
    wall = np.full((720, 960, 3), (180, 175, 170), np.uint8)
    noise = np.random.default_rng(5).integers(-10, 10, wall.shape)
    wall = np.clip(wall.astype(int) + noise, 0, 255).astype(np.uint8)
    h, w = art.shape[:2]
    src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    dst = np.float32([[300, 180], [700, 220], [690, 560], [310, 600]])
    M = cv2.getPerspectiveTransform(src, dst)
    warped = cv2.warpPerspective(art, M, (960, 720))
    mask = cv2.warpPerspective(np.ones((h, w), np.uint8), M, (960, 720)).astype(bool)
    wall[mask] = warped[mask]
    return wall


def test_finds_the_same_artwork():
    art = _artwork(1)
    creator_photo = np.full((600, 800, 3), 200, np.uint8)
    creator_photo[150:450, 200:600] = art
    target = crop_target(creator_photo, [200, 150, 400, 300])
    r = match(_gallery_photo(art), target)
    assert r.matched, r


def test_rejects_a_different_artwork():
    r = match(_gallery_photo(_artwork(2)), _artwork(1))
    assert not r.matched, r


def test_haversine():
    # Two points ~111 m apart (0.001 deg latitude)
    assert 105 < haversine_m(38.9404, -92.3277, 38.9414, -92.3277) < 117
