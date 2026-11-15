"""Tap-to-cut selection logic (pure numpy: no GPU, no SAM)."""
import numpy as np

from app.services.segmentation import MaskCandidate, choose_whole_object


def cand(mask, quality=0.9):
    ys, xs = np.nonzero(mask)
    box = (int(xs.min()), int(ys.min()), int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1))
    return MaskCandidate(mask=mask, quality=quality, bbox=box, area=int(mask.sum()), rank_score=quality)


def rect(h, w, y0, y1, x0, x1):
    m = np.zeros((h, w), bool)
    m[y0:y1, x0:x1] = True
    return m


H, W = 100, 100
HANDLE = cand(rect(H, W, 40, 50, 40, 50))            # what SAM's point mask picked: a small part
CUP = cand(rect(H, W, 20, 80, 20, 80), 0.8)           # the whole object, contains the part and the tap
TAP = (45, 45)


def test_swaps_a_part_for_the_whole_object():
    assert choose_whole_object(HANDLE, [CUP], *TAP) is CUP


def test_keeps_the_point_mask_when_there_is_no_whole_object():
    assert choose_whole_object(HANDLE, [], *TAP) is HANDLE


def test_ignores_masks_that_do_not_contain_the_tap():
    elsewhere = cand(rect(H, W, 0, 30, 70, 100))
    assert choose_whole_object(HANDLE, [elsewhere], *TAP) is HANDLE


def test_ignores_masks_that_do_not_swallow_the_part():
    beside = cand(rect(H, W, 30, 60, 44, 90))  # contains the tap but covers only half of the part
    assert choose_whole_object(HANDLE, [beside], *TAP) is HANDLE


def test_never_picks_the_whole_picture():
    everything = cand(np.ones((H, W), bool))
    assert choose_whole_object(HANDLE, [everything], *TAP) is HANDLE


def test_never_picks_something_smaller():
    tiny = cand(rect(H, W, 44, 47, 44, 47))
    assert choose_whole_object(HANDLE, [tiny], *TAP) is HANDLE


def test_picks_the_most_confident_whole_object():
    other = cand(rect(H, W, 10, 90, 10, 90), 0.95)
    assert choose_whole_object(HANDLE, [CUP, other], *TAP) is other


def test_tap_outside_the_image_is_safe():
    assert choose_whole_object(HANDLE, [CUP], -5, 500) is HANDLE
