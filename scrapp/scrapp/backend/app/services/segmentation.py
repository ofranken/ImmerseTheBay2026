"""Sticker segmentation.

Default backend is SAM 3 running on a GPU: text-prompted concept segmentation over the whole frame, then
`rank_candidates` scores every mask by how central, how well-formed and how object-sized it is.
The glasses have no eye tracking, so "where the wearer was looking" is approximated by the centre of
the head-mounted camera frame: the most central object becomes the hero sticker.

`GrabCutSegmenter` is a CPU-only fallback so the pipeline runs on a laptop without a GPU. It is for
development only; production uses SAM.
"""
from __future__ import annotations

import math
import threading
from dataclasses import dataclass
from typing import Protocol

import cv2
import numpy as np

from ..config import get_settings


@dataclass(eq=False)  # identity equality; masks are arrays
class MaskCandidate:
    mask: np.ndarray  # bool, HxW
    quality: float  # 0..1, model confidence
    bbox: tuple[int, int, int, int]  # x, y, w, h
    area: int
    rank_score: float = 0.0
    solidity: float = 1.0  # area / convex-hull area: ~1 for a solid object, low for ragged surfaces


class Segmenter(Protocol):
    def auto_masks(self, image_rgb: np.ndarray, prompt: str | None = None) -> list[MaskCandidate]: ...

    def mask_at_point(self, image_rgb: np.ndarray, x: int, y: int) -> MaskCandidate | None: ...


def candidate_from_mask(mask: np.ndarray, quality: float) -> MaskCandidate | None:
    mask = mask.astype(bool)
    area = int(mask.sum())
    if area == 0:
        return None
    ys, xs = np.nonzero(mask)
    x0, x1, y0, y1 = int(xs.min()), int(xs.max()), int(ys.min()), int(ys.max())
    return MaskCandidate(mask=mask, quality=float(quality), bbox=(x0, y0, x1 - x0 + 1, y1 - y0 + 1), area=area,
                         solidity=mask_solidity(mask))


def mask_solidity(mask: np.ndarray) -> float:
    """Filled-ness of a mask: area over convex-hull area. A tabletop full of holes scores far below a mug."""
    contours, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return 0.0
    hull_area = cv2.contourArea(cv2.convexHull(np.vstack(contours)))
    return min(1.0, float(mask.sum()) / hull_area) if hull_area > 0 else 0.0


def refine_mask(mask: np.ndarray) -> np.ndarray:
    """Clean a cutout: drop stray islands, fill small holes. Keeps genuine large holes (a mug handle)."""
    m = mask.astype(np.uint8)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(m, 8)
    if n > 2:
        areas = stats[1:, cv2.CC_STAT_AREA]
        keep = 1 + np.nonzero(areas >= 0.05 * areas.max())[0]
        m = np.isin(labels, keep).astype(np.uint8)
    inv = (1 - m).astype(np.uint8)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(inv, 4)
    limit = 0.02 * max(int(m.sum()), 1)
    border = set(labels[0, :]) | set(labels[-1, :]) | set(labels[:, 0]) | set(labels[:, -1])
    for i in range(1, n):
        if i not in border and stats[i, cv2.CC_STAT_AREA] <= limit:
            m[labels == i] = 1
    return m.astype(bool)


# ------------------------------------------------------------------------------------------- SAM 3
class Sam3Segmenter:
    """SAM 3 image model (promptable concept segmentation) plus its SAM-style point predictor.

    SAM 3 has no "segment everything" mode, so `auto_masks` has two paths:
      * a spoken noun ("scrapbook that cup") is the text prompt;
      * with no noun, generic concept words ("object", "thing") find almost nothing, so instead we tap a
        small grid of points around the frame centre with the point predictor. That is the head-direction
        prior: the wearer is facing what they care about.
    Overlaps are deduplicated later by `rank_candidates`. Tap-to-cut uses the same point predictor.
    """

    def __init__(self, checkpoint: str, device: str, confidence: float, vocab: list[str] | None = None,
                 vocab_min_score: float = 0.45):
        import torch  # noqa: F401  (imported lazily so the API boots without a GPU stack)
        from sam3.model.sam3_image_processor import Sam3Processor
        from sam3.model_builder import build_sam3_image_model

        # Empty checkpoint -> the builder downloads facebook/sam3 (needs `hf auth login`).
        model = build_sam3_image_model(
            device=device,
            checkpoint_path=checkpoint or None,
            load_from_HF=not checkpoint,
            enable_inst_interactivity=True,
        )
        self._processor = Sam3Processor(model, device=device, confidence_threshold=confidence)
        self._predictor = model.inst_interactive_predictor
        # The builder makes the point-prompt tracker with backbone=None; it shares the main vision
        # backbone (built with the extra SAM-style neck by enable_inst_interactivity=True).
        self._predictor.model.backbone = model.backbone
        self._device = device
        self._vocab = vocab or []
        self._vocab_min_score = vocab_min_score
        self._lock = threading.Lock()  # one GPU, one request at a time

    def _autocast(self):
        import torch

        return torch.autocast(self._device.split(":")[0], dtype=torch.bfloat16, enabled=self._device != "cpu")

    def auto_masks(self, image_rgb: np.ndarray, prompt: str | None = None) -> list[MaskCandidate]:
        if prompt and prompt.strip():
            return self._text_masks(image_rgb, [prompt.strip()], 0.0)
        # No noun: everyday-object vocabulary (clean whole-object masks), plus centre taps for anything
        # the vocabulary doesn't name.
        return self._text_masks(image_rgb, self._vocab, self._vocab_min_score) + self._center_point_masks(image_rgb)

    def _text_masks(self, image_rgb: np.ndarray, prompts: list[str], min_score: float) -> list[MaskCandidate]:
        import torch
        from PIL import Image

        out: list[MaskCandidate] = []
        if not prompts:
            return out
        with self._lock, torch.inference_mode(), self._autocast():
            state = self._processor.set_image(Image.fromarray(image_rgb))  # embed once, prompt many times
            for text in prompts:
                self._processor.reset_all_prompts(state)
                self._processor.set_text_prompt(prompt=text, state=state)
                masks, scores = state.get("masks"), state.get("scores")
                if masks is None or len(scores) == 0:
                    continue
                masks = masks[:, 0].cpu().numpy()  # (N, H, W) bool
                for m, sc in zip(masks, scores.float().cpu().numpy()):
                    if sc < min_score:
                        continue
                    c = candidate_from_mask(refine_mask(m), float(sc))
                    if c:
                        out.append(c)
        return out

    def _center_point_masks(self, image_rgb: np.ndarray) -> list[MaskCandidate]:
        import torch
        from PIL import Image

        h, w = image_rgb.shape[:2]
        points = [(0.5, 0.5), (0.32, 0.5), (0.68, 0.5), (0.5, 0.32), (0.5, 0.68)]
        out: list[MaskCandidate] = []
        with self._lock, torch.inference_mode(), self._autocast():
            self._predictor.set_image(Image.fromarray(image_rgb))  # embed once, click five times
            for fx, fy in points:
                masks, scores, _ = self._predictor.predict(
                    point_coords=np.array([[fx * w, fy * h]], dtype=np.float32),
                    point_labels=np.array([1], dtype=np.int32),
                    multimask_output=True,
                )
                for m, sc in zip(masks, scores):
                    c = candidate_from_mask(refine_mask(m > 0), float(sc))
                    if c:
                        out.append(c)
        return out

    def mask_at_point(self, image_rgb: np.ndarray, x: int, y: int) -> MaskCandidate | None:
        import torch
        from PIL import Image

        with self._lock, torch.inference_mode(), self._autocast():
            self._predictor.set_image(Image.fromarray(image_rgb))
            masks, scores, _ = self._predictor.predict(
                point_coords=np.array([[x, y]], dtype=np.float32),
                point_labels=np.array([1], dtype=np.int32),
                multimask_output=True,
            )
        best = int(np.argmax(scores))
        return candidate_from_mask(refine_mask(masks[best] > 0), float(scores[best]))


# ------------------------------------------------------------------------------- CPU dev fallback
class GrabCutSegmenter:
    """Rough central-object cutout with OpenCV GrabCut. Development fallback only."""

    def _grabcut(self, image_rgb: np.ndarray, rect: tuple[int, int, int, int]) -> np.ndarray:
        bgr = cv2.cvtColor(image_rgb, cv2.COLOR_RGB2BGR)
        mask = np.zeros(bgr.shape[:2], np.uint8)
        bgd, fgd = np.zeros((1, 65), np.float64), np.zeros((1, 65), np.float64)
        cv2.grabCut(bgr, mask, rect, bgd, fgd, 5, cv2.GC_INIT_WITH_RECT)
        fg = (mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD)
        n, labels, stats, _ = cv2.connectedComponentsWithStats(fg.astype(np.uint8), 8)
        if n <= 1:
            return fg
        largest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
        return labels == largest

    def auto_masks(self, image_rgb: np.ndarray, prompt: str | None = None) -> list[MaskCandidate]:
        h, w = image_rgb.shape[:2]
        rect = (int(w * 0.2), int(h * 0.2), int(w * 0.6), int(h * 0.6))
        c = candidate_from_mask(self._grabcut(image_rgb, rect), 0.5)
        return [c] if c else []

    def mask_at_point(self, image_rgb: np.ndarray, x: int, y: int) -> MaskCandidate | None:
        h, w = image_rgb.shape[:2]
        half = int(min(w, h) * 0.18)
        x0, y0 = max(0, x - half), max(0, y - half)
        x1, y1 = min(w - 1, x + half), min(h - 1, y + half)
        return candidate_from_mask(self._grabcut(image_rgb, (x0, y0, x1 - x0, y1 - y0)), 0.5)


_segmenter: Segmenter | None = None
_seg_lock = threading.Lock()


def get_segmenter() -> Segmenter:
    global _segmenter
    with _seg_lock:
        if _segmenter is None:
            s = get_settings()
            if s.segmenter == "sam3":
                vocab = [w.strip() for w in s.sam3_vocab.split(",") if w.strip()]
                _segmenter = Sam3Segmenter(s.sam3_checkpoint, s.sam_device, s.sam3_confidence, vocab)
            elif s.segmenter == "grabcut":
                _segmenter = GrabCutSegmenter()
            else:
                raise RuntimeError(f"Unknown SEGMENTER={s.segmenter!r}")
        return _segmenter


# ------------------------------------------------------------------------------------- ranking
def _iou(a: np.ndarray, b: np.ndarray) -> tuple[float, float]:
    inter = np.logical_and(a, b).sum()
    if inter == 0:
        return 0.0, 0.0
    union = np.logical_or(a, b).sum()
    containment = inter / min(a.sum(), b.sum())
    return float(inter / union), float(containment)


def rank_candidates(
    cands: list[MaskCandidate], height: int, width: int, k: int, named: bool = False
) -> list[MaskCandidate]:
    """Score masks by centrality, size and model quality; drop background-like masks; dedupe parts.

    `named=True` means the wearer said what they wanted ("scrapbook that chair"), so big or
    frame-touching masks are not treated as background.

    Returns at most k candidates, best (the hero sticker) first.
    """
    total = float(height * width)
    cx, cy = width / 2.0, height / 2.0
    half_diag = math.hypot(cx, cy)
    scored: list[MaskCandidate] = []
    for c in cands:
        frac = c.area / total
        if frac < 0.004 or (frac > 0.65 and not named):
            continue
        x, y, w, h = c.bbox
        borders = (x <= 1) + (y <= 1) + (x + w >= width - 1) + (y + h >= height - 1)
        if borders >= 3 and not named:  # floor, wall, sky
            continue
        # Ragged masks: a tabletop with holes, a tangle of cable. Small spindly things (legs, bikes) are fine.
        if not named and (c.solidity < 0.55 or (frac > 0.18 and c.solidity < 0.80)):
            continue
        ys, xs = np.nonzero(c.mask)
        d = math.hypot(xs.mean() - cx, ys.mean() - cy) / half_diag
        centrality = math.exp(-(d * d) / (2 * 0.35 * 0.35))
        size_score = min(1.0, frac / 0.05) * (1.0 if frac < 0.45 else max(0.0, (0.65 - frac) / 0.2))
        bonus = 0.15 if c.mask[int(cy), int(cx)] else 0.0
        surface_penalty = 0.25 if (frac > 0.40 and not named) else 0.0  # huge masks are usually surfaces
        c.rank_score = (0.50 * centrality + 0.25 * c.quality + 0.15 * size_score + 0.10 * c.solidity
                        + bonus - surface_penalty)
        scored.append(c)

    scored.sort(key=lambda c: c.rank_score, reverse=True)
    kept: list[MaskCandidate] = []
    for c in scored:
        if any(max(_iou(c.mask, k_.mask)) > 0.6 for k_ in kept):
            continue
        kept.append(c)
        if len(kept) >= k:
            break
    return kept


# ------------------------------------------------------------------------------------ stickers
def make_sticker(image_rgb: np.ndarray, mask: np.ndarray) -> tuple[bytes, tuple[int, int, int, int]]:
    """Die-cut sticker: object pixels, a white outline and a transparent background, as PNG bytes.

    Returns (png_bytes, crop_box_in_source_pixels as x, y, w, h).
    """
    mask = mask.astype(np.uint8)
    h_img, w_img = mask.shape
    ys, xs = np.nonzero(mask)
    x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
    span = max(x1 - x0, y1 - y0) + 1
    border = max(6, int(round(span * 0.05)))
    pad = border * 2 + 4
    cx0, cy0 = max(0, x0 - pad), max(0, y0 - pad)
    cx1, cy1 = min(w_img, x1 + pad + 1), min(h_img, y1 + pad + 1)

    m = mask[cy0:cy1, cx0:cx1] * 255
    rgb = image_rgb[cy0:cy1, cx0:cx1].astype(np.float32)
    # Pad the crop so the outline never touches the PNG edge, even for objects cut by the frame.
    m = cv2.copyMakeBorder(m, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=0)
    rgb = cv2.copyMakeBorder(rgb, pad, pad, pad, pad, cv2.BORDER_REPLICATE)

    kernel_small = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, kernel_small)
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, kernel_small)
    alpha_obj = cv2.GaussianBlur(m, (0, 0), 1.0).astype(np.float32) / 255.0

    kernel_border = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * border + 1, 2 * border + 1))
    outline = cv2.dilate(m, kernel_border)
    alpha_out = cv2.GaussianBlur(outline, (0, 0), 1.2).astype(np.float32) / 255.0

    white = np.full_like(rgb, 255.0)
    a = alpha_obj[..., None]
    out_rgb = rgb * a + white * (1.0 - a)
    out_alpha = np.maximum(alpha_out, alpha_obj)

    rgba = np.dstack([out_rgb, out_alpha * 255.0]).clip(0, 255).astype(np.uint8)
    bgra = cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGRA)
    ok, buf = cv2.imencode(".png", bgra)
    if not ok:
        raise RuntimeError("PNG encode failed")
    return buf.tobytes(), (int(cx0), int(cy0), int(cx1 - cx0), int(cy1 - cy0))


def fill_holes(mask: np.ndarray, max_frac: float) -> np.ndarray:
    """Fill enclosed holes up to max_frac of the object's area. SAM often leaves bright patches (a white belly)
    as holes; a 3D generator would see background through them. Big holes (a mug handle) are kept."""
    m = mask.astype(np.uint8)
    inv = (1 - m).astype(np.uint8)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(inv, 4)
    border = set(labels[0, :]) | set(labels[-1, :]) | set(labels[:, 0]) | set(labels[:, -1])
    limit = max_frac * max(int(m.sum()), 1)
    for i in range(1, n):
        if i not in border and stats[i, cv2.CC_STAT_AREA] <= limit:
            m[labels == i] = 1
    return m.astype(bool)


def cutout_png(image_rgb: np.ndarray, mask: np.ndarray, max_side: int = 1024, min_side: int = 512,
               pad_frac: float = 0.06) -> bytes:
    """Just the object on a transparent background: no white outline, cropped, <= max_side. For image-to-3D.

    (make_sticker's outline is for humans; fed to a 3D generator it becomes part of the model.)
    """
    mask = fill_holes(mask, 0.10).astype(np.uint8)
    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        raise ValueError("empty mask")
    h, w = mask.shape
    x0, x1, y0, y1 = int(xs.min()), int(xs.max()), int(ys.min()), int(ys.max())
    pad = int(round(max(x1 - x0, y1 - y0) * pad_frac))
    cx0, cy0, cx1, cy1 = max(0, x0 - pad), max(0, y0 - pad), min(w, x1 + pad + 1), min(h, y1 + pad + 1)
    alpha = cv2.GaussianBlur(mask[cy0:cy1, cx0:cx1] * 255, (0, 0), 0.8)
    rgb = image_rgb[cy0:cy1, cx0:cx1]
    longest = float(max(alpha.shape))
    # Small objects (tiny source photos) get upscaled so Meshy has something to work with; big ones are shrunk.
    scale = max_side / longest if longest > max_side else (min_side / longest if longest < min_side else 1.0)
    if scale != 1.0:
        size = (max(1, int(round(alpha.shape[1] * scale))), max(1, int(round(alpha.shape[0] * scale))))
        interp = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_CUBIC
        rgb = cv2.resize(rgb, size, interpolation=interp)
        alpha = cv2.resize(alpha, size, interpolation=interp)
    bgra = cv2.cvtColor(np.dstack([rgb, alpha]), cv2.COLOR_RGBA2BGRA)
    ok, buf = cv2.imencode(".png", bgra)
    if not ok:
        raise RuntimeError("PNG encode failed")
    return buf.tobytes()


def mask_png(mask: np.ndarray) -> bytes:
    ok, buf = cv2.imencode(".png", mask.astype(np.uint8) * 255)
    if not ok:
        raise RuntimeError("PNG encode failed")
    return buf.tobytes()


def resize_for_model(image_rgb: np.ndarray, max_side: int) -> tuple[np.ndarray, float]:
    h, w = image_rgb.shape[:2]
    scale = min(1.0, max_side / float(max(h, w)))
    if scale >= 1.0:
        return image_rgb, 1.0
    small = cv2.resize(image_rgb, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    return small, scale


def upscale_mask(mask: np.ndarray, height: int, width: int) -> np.ndarray:
    if mask.shape == (height, width):
        return mask
    return cv2.resize(mask.astype(np.uint8), (width, height), interpolation=cv2.INTER_NEAREST).astype(bool)
