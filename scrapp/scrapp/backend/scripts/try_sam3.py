"""Run the SAM 3 sticker pipeline on one photo, no database or server needed.

    python scripts/try_sam3.py photo.jpg [--prompt "coffee cup"] [--out out/]

Writes sticker_N.png (die-cut) and overlay.png (ranked masks drawn on the photo).
"""
import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import get_settings  # noqa: E402
from app.services.segmentation import get_segmenter, make_sticker, rank_candidates, resize_for_model  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("image")
ap.add_argument("--prompt", default=None)
ap.add_argument("--out", default="out")
a = ap.parse_args()

rgb = cv2.cvtColor(cv2.imread(a.image), cv2.COLOR_BGR2RGB)
s = get_settings()
small, _ = resize_for_model(rgb, s.sam_max_side)
cands = get_segmenter().auto_masks(small, a.prompt)
ranked = rank_candidates(cands, small.shape[0], small.shape[1], s.stickers_per_capture)
print(f"{len(cands)} raw masks -> {len(ranked)} stickers")

out = Path(a.out)
out.mkdir(exist_ok=True)
overlay = small.copy()
rng = np.random.default_rng(0)
for i, c in enumerate(ranked):
    png, _ = make_sticker(small, c.mask)
    (out / f"sticker_{i}.png").write_bytes(png)
    overlay[c.mask] = (0.5 * overlay[c.mask] + 0.5 * rng.integers(60, 255, 3)).astype(np.uint8)
    print(f"  #{i} score={c.rank_score:.2f} quality={c.quality:.2f} bbox={c.bbox}")
cv2.imwrite(str(out / "overlay.png"), cv2.cvtColor(overlay, cv2.COLOR_RGB2BGR))
