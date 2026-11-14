"""Scavenger-hunt verification: does the friend's glasses photo show the creator's original object?

Artwork is mostly planar and richly textured, so local features + a RANSAC homography are a strong,
explainable check that runs on CPU: SIFT keypoints, Lowe ratio test, then count geometric inliers.
For 3D objects (sculptures) swap in an embedding similarity (DINOv2/CLIP) as a second vote.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import cv2
import numpy as np


@dataclass
class MatchResult:
    inliers: int
    good: int
    inlier_ratio: float
    matched: bool


def _gray(img_bgr: np.ndarray, max_side: int = 1024) -> np.ndarray:
    h, w = img_bgr.shape[:2]
    s = min(1.0, max_side / float(max(h, w)))
    if s < 1.0:
        img_bgr = cv2.resize(img_bgr, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
    return cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)


_sift = None


def _detector():
    global _sift
    if _sift is None:
        _sift = cv2.SIFT_create(nfeatures=3000)
    return _sift


def match(query_bgr: np.ndarray, target_bgr: np.ndarray, min_inliers: int = 25, min_ratio: float = 0.2) -> MatchResult:
    sift = _detector()
    kq, dq = sift.detectAndCompute(_gray(query_bgr), None)
    kt, dt = sift.detectAndCompute(_gray(target_bgr), None)
    if dq is None or dt is None or len(kq) < 8 or len(kt) < 8:
        return MatchResult(0, 0, 0.0, False)

    flann = cv2.FlannBasedMatcher({"algorithm": 1, "trees": 5}, {"checks": 64})
    pairs = flann.knnMatch(dt, dq, k=2)
    good = [p[0] for p in pairs if len(p) == 2 and p[0].distance < 0.75 * p[1].distance]
    if len(good) < 8:
        return MatchResult(0, len(good), 0.0, False)

    src = np.float32([kt[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
    dst = np.float32([kq[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
    H, inlier_mask = cv2.findHomography(src, dst, cv2.RANSAC, 5.0)
    if H is None or inlier_mask is None:
        return MatchResult(0, len(good), 0.0, False)

    # Reject degenerate warps (collapsed or mirrored target).
    det = float(H[0, 0] * H[1, 1] - H[0, 1] * H[1, 0])
    inliers = int(inlier_mask.sum())
    ratio = inliers / float(len(good))
    sane = 0.01 < det < 100.0
    return MatchResult(inliers, len(good), ratio, sane and inliers >= min_inliers and ratio >= min_ratio)


def crop_target(original_bgr: np.ndarray, bbox: list[int] | tuple[int, ...], pad_frac: float = 0.1) -> np.ndarray:
    """Region of the creator's original photo that holds the sticker object, with some context."""
    h, w = original_bgr.shape[:2]
    x, y, bw, bh = bbox
    px, py = int(bw * pad_frac), int(bh * pad_frac)
    x0, y0 = max(0, x - px), max(0, y - py)
    x1, y1 = min(w, x + bw + px), min(h, y + bh + py)
    return original_bgr[y0:y1, x0:x1]


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))
