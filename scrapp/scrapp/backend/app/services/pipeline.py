"""Capture -> stickers. Runs as a background task after the original photo is safely stored."""
from __future__ import annotations

import asyncio
import logging

import cv2
import numpy as np
from bson import ObjectId

from ..config import get_settings
from ..db import db
from ..storage import get_bytes, put_bytes
from ..util import now
from .segmentation import (
    MaskCandidate,
    get_segmenter,
    make_sticker,
    mask_png,
    rank_candidates,
    resize_for_model,
    upscale_mask,
)

log = logging.getLogger("scrapp.pipeline")

# SAM and the image work are CPU/GPU heavy. Everything heavy runs in worker threads so the API keeps answering,
# and only one capture is processed at a time (one GPU) instead of stacking up.
_work = asyncio.Semaphore(1)


def decode_rgb(data: bytes) -> np.ndarray:
    # IMREAD_COLOR applies EXIF orientation, so phone imports come out upright.
    bgr = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if bgr is None:
        raise ValueError("Could not decode image")
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)


async def _store_sticker(capture: dict, full_rgb: np.ndarray, cand: MaskCandidate, hero: bool, source: str) -> ObjectId:
    png, crop_box = await asyncio.to_thread(make_sticker, full_rgb, cand.mask)
    owner = capture["owner_id"]
    image_id = await put_bytes(png, "sticker.png", "image/png", owner, "sticker")
    mask_id = await put_bytes(await asyncio.to_thread(mask_png, cand.mask), "mask.png", "image/png", owner, "mask")
    doc = {
        "owner_id": owner,
        "capture_id": capture["_id"],
        "image_file_id": image_id,
        "mask_file_id": mask_id,
        "bbox": list(cand.bbox),  # object box in source pixels (used as the hunt image target)
        "crop_box": list(crop_box),
        "score": round(cand.rank_score, 4),
        "is_hero": hero,
        "source": source,  # auto | point
        "title": capture.get("place_name") or "",
        "location": capture.get("location"),
        "place_name": capture.get("place_name"),
        "captured_at": capture.get("captured_at"),
        "created_at": now(),
    }
    res = await db().stickers.insert_one(doc)
    return res.inserted_id


async def process_capture(capture_id: ObjectId) -> None:
    async with _work:
        await _process_capture(capture_id)


async def _process_capture(capture_id: ObjectId) -> None:
    s = get_settings()
    caps = db().captures
    capture = await caps.find_one({"_id": capture_id})
    if not capture:
        return
    try:
        full_rgb = await asyncio.to_thread(decode_rgb, await get_bytes(capture["original_file_id"]))
        h, w = full_rgb.shape[:2]
        small, _ = await asyncio.to_thread(resize_for_model, full_rgb, s.sam_max_side)
        seg = await asyncio.to_thread(get_segmenter)  # first call loads SAM 3: never on the event loop
        cands = await asyncio.to_thread(seg.auto_masks, small, capture.get("prompt"))
        ranked = await asyncio.to_thread(rank_candidates, cands, small.shape[0], small.shape[1], s.stickers_per_capture,
                                         named=bool(capture.get("prompt")))
        sticker_ids = []
        sx, sy = w / small.shape[1], h / small.shape[0]
        for i, c in enumerate(ranked):
            full_mask = await asyncio.to_thread(upscale_mask, c.mask, h, w)
            x, y, bw, bh = c.bbox
            c_full = MaskCandidate(
                mask=full_mask,
                quality=c.quality,
                bbox=(int(x * sx), int(y * sy), int(bw * sx), int(bh * sy)),
                area=int(full_mask.sum()),
                rank_score=c.rank_score,
            )
            sticker_ids.append(await _store_sticker(capture, full_rgb, c_full, hero=(i == 0), source="auto"))
        await caps.update_one(
            {"_id": capture_id},
            {"$set": {
                "status": "ready" if sticker_ids else "no_objects",
                "sticker_ids": sticker_ids,
                "hero_sticker_id": sticker_ids[0] if sticker_ids else None,
                "width": w, "height": h,
                "processed_at": now(),
            }},
        )
    except Exception as e:  # keep the original; mark the capture so the app can retry
        log.exception("capture %s failed", capture_id)
        await caps.update_one({"_id": capture_id}, {"$set": {"status": "failed", "error": str(e)[:300]}})


async def sticker_at_point(capture: dict, x_norm: float, y_norm: float) -> ObjectId | None:
    """Tap-to-cut: segment whatever is under a tap on the original photo."""
    s = get_settings()
    full_rgb = await asyncio.to_thread(decode_rgb, await get_bytes(capture["original_file_id"]))
    h, w = full_rgb.shape[:2]
    small, scale = await asyncio.to_thread(resize_for_model, full_rgb, s.sam_max_side)
    px, py = int(x_norm * small.shape[1]), int(y_norm * small.shape[0])
    seg = await asyncio.to_thread(get_segmenter)
    cand = await asyncio.to_thread(seg.mask_at_point, small, px, py)
    if cand is None:
        return None
    full_mask = await asyncio.to_thread(upscale_mask, cand.mask, h, w)
    x, y, bw, bh = cand.bbox
    inv = 1.0 / scale
    c_full = MaskCandidate(full_mask, cand.quality, (int(x * inv), int(y * inv), int(bw * inv), int(bh * inv)),
                           int(full_mask.sum()), cand.quality)
    sid = await _store_sticker(capture, full_rgb, c_full, hero=False, source="point")
    await db().captures.update_one({"_id": capture["_id"]}, {"$push": {"sticker_ids": sid}})
    return sid
