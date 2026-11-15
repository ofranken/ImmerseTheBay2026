"""Appearance (embedding) matching for scavenger hunts: the fallback when SIFT finds nothing.

SIFT + homography (matching.py) is precise but only works on flat, textured targets (posters, paintings, signs). A cup,
a plant or a statue changes appearance with the viewpoint, so for those we compare *what things look like*: a DINOv2
embedding of the hunt item's target crop against embeddings of the attempt photo (whole frame, a centre crop and a 2x2
grid of crops, so a small object in a big frame still gets a view that is mostly that object).

An item counts as found only if ALL of these hold (all configurable):
  * its best view similarity is at least `min_score`;
  * it beats the runner-up item by `margin` (when the hunt has several unfound items), so a generic "looks like an
    object" frame cannot tick off an arbitrary item;
  * it stands out from the frame: best view minus the mean over views is at least `standout` (the distractor baseline:
    a frame that resembles everything equally resembles nothing in particular).

The model loads lazily and is optional. If it cannot load (no weights, offline, no torch) the hunt falls back to
SIFT-only behaviour and this is logged once. `decide()` is pure numpy so it is unit-tested with a stub embedder.
"""
from __future__ import annotations

import logging
import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import Protocol

import cv2
import numpy as np

log = logging.getLogger("scrapp.embedding")


class Embedder(Protocol):
    def embed(self, images_bgr: list[np.ndarray]) -> np.ndarray:
        """Returns an (n, d) float32 array of L2-normalised embeddings."""
        ...


def _l2(x: np.ndarray) -> np.ndarray:
    return x / np.maximum(np.linalg.norm(x, axis=1, keepdims=True), 1e-9)


class DinoEmbedder:
    """DINOv2 (small) through timm. CPU by default so it never fights SAM for the GPU."""

    def __init__(self, model_name: str, device: str = "cpu"):
        import timm
        import torch

        self._torch = torch
        self.device = device
        self.model = timm.create_model(model_name, pretrained=True, num_classes=0).eval().to(device)
        cfg = timm.data.resolve_data_config({}, model=self.model)
        self.size = int(cfg["input_size"][-1])
        self.mean = np.array(cfg["mean"], np.float32)
        self.std = np.array(cfg["std"], np.float32)
        self._lock = threading.Lock()

    def _prep(self, bgr: np.ndarray) -> np.ndarray:
        rgb = cv2.cvtColor(cv2.resize(bgr, (self.size, self.size), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2RGB)
        return ((rgb.astype(np.float32) / 255.0 - self.mean) / self.std).transpose(2, 0, 1)

    def embed(self, images_bgr: list[np.ndarray]) -> np.ndarray:
        batch = self._torch.from_numpy(np.stack([self._prep(i) for i in images_bgr])).to(self.device)
        with self._lock, self._torch.inference_mode():
            out = self.model(batch)
        return _l2(out.float().cpu().numpy())


# ------------------------------------------------------------------------------- lazy singleton
_embedder: Embedder | None = None
_failed = False
_lock = threading.Lock()


def get_embedder(settings) -> Embedder | None:
    """The shared embedder, or None when disabled/unavailable (logged once, then silent)."""
    global _embedder, _failed
    if not settings.embed_enabled or _failed:
        return None
    with _lock:
        if _embedder is None and not _failed:
            try:
                _embedder = DinoEmbedder(settings.embed_model, settings.embed_device)
                log.info("hunt embedding matcher ready: %s on %s", settings.embed_model, settings.embed_device)
            except Exception as e:  # noqa: BLE001 - optional feature: never break the hunt
                _failed = True
                log.warning("hunt embedding matcher unavailable (%s: %s); hunts use SIFT only", type(e).__name__, e)
        return _embedder


def set_embedder(e: Embedder | None) -> None:
    """Tests (or other code) can install an embedder; None resets to lazy loading."""
    global _embedder, _failed
    _embedder, _failed = e, False


# ------------------------------------------------------------------------------- views and cache
def query_views(img: np.ndarray) -> list[np.ndarray]:
    """Whole frame + centre crop + 2x2 grid: 6 views, so a small object still dominates at least one of them."""
    h, w = img.shape[:2]
    views = [img, img[h // 5: h - h // 5, w // 5: w - w // 5]]
    for r in (0, 1):
        for c in (0, 1):
            views.append(img[r * h // 2: (r + 1) * h // 2 + h // 8, c * w // 2: (c + 1) * w // 2 + w // 8])
    return [v for v in views if v.shape[0] >= 16 and v.shape[1] >= 16]


class TargetCache:
    """In-process LRU of target-crop embeddings keyed by the stored target file id."""

    def __init__(self, maxsize: int = 512):
        self.maxsize = maxsize
        self._d: OrderedDict[str, np.ndarray] = OrderedDict()
        self.misses = 0

    def get(self, key: str, compute) -> np.ndarray:
        if key in self._d:
            self._d.move_to_end(key)
            return self._d[key]
        self.misses += 1
        vec = compute()
        self._d[key] = vec
        if len(self._d) > self.maxsize:
            self._d.popitem(last=False)
        return vec


target_cache = TargetCache()


# ------------------------------------------------------------------------------- decision
@dataclass
class EmbeddingResult:
    matched: bool
    item_id: str | None = None
    score: float = 0.0
    margin: float = 0.0
    standout: float = 0.0
    reason: str = ""
    ranking: list[tuple[str, float]] | None = None


def decide(views: np.ndarray, targets: dict[str, np.ndarray], min_score: float, margin: float, standout: float) -> EmbeddingResult:
    """views: (v, d) normalised view embeddings; targets: item_id -> (d,) normalised embedding."""
    if not targets:
        return EmbeddingResult(False, reason="no remaining items")
    scored = []
    for item_id, t in targets.items():
        sims = views @ t
        scored.append((item_id, float(sims.max()), float(sims.max() - sims.mean())))
    scored.sort(key=lambda s: s[1], reverse=True)
    ranking = [(i, round(s, 4)) for i, s, _ in scored]
    best_id, best, stand = scored[0]
    gap = best - scored[1][1] if len(scored) > 1 else 1.0
    if best < min_score:
        return EmbeddingResult(False, best_id, best, gap, stand, "below min_score", ranking)
    if gap < margin:
        return EmbeddingResult(False, best_id, best, gap, stand, "too close to the runner-up item", ranking)
    if stand < standout:
        return EmbeddingResult(False, best_id, best, gap, stand, "does not stand out from the rest of the frame", ranking)
    return EmbeddingResult(True, best_id, best, gap, stand, "ok", ranking)


def match_embedding(embedder: Embedder, query_bgr: np.ndarray, items: list[tuple[str, str, np.ndarray]], settings,
                    cache: TargetCache = target_cache) -> EmbeddingResult:
    """items: [(item_id, target_file_id, target_bgr)]. Blocking (model inference): call from a thread."""
    if not items:
        return EmbeddingResult(False, reason="no remaining items")
    views = embedder.embed(query_views(query_bgr))
    targets = {iid: cache.get(fid, lambda img=img: embedder.embed([img])[0]) for iid, fid, img in items}
    return decide(views, targets, settings.embed_min_score, settings.embed_margin, settings.embed_standout)
