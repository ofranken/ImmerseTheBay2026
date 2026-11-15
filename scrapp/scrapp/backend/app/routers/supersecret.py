"""/supersecret: a small sticker-cutter web page for non-technical teammates (demo videos).

Upload a photo, click the object (or describe it), pick a cut, download a die-cut PNG sticker. It reuses the segmenter the
API already has loaded (never a second model on the GPU). There is no login by design (the URL is the gate), so it is
protected against abuse instead: per-IP rate limits, an upload size cap, a pixel cap, a small in-memory session cache and
one GPU job at a time.
"""
from __future__ import annotations

import asyncio
import base64
import collections
import secrets
import time
import uuid
from pathlib import Path

import cv2
import numpy as np
from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field

from ..config import get_settings
from ..services.segmentation import MaskCandidate, get_segmenter, make_sticker, rank_candidates, resize_for_model, upscale_mask

router = APIRouter(prefix="/supersecret", tags=["supersecret"], include_in_schema=False)

PAGE = Path(__file__).resolve().parent.parent / "static" / "supersecret.html"

MAX_UPLOAD_BYTES = 12 * 1024 * 1024      # request body cap
MAX_PIXELS = 50_000_000                  # reject absurd images before decoding them into memory
FULL_MAX_SIDE = 4096                     # the stored full-resolution copy (stickers are cut from this, like the app's originals)
MAX_SESSIONS = 6
SESSION_TTL_S = 3600
MAX_MASKS_PER_SESSION = 80
MAX_POINTS = 24
GPU_WAIT_S = 25

# (bucket, max events, window seconds) per client IP
LIMITS = {"upload": (10, 300), "segment": (60, 60), "sticker": (40, 60)}


# ------------------------------------------------------------------------------------------ rate limiting
class RateLimiter:
    """Sliding window per (client, bucket). In memory: fine for one server process."""

    def __init__(self, limits: dict[str, tuple[int, int]]):
        self.limits = limits
        self.hits: dict[tuple[str, str], collections.deque] = collections.defaultdict(collections.deque)

    def check(self, client: str, bucket: str, now: float | None = None) -> int:
        """Returns 0 if allowed (and records the hit), otherwise the seconds to wait."""
        now = time.monotonic() if now is None else now
        limit, window = self.limits[bucket]
        q = self.hits[(client, bucket)]
        while q and now - q[0] > window:
            q.popleft()
        if len(q) >= limit:
            return int(window - (now - q[0])) + 1
        q.append(now)
        if len(self.hits) > 5000:  # forget idle clients
            for k in [k for k, v in self.hits.items() if not v or now - v[-1] > 3600]:
                self.hits.pop(k, None)
        return 0


limiter = RateLimiter(LIMITS)
_gpu = asyncio.Semaphore(1)  # one segmentation job at a time, so the page can never starve the app's own captures


def client_ip(request: Request) -> str:
    return request.headers.get("cf-connecting-ip") or (request.client.host if request.client else "unknown")


def throttle(request: Request, bucket: str) -> None:
    wait = limiter.check(client_ip(request), bucket)
    if wait:
        raise HTTPException(429, f"Slow down a little: try again in {wait} seconds.", headers={"Retry-After": str(wait)})


# ------------------------------------------------------------------------------------------ sessions
class Session:
    def __init__(self, full_rgb: np.ndarray, small_rgb: np.ndarray):
        self.full = full_rgb
        self.small = small_rgb
        self.masks: collections.OrderedDict[str, np.ndarray] = collections.OrderedDict()  # mask id -> bool mask at small size
        self.touched = time.monotonic()


SESSIONS: collections.OrderedDict[str, Session] = collections.OrderedDict()


def _gc() -> None:
    now = time.monotonic()
    for sid in [k for k, s in SESSIONS.items() if now - s.touched > SESSION_TTL_S]:
        SESSIONS.pop(sid, None)
    while len(SESSIONS) > MAX_SESSIONS:
        SESSIONS.popitem(last=False)


def get_session(sid: str) -> Session:
    _gc()
    s = SESSIONS.get(sid)
    if s is None:
        raise HTTPException(404, "That photo expired. Please upload it again.")
    s.touched = time.monotonic()
    SESSIONS.move_to_end(sid)
    return s


def remember(s: Session, mask: np.ndarray) -> str:
    mid = uuid.uuid4().hex[:10]
    s.masks[mid] = mask
    while len(s.masks) > MAX_MASKS_PER_SESSION:
        s.masks.popitem(last=False)
    return mid


# ------------------------------------------------------------------------------------------ image helpers
def b64png(img: np.ndarray) -> str:
    ok, buf = cv2.imencode(".png", img)
    if not ok:
        raise RuntimeError("PNG encode failed")
    return base64.b64encode(buf.tobytes()).decode()


def overlay_png(mask: np.ndarray, color=(0xC5, 0xC1, 0x96)) -> str:
    """Tinted mask with an outline, as a transparent PNG the browser stacks on the photo. Colour is BGR (Scrapp teal)."""
    h, w = mask.shape
    out = np.zeros((h, w, 4), np.uint8)
    m = mask.astype(np.uint8)
    out[m > 0] = (*color, 120)
    cnts, _ = cv2.findContours(m, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    cv2.drawContours(out, cnts, -1, (0x88, 0x82, 0x4E, 255), max(2, round(max(h, w) / 420)))
    return b64png(out)


def thumb_png(rgb: np.ndarray, mask: np.ndarray, side: int = 150) -> str:
    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        return ""
    x0, x1, y0, y1 = xs.min(), xs.max() + 1, ys.min(), ys.max() + 1
    crop = rgb[y0:y1, x0:x1]
    a = (mask[y0:y1, x0:x1] * 255).astype(np.uint8)
    k = side / max(crop.shape[:2])
    if k < 1:
        crop, a = cv2.resize(crop, None, fx=k, fy=k, interpolation=cv2.INTER_AREA), cv2.resize(a, None, fx=k, fy=k, interpolation=cv2.INTER_AREA)
    return b64png(np.dstack([cv2.cvtColor(crop, cv2.COLOR_RGB2BGR), a]))


# ------------------------------------------------------------------------------------------ segmentation glue
async def run_gpu(fn, *args):
    try:
        await asyncio.wait_for(_gpu.acquire(), GPU_WAIT_S)
    except asyncio.TimeoutError:
        raise HTTPException(503, "The cutter is busy right now. Please try again in a moment.")
    try:
        return await asyncio.to_thread(fn, *args)
    finally:
        _gpu.release()


def candidates_out(s: Session, cands: list[MaskCandidate], limit: int) -> list[dict]:
    out = []
    for c in cands[:limit]:
        mid = remember(s, c.mask)
        out.append({"id": mid, "score": round(float(c.quality), 3), "area": round(float(c.mask.mean()), 4),
                    "overlay": overlay_png(c.mask), "thumb": thumb_png(s.small, c.mask)})
    return out


# ------------------------------------------------------------------------------------------ routes
@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse, include_in_schema=False)
async def page():
    return HTMLResponse(PAGE.read_text(encoding="utf-8"), headers={"Cache-Control": "no-store", "X-Robots-Tag": "noindex, nofollow"})


@router.post("/api/upload")
async def upload(request: Request, file: UploadFile = File(...)):
    throttle(request, "upload")
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_UPLOAD_BYTES + 4096:
        raise HTTPException(413, "That photo is too big. Please use one under 12 MB.")
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "That photo is too big. Please use one under 12 MB.")
    arr = np.frombuffer(data, np.uint8)
    head = cv2.imdecode(arr, cv2.IMREAD_REDUCED_COLOR_8)  # cheap decode first: rejects non-images without a full load
    if head is None:
        raise HTTPException(415, "That doesn't look like a photo. Try a JPG or PNG.")
    if head.shape[0] * head.shape[1] * 64 > MAX_PIXELS:
        raise HTTPException(413, "That photo has too many pixels. Please use a smaller one.")
    bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)  # applies EXIF orientation
    if bgr is None:
        raise HTTPException(415, "That doesn't look like a photo. Try a JPG or PNG.")
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    if max(rgb.shape[:2]) > FULL_MAX_SIDE:
        f = FULL_MAX_SIDE / max(rgb.shape[:2])
        rgb = cv2.resize(rgb, None, fx=f, fy=f, interpolation=cv2.INTER_AREA)
    small, _ = resize_for_model(rgb, get_settings().sam_max_side)
    sid = secrets.token_urlsafe(12)
    SESSIONS[sid] = Session(rgb, small)
    _gc()
    return {"id": sid, "width": int(small.shape[1]), "height": int(small.shape[0])}


class Point(BaseModel):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    positive: bool = True


class PointsIn(BaseModel):
    id: str
    points: list[Point] = Field(min_length=1, max_length=MAX_POINTS)


class TextIn(BaseModel):
    id: str
    prompt: str = Field(min_length=2, max_length=80)


@router.post("/api/points")
async def points(body: PointsIn, request: Request):
    throttle(request, "segment")
    s = get_session(body.id)
    if not any(p.positive for p in body.points):
        raise HTTPException(422, "Click on the thing you want first (a plus click).")
    h, w = s.small.shape[:2]
    pts = [(int(min(p.x, 0.9999) * w), int(min(p.y, 0.9999) * h), 1 if p.positive else 0) for p in body.points]
    seg = get_segmenter()
    if hasattr(seg, "masks_for_points"):
        cands = await run_gpu(seg.masks_for_points, s.small, pts)
    else:  # CPU development fallback (no SAM): one positive click only
        first = next(p for p in pts if p[2])
        one = await run_gpu(seg.mask_at_point, s.small, first[0], first[1])
        cands = [one] if one else []
    return {"candidates": candidates_out(s, cands, 3)}


@router.post("/api/text")
async def text(body: TextIn, request: Request):
    throttle(request, "segment")
    s = get_session(body.id)
    seg = get_segmenter()
    cands = await run_gpu(seg.auto_masks, s.small, body.prompt.strip())
    h, w = s.small.shape[:2]
    ranked = rank_candidates(cands, h, w, 6, named=True)
    return {"candidates": candidates_out(s, ranked, 6)}


class StickerIn(BaseModel):
    id: str
    mask_ids: list[str] = Field(min_length=1, max_length=12)
    preview: bool = False   # a smaller copy of the same PNG, only to keep the page snappy
    download: bool = False


@router.post("/api/sticker")
async def sticker(body: StickerIn, request: Request):
    """The exported sticker is exactly what the app makes: pipeline._store_sticker calls
    make_sticker(full_photo, upscale_mask(mask, h, w)); so do we. No other border, shadow or smoothing is applied here,
    so it cannot drift from the app's look. (The soft shadow you see around stickers inside the app is drawn by the
    Flutter widget at display time and is not part of the PNG.)"""
    throttle(request, "sticker")
    s = get_session(body.id)
    masks = [s.masks[m] for m in body.mask_ids if m in s.masks]
    if not masks:
        raise HTTPException(404, "Those cuts expired. Please click the object again.")
    union = np.logical_or.reduce(masks)
    h, w = s.full.shape[:2]

    def build():
        png, _crop = make_sticker(s.full, upscale_mask(union, h, w))
        if body.preview:
            im = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_UNCHANGED)
            if max(im.shape[:2]) > 900:
                f = 900 / max(im.shape[:2])
                im = cv2.resize(im, None, fx=f, fy=f, interpolation=cv2.INTER_AREA)
                png = cv2.imencode(".png", im)[1].tobytes()
        return png

    png = await asyncio.to_thread(build)
    headers = {"Cache-Control": "no-store"}
    if body.download:
        headers["Content-Disposition"] = 'attachment; filename="sticker.png"'
    return Response(png, media_type="image/png", headers=headers)
