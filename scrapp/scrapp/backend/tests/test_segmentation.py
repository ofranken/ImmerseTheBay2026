import cv2
import numpy as np

from app.services.segmentation import (
    GrabCutSegmenter,
    candidate_from_mask,
    make_sticker,
    rank_candidates,
)


def _disc(h, w, cx, cy, r):
    yy, xx = np.mgrid[:h, :w]
    return (xx - cx) ** 2 + (yy - cy) ** 2 <= r * r


def test_hero_is_the_central_object():
    h, w = 480, 640
    center = candidate_from_mask(_disc(h, w, 320, 240, 60), 0.9)
    corner = candidate_from_mask(_disc(h, w, 90, 90, 70), 0.95)
    wall = candidate_from_mask(np.ones((h, w), bool), 0.99)  # touches every border -> background
    part = candidate_from_mask(_disc(h, w, 320, 240, 20), 0.9)  # inside the central object
    ranked = rank_candidates([corner, wall, part, center], h, w, k=4)
    assert ranked[0] is center
    assert wall not in ranked
    assert part not in ranked  # contained in the hero -> deduped
    assert corner in ranked


def test_sticker_has_white_outline_and_transparent_background():
    h, w = 300, 300
    img = np.zeros((h, w, 3), np.uint8)
    img[:] = (30, 90, 160)
    mask = _disc(h, w, 150, 150, 50)
    img[mask] = (200, 40, 40)
    png, box = make_sticker(img, mask)
    rgba = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_UNCHANGED)
    assert rgba.shape[2] == 4
    assert rgba[0, 0, 3] == 0  # corner transparent
    ch, cw = rgba.shape[:2]
    assert rgba[ch // 2, cw // 2, 3] == 255  # object opaque
    # Walk right from the centre: object -> white outline -> transparent
    row = rgba[ch // 2]
    last_solid = max(i for i in range(cw // 2, cw) if row[i, 3] > 200)
    outline_px = row[last_solid]
    assert outline_px[:3].min() > 200  # outermost solid ring is white
    assert box[2] > 100 and box[3] > 100


def test_grabcut_fallback_finds_center_object():
    h, w = 240, 320
    rng = np.random.default_rng(0)
    img = rng.integers(0, 60, (h, w, 3), dtype=np.uint8)
    obj = _disc(h, w, 160, 120, 45)
    img[obj] = (230, 200, 30)
    c = GrabCutSegmenter().auto_masks(img)[0]
    iou = np.logical_and(c.mask, obj).sum() / np.logical_or(c.mask, obj).sum()
    assert iou > 0.7


def test_named_object_touching_the_frame_is_not_background():
    h, w = 480, 640
    c = candidate_from_mask(np.ones((h, w), bool), 0.9)  # fills the frame, touches every border
    assert rank_candidates([c], h, w, k=2) == []  # unnamed: dropped as background
    assert rank_candidates([c], h, w, k=2, named=True) == [c]  # "scrap that <noun>": kept
