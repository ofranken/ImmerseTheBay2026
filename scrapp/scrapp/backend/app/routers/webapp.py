"""Bridge for the Scrapp 3D Studio web app (scrapp/web-app).

The web app has no user login, so it talks to these routes with a shared key (WEBAPP_KEY) instead of a JWT.
They reuse the exact capture -> sticker pipeline the phone app uses: the same SAM 3 segmenter
(`get_segmenter()`), the same ranking, and the same die-cut sticker maker, so stickers made on the web
look and behave exactly like ones made with the glasses.

Flow:
  POST /webapp/captures         upload a photo as a capture (owner = the web app's "acting as" user)
  POST /webapp/segment          find objects (SAM 3 text prompt or vocabulary + centre taps), ranked
  POST /webapp/segment/point    tap-to-cut: the object under one point
  POST /webapp/stickers         turn chosen candidates into stickers (same documents as the app)

Candidate masks stay in server memory (keyed by a short-lived token) between "find" and "make stickers",
so nothing is segmented twice. Disabled unless WEBAPP_KEY is set.
"""
from __future__ import annotations

import asyncio
import base64
import secrets
import time
from collections import OrderedDict

import cv2
import numpy as np
from bson import ObjectId
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from ..config import get_settings
from ..db import db
from ..services.pipeline import _store_sticker, _work, decode_rgb
from ..services.segmentation import MaskCandidate, get_segmenter, rank_candidates, resize_for_model, upscale_mask
from ..storage import get_bytes, put_bytes
from ..util import now

router = APIRouter(prefix="/webapp", tags=["web app"])


def require_key(x_webapp_key: str | None = Header(default=None)) -> None:
    key = get_settings().webapp_key
    if not key:
        raise HTTPException(503, "The web-app bridge is off. Set WEBAPP_KEY in the backend's .env.")
    if not x_webapp_key or not secrets.compare_digest(x_webapp_key, key):
        raise HTTPException(401, "Wrong web-app key")


# ------------------------------------------------------------------------------- candidate cache
class _Session:
    def __init__(self, capture_id: ObjectId, small_shape: tuple[int, int]):
        self.capture_id = capture_id
        self.small_shape = small_shape  # (h, w) the masks are in
        self.cands: list[MaskCandidate] = []
        self.touched = time.monotonic()


_SESSIONS: OrderedDict[str, _Session] = OrderedDict()
_TTL_S = 20 * 60
_MAX_SESSIONS = 24


def _session(token: str | None) -> _Session | None:
    for k in [k for k, s in _SESSIONS.items() if time.monotonic() - s.touched > _TTL_S]:
        _SESSIONS.pop(k, None)
    s = _SESSIONS.get(token or "")
    if s:
        s.touched = time.monotonic()
        _SESSIONS.move_to_end(token)
    return s


def _new_session(capture_id: ObjectId, small_shape: tuple[int, int]) -> tuple[str, _Session]:
    while len(_SESSIONS) >= _MAX_SESSIONS:
        _SESSIONS.popitem(last=False)
    token = secrets.token_urlsafe(12)
    s = _Session(capture_id, small_shape)
    _SESSIONS[token] = s
    return token, s


def _outline(mask: np.ndarray) -> list[list[list[float]]]:
    """Mask -> simplified outer contours, normalised 0..1, for drawing and hit-testing in the browser."""
    h, w = mask.shape
    contours, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    out = []
    for c in sorted(contours, key=cv2.contourArea, reverse=True)[:6]:
        if cv2.contourArea(c) < 0.0005 * h * w:
            continue
        c = cv2.approxPolyDP(c, 0.0025 * cv2.arcLength(c, True), True)
        out.append([[round(float(x) / w, 4), round(float(y) / h, 4)] for x, y in c[:, 0, :]])
    return out


def _cand_out(i: int, c: MaskCandidate) -> dict:
    h, w = c.mask.shape
    x, y, bw, bh = c.bbox
    return {
        "index": i,
        "score": round(float(c.rank_score or c.quality), 3),
        "quality": round(float(c.quality), 3),
        "area": round(c.area / float(h * w), 4),
        "bbox": [round(x / w, 4), round(y / h, 4), round(bw / w, 4), round(bh / h, 4)],
        "outline": _outline(c.mask),
    }


async def _load_capture(capture_id: str) -> tuple[dict, np.ndarray, np.ndarray]:
    if not ObjectId.is_valid(capture_id):
        raise HTTPException(404, "Capture not found")
    cap = await db().captures.find_one({"_id": ObjectId(capture_id)})
    if not cap:
        raise HTTPException(404, "Capture not found")
    full = await asyncio.to_thread(decode_rgb, await get_bytes(cap["original_file_id"]))
    small, _ = await asyncio.to_thread(resize_for_model, full, get_settings().sam_max_side)
    return cap, full, small


async def _segmenter():
    return await asyncio.to_thread(get_segmenter)  # first call loads SAM 3: never on the event loop


# ------------------------------------------------------------------------------------- routes
@router.get("/health", dependencies=[Depends(require_key)])
async def health():
    s = get_settings()
    return {"ok": True, "segmenter": s.segmenter, "loaded": _segmenter_loaded()}


def _segmenter_loaded() -> bool:
    from ..services import segmentation
    return getattr(segmentation, "_segmenter", None) is not None


class CaptureIn(BaseModel):
    owner_id: str
    image_b64: str = Field(min_length=16)  # raw base64 or a data: URI
    place_name: str | None = Field(default=None, max_length=200)


@router.post("/captures", dependencies=[Depends(require_key)])
async def upload_capture(body: CaptureIn):
    """A photo uploaded on the web becomes a normal capture (original kept, stickers cut later)."""
    if not ObjectId.is_valid(body.owner_id) or not await db().users.find_one({"_id": ObjectId(body.owner_id)}):
        raise HTTPException(422, "Unknown owner")
    raw = body.image_b64.split(",", 1)[1] if body.image_b64.startswith("data:") else body.image_b64
    try:
        data = base64.b64decode(raw, validate=True)
        await asyncio.to_thread(decode_rgb, data)  # reject anything OpenCV can't read
    except Exception:
        raise HTTPException(422, "That isn't an image the segmenter can read (JPEG, PNG or WebP).")
    owner = ObjectId(body.owner_id)
    ctype = "image/png" if data[:8] == b"\x89PNG\r\n\x1a\n" else "image/webp" if data[8:12] == b"WEBP" else "image/jpeg"
    file_id = await put_bytes(data, "capture" + {"image/png": ".png", "image/webp": ".webp"}.get(ctype, ".jpg"), ctype, owner, "original")
    doc = {
        "owner_id": owner, "original_file_id": file_id, "captured_at": now(), "location": None,
        "place_name": body.place_name, "trigger": "web", "transcript": None, "prompt": None, "device": "web-app",
        "status": "ready", "sticker_ids": [], "created_at": now(),
    }
    res = await db().captures.insert_one(doc)
    return {"capture_id": str(res.inserted_id), "original_file_id": str(file_id)}


class SegmentIn(BaseModel):
    capture_id: str
    prompt: str | None = Field(default=None, max_length=80)  # "cup", "the red chair", … (optional)
    max_candidates: int = Field(default=8, ge=1, le=16)


@router.post("/segment", dependencies=[Depends(require_key)])
async def segment(body: SegmentIn):
    """Find the objects in a capture with SAM 3, ranked like the app's auto stickers (best first)."""
    _, _, small = await _load_capture(body.capture_id)
    prompt = (body.prompt or "").strip() or None
    async with _work:  # one GPU: queue behind the app's own capture processing
        seg = await _segmenter()
        cands = await asyncio.to_thread(seg.auto_masks, small, prompt)
    ranked = await asyncio.to_thread(rank_candidates, cands, small.shape[0], small.shape[1], body.max_candidates,
                                     named=bool(prompt))
    token, sess = _new_session(ObjectId(body.capture_id), small.shape[:2])
    sess.cands = ranked
    return {
        "token": token, "width": small.shape[1], "height": small.shape[0],
        "candidates": [_cand_out(i, c) for i, c in enumerate(ranked)],
    }


class PointSegIn(BaseModel):
    capture_id: str
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    token: str | None = None


@router.post("/segment/point", dependencies=[Depends(require_key)])
async def segment_point(body: PointSegIn):
    """Tap-to-cut, same as the app: SAM's point predictor, best of its multimask outputs."""
    sess = _session(body.token)
    if sess and str(sess.capture_id) != body.capture_id:
        sess = None
    _, _, small = await _load_capture(body.capture_id)
    async with _work:
        seg = await _segmenter()
        cand = await asyncio.to_thread(seg.mask_at_point, small, int(body.x * small.shape[1]), int(body.y * small.shape[0]))
    if cand is None:
        raise HTTPException(422, "Nothing to cut there")
    cand.rank_score = cand.quality
    if sess is None:
        token, sess = _new_session(ObjectId(body.capture_id), small.shape[:2])
    else:
        token = next(k for k, v in _SESSIONS.items() if v is sess)
    sess.cands.append(cand)
    i = len(sess.cands) - 1
    return {"token": token, "width": small.shape[1], "height": small.shape[0], "candidate": _cand_out(i, cand)}


class StickersIn(BaseModel):
    token: str
    indices: list[int] = Field(min_length=1, max_length=16)
    title: str | None = Field(default=None, max_length=120)


@router.post("/stickers", dependencies=[Depends(require_key)])
async def make_stickers(body: StickersIn):
    """Chosen candidates -> stickers, through the app's own _store_sticker (die-cut PNG, mask, metadata)."""
    sess = _session(body.token)
    if not sess:
        raise HTTPException(410, "Those cut-outs expired. Find objects again.")
    capture = await db().captures.find_one({"_id": sess.capture_id})
    if not capture:
        raise HTTPException(404, "Capture not found")
    full = await asyncio.to_thread(decode_rgb, await get_bytes(capture["original_file_id"]))
    h, w = full.shape[:2]
    sh, sw = sess.small_shape
    sx, sy = w / sw, h / sh
    created = []
    for i in dict.fromkeys(body.indices):  # de-duplicate, keep order
        if not 0 <= i < len(sess.cands):
            continue
        c = sess.cands[i]
        full_mask = await asyncio.to_thread(upscale_mask, c.mask, h, w)
        x, y, bw, bh = c.bbox
        c_full = MaskCandidate(full_mask, c.quality, (int(x * sx), int(y * sy), int(bw * sx), int(bh * sy)),
                               int(full_mask.sum()), c.rank_score)
        sid = await _store_sticker(capture, full, c_full, hero=False, source="web")
        if body.title:
            await db().stickers.update_one({"_id": sid}, {"$set": {"title": body.title}})
        created.append(sid)
    if not created:
        raise HTTPException(422, "No valid cut-outs chosen")
    await db().captures.update_one({"_id": capture["_id"]}, {"$push": {"sticker_ids": {"$each": created}}})
    docs = await db().stickers.find({"_id": {"$in": created}}, {"image_file_id": 1, "title": 1}).to_list(None)
    by_id = {d["_id"]: d for d in docs}
    return {"stickers": [{"id": str(s), "image_file_id": str(by_id[s]["image_file_id"]), "title": by_id[s].get("title") or ""}
                         for s in created if s in by_id]}
