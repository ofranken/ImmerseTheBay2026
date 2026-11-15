"""Score the segmenter on real photos with ground-truth masks (COCO 2017 val, see data/manifest.json).

Three modes mirror how the product uses SAM:
  text     "scrap that <noun>": prompt with the noun; hero = rank_candidates()[0]
  generic  "scrap that": no noun; success if any of the ranked stickers matches the object
  point    tap-to-cut: one positive click inside the object

Everything runs at the pipeline's working resolution (SAM_MAX_SIDE) and is scored at full resolution.

    python -m tests.sam_eval [--split dev|holdout] [--json results.json] [--overlays DIR]
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path

import cv2
import numpy as np
from pycocotools import mask as mask_util

from app.config import get_settings
from app.services.segmentation import (
    get_segmenter,
    rank_candidates,
    resize_for_model,
    upscale_mask,
)

DATA = Path(__file__).parent / "data"


def load_manifest(split: str | None = None) -> list[dict]:
    """split: "dev" (settings were tuned on these), "holdout" (never used for tuning), or None for both."""
    items = json.loads((DATA / "manifest.json").read_text())["images"]
    return [i for i in items if split is None or i.get("split") == split]


def gt_mask(item: dict) -> np.ndarray:
    h, w = item["height"], item["width"]
    rles = mask_util.frPyObjects(item["gt_polygons"], h, w)
    return mask_util.decode(mask_util.merge(rles)).astype(bool)


def iou(a: np.ndarray, b: np.ndarray) -> float:
    union = np.logical_or(a, b).sum()
    return float(np.logical_and(a, b).sum() / union) if union else 0.0


def interior_point(gt: np.ndarray) -> tuple[int, int]:
    """The pixel deepest inside the object, a fair stand-in for a user's tap."""
    dist = cv2.distanceTransform(gt.astype(np.uint8), cv2.DIST_L2, 5)
    y, x = np.unravel_index(int(np.argmax(dist)), dist.shape)
    return int(x), int(y)


def evaluate_one(item: dict, seg=None) -> dict:
    seg = seg or get_segmenter()
    s = get_settings()
    bgr = cv2.imread(str(DATA / "images" / item["file"]))
    if bgr is None:
        raise FileNotFoundError(f"{item['file']} missing: run python -m tests.fetch_test_images")
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    h, w = rgb.shape[:2]
    gt = gt_mask(item)
    small, scale = resize_for_model(rgb, s.sam_max_side)
    sh, sw = small.shape[:2]
    res: dict = {"file": item["file"], "category": item["category"], "gt_area_frac": item["area_frac"]}
    masks: dict[str, np.ndarray | None] = {}

    def timed(fn):
        t = time.perf_counter()
        out = fn()
        return out, time.perf_counter() - t

    # text: noun prompt
    cands, dt = timed(lambda: seg.auto_masks(small, item["prompt"]))
    ranked = rank_candidates(cands, sh, sw, s.stickers_per_capture, named=True)
    hero = upscale_mask(ranked[0].mask, h, w) if ranked else None
    res["text_iou"] = iou(hero, gt) if hero is not None else 0.0
    res["text_found"] = bool(ranked)
    res["text_secs"] = dt
    masks["text"] = hero

    # generic: no noun
    cands, dt = timed(lambda: seg.auto_masks(small, None))
    ranked = rank_candidates(cands, sh, sw, s.stickers_per_capture)
    full = [upscale_mask(c.mask, h, w) for c in ranked]
    ious = [iou(m, gt) for m in full]
    res["generic_hero_iou"] = ious[0] if ious else 0.0
    res["generic_best_iou"] = max(ious, default=0.0)
    res["generic_n_stickers"] = len(ranked)
    res["generic_secs"] = dt
    masks["generic"] = full[int(np.argmax(ious))] if ious else None

    # point: tap inside the object
    px, py = interior_point(gt)
    cand, dt = timed(lambda: seg.mask_at_point(small, int(px * scale), int(py * scale)))
    pm = upscale_mask(cand.mask, h, w) if cand else None
    res["point_iou"] = iou(pm, gt) if pm is not None else 0.0
    res["point_secs"] = dt
    masks["point"] = pm
    res["_masks"] = masks
    res["_rgb"] = rgb
    res["_gt"] = gt
    return res


def summarize(rows: list[dict]) -> dict:
    def mean(k):
        return statistics.fmean(r[k] for r in rows)

    return {
        "n_images": len(rows),
        "text_mean_iou": mean("text_iou"),
        "text_hit_rate_50": sum(r["text_iou"] >= 0.5 for r in rows) / len(rows),
        "generic_hero_mean_iou": mean("generic_hero_iou"),
        "generic_hero_hit_rate_50": sum(r["generic_hero_iou"] >= 0.5 for r in rows) / len(rows),
        "generic_any_hit_rate_50": sum(r["generic_best_iou"] >= 0.5 for r in rows) / len(rows),
        "point_mean_iou": mean("point_iou"),
        "point_hit_rate_50": sum(r["point_iou"] >= 0.5 for r in rows) / len(rows),
        "median_text_secs": statistics.median(r["text_secs"] for r in rows),
        "median_generic_secs": statistics.median(r["generic_secs"] for r in rows),
        "median_point_secs": statistics.median(r["point_secs"] for r in rows),
    }


def save_overlay(row: dict, outdir: Path) -> None:
    """Side-by-side panels: photo | ground truth | text | generic | point."""
    rgb = row["_rgb"]
    scale = 360 / rgb.shape[0]
    base = cv2.resize(rgb, None, fx=scale, fy=scale)
    panels = [base]
    titles = ["photo", "ground truth"]
    for name, m in [("gt", row["_gt"]), ("text", row["_masks"]["text"]),
                    ("generic", row["_masks"]["generic"]), ("point", row["_masks"]["point"])]:
        p = base.copy()
        if m is not None:
            mm = cv2.resize(m.astype(np.uint8), (p.shape[1], p.shape[0]), interpolation=cv2.INTER_NEAREST).astype(bool)
            color = np.array([0, 200, 120] if name == "gt" else [230, 80, 60])
            p[mm] = (0.45 * p[mm] + 0.55 * color).astype(np.uint8)
            edge = cv2.Canny(mm.astype(np.uint8) * 255, 50, 150) > 0
            p[edge] = (255, 255, 255)
        label = name if name == "gt" else f"{name}  IoU {row[name + '_iou'] if name + '_iou' in row else row['generic_best_iou']:.2f}"
        cv2.putText(p, label, (8, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 3)
        cv2.putText(p, label, (8, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (20, 20, 20), 1)
        panels.append(p)
    panels = [cv2.resize(p, (int(p.shape[1] * 360 / p.shape[0]), 360)) if p.shape[0] != 360 else p for p in panels]
    # drop the plain photo panel to keep sheets compact: gt/text/generic/point
    sheet = np.hstack(panels[1:])
    cv2.imwrite(str(outdir / f"{row['category'].replace(' ', '_')}_{Path(row['file']).stem}.jpg"),
                cv2.cvtColor(sheet, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 85])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json")
    ap.add_argument("--overlays")
    ap.add_argument("--split", choices=["dev", "holdout"], default=None)
    a = ap.parse_args()
    seg = get_segmenter()
    items = load_manifest(a.split)
    seg.auto_masks(resize_for_model(np.zeros((480, 640, 3), np.uint8), 640)[0], "warmup")  # JIT warm-up
    rows = []
    for it in items:
        r = evaluate_one(it, seg)
        print(f"{r['category']:13s} text {r['text_iou']:.2f}  generic {r['generic_hero_iou']:.2f}/{r['generic_best_iou']:.2f}  point {r['point_iou']:.2f}")
        if a.overlays:
            Path(a.overlays).mkdir(parents=True, exist_ok=True)
            save_overlay(r, Path(a.overlays))
        rows.append({k: v for k, v in r.items() if not k.startswith("_")})
    summ = summarize(rows)
    print(json.dumps(summ, indent=2))
    if a.json:
        Path(a.json).write_text(json.dumps({"summary": summ, "rows": rows}, indent=2))


if __name__ == "__main__":
    main()
