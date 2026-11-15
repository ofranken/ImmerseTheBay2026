"""Tap-to-cut: how should we pick among SAM's multimask outputs? Scores every strategy on the same taps.

    python -m tests.tapcut_study            # needs the GPU (stop the API first) and the COCO test photos

Reports hit rate (IoU >= 0.5) and mean IoU per strategy, separately for the dev split (what we tune on) and the
holdout split (what we validate on). The tap is the pixel deepest inside the ground-truth object, a stand-in for a user.
"""
from __future__ import annotations

import json
import statistics

import cv2
import numpy as np
import torch
from PIL import Image

from app.config import get_settings
from app.services.segmentation import get_segmenter, refine_mask, resize_for_model, upscale_mask
from tests.sam_eval import gt_mask, interior_point, iou, load_manifest


def strategies():
    def argmax_score(ms, sc):  # what the app did
        return int(np.argmax(sc))

    def largest_within(frac):
        def pick(ms, sc):
            ok = [i for i in range(len(sc)) if sc[i] >= frac * max(sc)]
            return max(ok, key=lambda i: ms[i].sum())
        return pick

    def largest_above(abs_min):
        def pick(ms, sc):
            ok = [i for i in range(len(sc)) if sc[i] >= abs_min]
            return max(ok, key=lambda i: ms[i].sum()) if ok else int(np.argmax(sc))
        return pick

    def whole_not_image(frac, cap=0.85):
        def pick(ms, sc):
            area = [m.mean() for m in ms]
            ok = [i for i in range(len(sc)) if sc[i] >= frac * max(sc) and area[i] <= cap]
            return max(ok, key=lambda i: ms[i].sum()) if ok else int(np.argmax(sc))
        return pick

    out = {"argmax_score (before)": argmax_score}
    for f in (0.6, 0.7, 0.8, 0.9):
        out[f"largest_within_{f}"] = largest_within(f)
    for a in (0.5, 0.6, 0.7):
        out[f"largest_score>={a}"] = largest_above(a)
    for f in (0.6, 0.7, 0.8):
        out[f"largest_within_{f}_notimage"] = whole_not_image(f)
    return out


def concept_strategies():
    """Strategies that also see SAM 3's whole-object concept masks (the same candidates 'scrapbook that' uses)."""
    def contains(c, x, y):
        return bool(c.mask[y, x])

    def point_argmax(P, sc, C, x, y):
        return P[int(np.argmax(sc))]

    def best_containing(P, sc, C, x, y):  # most confident concept mask under the tap, else the point mask
        inside = [c for c in C if contains(c, x, y)]
        return max(inside, key=lambda c: c.quality).mask if inside else P[int(np.argmax(sc))]

    def largest_containing(cap):
        def pick(P, sc, C, x, y):
            inside = [c for c in C if contains(c, x, y) and c.mask.mean() <= cap]
            return max(inside, key=lambda c: c.mask.sum()).mask if inside else P[int(np.argmax(sc))]
        return pick

    def hybrid(overlap):
        """Use a concept mask only if it swallows (most of) the point mask: i.e. the tap hit a part of that object."""
        def pick(P, sc, C, x, y):
            base = P[int(np.argmax(sc))]
            inside = [c for c in C if contains(c, x, y) and c.mask.sum() > base.sum()
                      and np.logical_and(c.mask, base).sum() / max(base.sum(), 1) >= overlap and c.mask.mean() <= 0.9]
            return max(inside, key=lambda c: c.quality).mask if inside else base
        return pick

    return {
        "argmax_score (before)": point_argmax,
        "concept_best_containing": best_containing,
        "concept_largest_containing_<=0.9": largest_containing(0.9),
        "concept_largest_containing_<=0.6": largest_containing(0.6),
        "hybrid_overlap>=0.5": hybrid(0.5),
        "hybrid_overlap>=0.7": hybrid(0.7),
        "hybrid_overlap>=0.9": hybrid(0.9),
    }


def main_concepts():
    s = get_settings()
    seg = get_segmenter()
    strat = concept_strategies()
    rows = {name: {"dev": [], "holdout": []} for name in strat}
    for item in load_manifest():
        rgb = cv2.cvtColor(cv2.imread(f"tests/data/images/{item['file']}"), cv2.COLOR_BGR2RGB)
        h, w = rgb.shape[:2]
        gt = gt_mask(item)
        small, scale = resize_for_model(rgb, s.sam_max_side)
        px, py = interior_point(gt)
        x, y = int(px * scale), int(py * scale)
        with seg._lock, torch.inference_mode(), seg._autocast():
            seg._predictor.set_image(Image.fromarray(small))
            masks, scores, _ = seg._predictor.predict(point_coords=np.array([[x, y]], dtype=np.float32),
                                                      point_labels=np.array([1], dtype=np.int32), multimask_output=True)
        P = [refine_mask(m > 0) for m in masks]
        sc = [float(v) for v in scores]
        C = seg.auto_masks(small, None)
        for name, pick in strat.items():
            rows[name][item["split"]].append(iou(upscale_mask(pick(P, sc, C, x, y), h, w), gt))
    print(f"{'strategy':36s} {'dev hit':>8s} {'dev iou':>8s} {'hold hit':>9s} {'hold iou':>9s}")
    for name, d in rows.items():
        f = lambda v: (sum(t >= 0.5 for t in v) / len(v), statistics.fmean(v))
        (dh, di), (hh, hi) = f(d["dev"]), f(d["holdout"])
        print(f"{name:36s} {dh:8.3f} {di:8.3f} {hh:9.3f} {hi:9.3f}")


def main():
    s = get_settings()
    seg = get_segmenter()
    strat = strategies()
    rows = {name: {"dev": [], "holdout": []} for name in strat}
    for item in load_manifest():
        bgr = cv2.imread(f"tests/data/images/{item['file']}")
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        h, w = rgb.shape[:2]
        gt = gt_mask(item)
        small, scale = resize_for_model(rgb, s.sam_max_side)
        px, py = interior_point(gt)
        with seg._lock, torch.inference_mode(), seg._autocast():
            seg._predictor.set_image(Image.fromarray(small))
            masks, scores, _ = seg._predictor.predict(
                point_coords=np.array([[px * scale, py * scale]], dtype=np.float32),
                point_labels=np.array([1], dtype=np.int32), multimask_output=True)
        ms = [refine_mask(m > 0) for m in masks]
        sc = [float(x) for x in scores]
        for name, pick in strat.items():
            i = pick(ms, sc)
            rows[name][item["split"]].append(iou(upscale_mask(ms[i], h, w), gt))
    result = {}
    for name, d in rows.items():
        result[name] = {sp: {"n": len(v), "hit50": round(sum(x >= 0.5 for x in v) / len(v), 3), "mean_iou": round(statistics.fmean(v), 3)} for sp, v in d.items()}
    print(f"{'strategy':32s} {'dev hit':>8s} {'dev iou':>8s} {'hold hit':>9s} {'hold iou':>9s}")
    for name, r in result.items():
        print(f"{name:32s} {r['dev']['hit50']:8.3f} {r['dev']['mean_iou']:8.3f} {r['holdout']['hit50']:9.3f} {r['holdout']['mean_iou']:9.3f}")
    print(json.dumps(result))


if __name__ == "__main__":
    import sys
    main_concepts() if "--concepts" in sys.argv else main()
