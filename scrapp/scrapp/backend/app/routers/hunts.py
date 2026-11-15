"""Geo-tagged scavenger hunts built from stickers.

Creation: each item points at a sticker; the server crops the matching region out of the creator's
ORIGINAL photo and stores it as the item's visual target (used for glasses matching and as the
ARCore augmented-image reference on the phone).

Play: a friend says "scrap that" while the hunt is active -> POST /hunts/{id}/attempt with the
glasses photo + location -> geofence filter -> SIFT/homography match -> check-off.
"""
import asyncio
import logging
import uuid

import cv2
import numpy as np
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile

from ..access import capture_out, hunt_visible, sticker_out
from ..config import get_settings
from ..db import db
from ..schemas import HuntIn
from ..security import current_user, file_url
from ..services.embedding_match import get_embedder, match_embedding
from ..services.matching import crop_target, haversine_m, match
from ..services.pipeline import process_capture
from ..storage import delete as storage_delete, get_bytes, put_bytes
from ..util import clean, now, oid
from .captures import parse_meta, store_capture

log = logging.getLogger("scrapp.hunts")
router = APIRouter(prefix="/hunts", tags=["hunts"])


def _decode_bgr(data: bytes) -> np.ndarray:
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise HTTPException(422, "Could not decode image")
    return img


@router.post("")
async def create_hunt(body: HuntIn, user=Depends(current_user)):
    s = get_settings()
    items = []
    for it in body.items:
        st = await db().stickers.find_one({"_id": oid(it.sticker_id), "owner_id": user["_id"]})
        if not st:
            raise HTTPException(404, f"Sticker {it.sticker_id} not found")
        cap = await db().captures.find_one({"_id": st["capture_id"]})
        original = _decode_bgr(await get_bytes(cap["original_file_id"]))
        target = crop_target(original, st["bbox"])
        ok, jpg = cv2.imencode(".jpg", target, [cv2.IMWRITE_JPEG_QUALITY, 92])
        target_id = await put_bytes(jpg.tobytes(), "target.jpg", "image/jpeg", user["_id"], "hunt_target")
        items.append({
            "item_id": uuid.uuid4().hex[:12],
            "sticker_id": st["_id"],
            "capture_id": st["capture_id"],
            "target_file_id": target_id,
            "title": it.title or st.get("title") or "Mystery find",
            "hint": it.hint,
            "location": st.get("location"),
            "place_name": st.get("place_name"),
            "radius_m": it.radius_m or s.hunt_default_radius_m,
            "animation": it.animation,
        })
    doc = {"owner_id": user["_id"], "title": body.title, "description": body.description,
           "items": items, "created_at": now()}
    doc["_id"] = (await db().hunts.insert_one(doc)).inserted_id
    return await _hunt_out(doc, user["_id"])


async def _hunt_out(h: dict, user_id) -> dict:
    out = clean(h)
    progress = await db().hunt_progress.find_one({"hunt_id": h["_id"], "user_id": user_id})
    found = (progress or {}).get("found", {})
    items = []
    ids = [it["sticker_id"] for it in h["items"]]
    stickers = {s["_id"]: s async for s in db().stickers.find({"_id": {"$in": ids}})}  # one query, not one per item
    for it in h["items"]:
        st = stickers.get(it["sticker_id"])
        d = clean(it)
        d["sticker"] = sticker_out(st) if st else None
        d["target_url"] = file_url(it["target_file_id"])
        if it.get("location"):
            d["lng"], d["lat"] = it["location"]["coordinates"]
        d["found"] = it["item_id"] in found
        items.append(d)
    out["items"] = items
    out["found_count"] = len(found)
    out["total"] = len(items)
    out["started"] = progress is not None
    out["completed_at"] = (progress or {}).get("completed_at")
    out["completed"] = bool(out["total"]) and out["found_count"] == out["total"]
    out["is_owner"] = h["owner_id"] == user_id
    return out


@router.get("")
async def list_hunts(scope: str = "all", user=Depends(current_user)):
    if scope == "mine":
        q = {"owner_id": user["_id"]}
    else:
        shared = [s["item_id"] async for s in db().shares.find({"to_id": user["_id"], "kind": "hunt"})]
        q = {"_id": {"$in": shared}} if scope == "shared" else {"$or": [{"owner_id": user["_id"]}, {"_id": {"$in": shared}}]}
    hunts = await db().hunts.find(q).sort("created_at", -1).to_list(100)
    return [await _hunt_out(h, user["_id"]) for h in hunts]


async def _visible_hunt(hunt_id: str, user: dict) -> dict:
    h = await db().hunts.find_one({"_id": oid(hunt_id)})
    if not h or not await hunt_visible(user["_id"], h):
        raise HTTPException(404, "Not found")
    return h


@router.get("/{hunt_id}")
async def get_hunt(hunt_id: str, user=Depends(current_user)):
    return await _hunt_out(await _visible_hunt(hunt_id, user), user["_id"])


@router.post("/{hunt_id}/start")
async def start(hunt_id: str, user=Depends(current_user)):
    h = await _visible_hunt(hunt_id, user)
    await db().hunt_progress.update_one(
        {"hunt_id": h["_id"], "user_id": user["_id"]},
        {"$setOnInsert": {"found": {}, "started_at": now()}},
        upsert=True,
    )
    return await _hunt_out(h, user["_id"])


async def _mark_found(h: dict, user_id, item_id: str, method: str, capture_id=None) -> dict:
    await db().hunt_progress.update_one(
        {"hunt_id": h["_id"], "user_id": user_id},
        {"$set": {f"found.{item_id}": {"at": now(), "method": method, "capture_id": capture_id}},
         "$setOnInsert": {"started_at": now()}},
        upsert=True,
    )
    out = await _hunt_out(h, user_id)
    if out["completed"] and not out["completed_at"]:  # stamp once, never overwrite
        await db().hunt_progress.update_one(
            {"hunt_id": h["_id"], "user_id": user_id, "completed_at": {"$exists": False}}, {"$set": {"completed_at": now()}})
        out = await _hunt_out(h, user_id)  # report the stored value (Mongo keeps milliseconds)
    return out


@router.post("/{hunt_id}/attempt")
async def attempt(
    hunt_id: str,
    tasks: BackgroundTasks,
    image: UploadFile = File(...),
    meta: str = Form("{}"),
    scan: bool = False,
    user=Depends(current_user),
):
    """scan=true: a live phone-camera probe. A miss leaves nothing behind (no capture, no SAM run); a hit is kept as a capture."""
    s = get_settings()
    h = await _visible_hunt(hunt_id, user)
    m = parse_meta(meta)
    cap = await store_capture(user, image, m, {"hunt_id": h["_id"]})
    if not scan:
        tasks.add_task(process_capture, cap["_id"])  # still a normal scrapbook capture for the finder

    progress = await db().hunt_progress.find_one({"hunt_id": h["_id"], "user_id": user["_id"]}) or {}
    found = progress.get("found", {})
    query = _decode_bgr(await get_bytes(cap["original_file_id"]))

    best = None
    candidates = []  # (item, decoded target, object cut-out or None) for the unfound, in-range items
    out_of_range = 0
    for it in h["items"]:
        if it["item_id"] in found:
            continue
        loc = it.get("location")
        if loc and m.lat is not None and m.lng is not None:
            lng, lat = loc["coordinates"]
            slack = (m.accuracy_m or 0) + it.get("radius_m", s.hunt_default_radius_m)
            if haversine_m(lat, lng, m.lat, m.lng) > slack:
                out_of_range += 1
                continue
        target = _decode_bgr(await get_bytes(it["target_file_id"]))
        candidates.append((it, target, await _cutout(it)))
        r = await asyncio.to_thread(match, query, target, s.match_min_inliers, s.match_min_inlier_ratio)
        log.info("hunt %s attempt: SIFT item=%s inliers=%s ratio=%.2f matched=%s", h["_id"], it["item_id"], r.inliers, r.inlier_ratio, r.matched)
        if r.matched and (best is None or r.inliers > best[1].inliers):
            best = (it, r)

    if best is not None:  # SIFT is primary: precise on flat, textured targets
        item, r = best
        if scan:
            tasks.add_task(process_capture, cap["_id"])
        hunt = await _mark_found(h, user["_id"], item["item_id"], "glasses", cap["_id"])
        found_item = next(i for i in hunt["items"] if i["item_id"] == item["item_id"])
        return {"matched": True, "method": "sift", "item": found_item, "inliers": r.inliers, "capture": capture_out(cap), "hunt": hunt,
                "scan": {"status": "matched", "best_title": found_item["title"], "score": r.inliers, "threshold": s.match_min_inliers}}

    # SIFT missed: appearance matching (DINOv2) for 3D things seen from another angle, distance, light and background.
    scan_only_probe = scan
    scan = {"status": "none", "best_title": None, "score": 0.0, "threshold": s.embed_min_score, "out_of_range": out_of_range,
            "reason": "all remaining items are too far away" if (out_of_range and not candidates) else "nothing recognised"}
    embedder = get_embedder(s) if candidates else None
    if candidates and embedder is None:
        scan["reason"] = "object matching is unavailable on the server"
    if embedder is not None:
        entries = []
        for it, tgt, cut in candidates:
            entries.append((it["item_id"], str(it["target_file_id"]), tgt))
            if cut is not None:
                entries.append((it["item_id"], "cut:" + str(it["target_file_id"]), cut))
        er = await asyncio.to_thread(match_embedding, embedder, query, entries, s)
        titles = {it["item_id"]: it["title"] for it, _, _ in candidates}
        log.info("hunt %s attempt: DINO best=%s score=%.3f margin=%.3f standout=%.3f -> %s (min %.2f) ranking=%s", h["_id"], er.item_id,
                 er.score, er.margin, er.standout, er.reason, s.embed_min_score, er.ranking)
        scan.update(score=round(er.score, 3), best_title=titles.get(er.item_id), reason=er.reason,
                    margin=round(er.margin, 3), standout=round(er.standout, 3))
        if er.matched:
            if scan:
                tasks.add_task(process_capture, cap["_id"])
            hunt = await _mark_found(h, user["_id"], er.item_id, "glasses_embedding", cap["_id"])
            found_item = next(i for i in hunt["items"] if i["item_id"] == er.item_id)
            scan["status"] = "matched"
            return {"matched": True, "method": "embedding", "item": found_item, "score": round(er.score, 3),
                    "capture": capture_out(cap), "hunt": hunt, "scan": scan}
        if er.score >= s.embed_close_score:
            scan["status"] = "close"
    if scan_only_probe:
        await db().captures.delete_one({"_id": cap["_id"]})
        await storage_delete(cap["original_file_id"])
    return {"matched": False, "capture": capture_out(cap), "hunt": await _hunt_out(h, user["_id"]), "scan": scan}


async def _cutout(item: dict):
    """The hunt item's sticker (SAM cut-out) on neutral grey: the object without the creator's desk or room around it."""
    st = await db().stickers.find_one({"_id": item.get("sticker_id")}) if item.get("sticker_id") else None
    if not st or not st.get("image_file_id"):
        return None
    try:
        rgba = cv2.imdecode(np.frombuffer(await get_bytes(st["image_file_id"]), np.uint8), cv2.IMREAD_UNCHANGED)
        if rgba is None or rgba.ndim != 3 or rgba.shape[2] != 4:
            return None
        ys, xs = np.where(rgba[..., 3] > 16)
        if len(ys) == 0:
            return None
        rgba = rgba[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
        a = rgba[..., 3:4].astype(np.float32) / 255.0
        return (rgba[..., :3] * a + 128 * (1 - a)).astype(np.uint8)
    except Exception:  # noqa: BLE001 - optional extra view
        return None


@router.post("/{hunt_id}/items/{item_id}/found")
async def found(hunt_id: str, item_id: str, lat: float | None = None, lng: float | None = None,
                accuracy_m: float | None = None, user=Depends(current_user)):
    """Phone AR check-off: the phone tracked the item's target image, so the client vouches for the find.
    When it sends a location we still enforce the geofence."""
    h = await _visible_hunt(hunt_id, user)
    item = next((i for i in h["items"] if i["item_id"] == item_id), None)
    if not item:
        raise HTTPException(404, "No such item")
    loc = item.get("location")
    if loc and lat is not None and lng is not None:
        ilng, ilat = loc["coordinates"]
        slack = (accuracy_m or 0) + item.get("radius_m", get_settings().hunt_default_radius_m)
        if haversine_m(ilat, ilng, lat, lng) > slack:
            raise HTTPException(409, "You're too far from this find")
    return await _mark_found(h, user["_id"], item_id, "phone_ar")


@router.get("/{hunt_id}/progress")
async def hunt_progress(hunt_id: str, user=Depends(current_user)):
    """Owner only: how far each player has got."""
    h = await db().hunts.find_one({"_id": oid(hunt_id), "owner_id": user["_id"]})
    if not h:
        raise HTTPException(404, "Not found")
    total = len(h["items"])
    players = []
    async for p in db().hunt_progress.find({"hunt_id": h["_id"]}):
        u = await db().users.find_one({"_id": p["user_id"]})
        players.append({
            "user": {"id": str(p["user_id"]), "username": (u or {}).get("username"),
                     "display_name": (u or {}).get("display_name")},
            "found_count": len(p.get("found", {})), "total": total,
            "started_at": p.get("started_at"), "completed_at": p.get("completed_at"),
        })
    return {"hunt_id": hunt_id, "total": total, "players": players}


@router.delete("/{hunt_id}")
async def delete_hunt(hunt_id: str, user=Depends(current_user)):
    res = await db().hunts.delete_one({"_id": oid(hunt_id), "owner_id": user["_id"]})
    if not res.deleted_count:
        raise HTTPException(404, "Not found")
    await db().hunt_progress.delete_many({"hunt_id": oid(hunt_id)})
    await db().shares.delete_many({"kind": "hunt", "item_id": oid(hunt_id)})
    return {"ok": True}
