"""Quality gate for the SAM 3 segmenter on real photos (COCO val, ground-truth masks).

Skipped automatically without a CUDA GPU and a local checkpoint. Thresholds sit below the recorded
baseline (tests/data/baseline.json) so normal noise passes but a real regression fails.

    python -m pytest -m gpu -s          # -s prints the per-image table
"""
import json
from pathlib import Path

import pytest

from app.config import get_settings

pytestmark = pytest.mark.gpu


@pytest.fixture(scope="session")
def results():
    torch = pytest.importorskip("torch")
    if not torch.cuda.is_available():
        pytest.skip("no CUDA GPU")
    s = get_settings()
    if not s.sam3_checkpoint or not Path(s.sam3_checkpoint).exists():
        pytest.skip("SAM3_CHECKPOINT not set to a local sam3.pt")
    from tests import fetch_test_images, sam_eval
    from app.services.segmentation import Sam3Segmenter

    try:
        fetch_test_images.fetch()
    except OSError as e:
        pytest.skip(f"could not download test images: {e}")
    seg = Sam3Segmenter(s.sam3_checkpoint, s.sam_device, s.sam3_confidence)
    rows = [sam_eval.evaluate_one(it, seg) for it in sam_eval.load_manifest()]
    for r in rows:
        print(f"{r['category']:13s} text {r['text_iou']:.2f}  no-noun {r['generic_hero_iou']:.2f}/{r['generic_best_iou']:.2f}  tap {r['point_iou']:.2f}")
    summary = sam_eval.summarize(rows)
    print(json.dumps(summary, indent=2))
    return summary


def test_named_object_is_cut_accurately(results):
    assert results["text_mean_iou"] >= 0.60
    assert results["text_hit_rate_50"] >= 0.65


def test_no_noun_finds_the_object_in_the_top_stickers(results):
    assert results["generic_any_hit_rate_50"] >= 0.55
    assert results["generic_hero_hit_rate_50"] >= 0.40


def test_tap_to_cut(results):
    assert results["point_hit_rate_50"] >= 0.50


def test_latency_is_interactive(results):
    for k in ("median_text_secs", "median_generic_secs", "median_point_secs"):
        assert results[k] < 3.0
