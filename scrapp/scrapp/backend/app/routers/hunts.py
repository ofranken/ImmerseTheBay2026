"""Geo-tagged scavenger hunts built from stickers.

Creation: each item points at a sticker; the server crops the matching region out of the creator's
ORIGINAL photo and stores it as the item's visual target (used for glasses matching and as the
ARCore augmented-image reference on the phone).

Play: a friend says "scrapbook that" while the hunt is active -> POST /hunts/{id}/attempt with the
glasses photo + location -> geofence filter -> SIFT/homography match -> check-off.
"""
import asyncio
import uuid

import cv2
import numpy as np
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile

from ..access import capture_out, hunt_visible, sticker_out
from ..config import get_settings
from ..db import db
from ..schemas import HuntIn
from ..security import current_user, file_url
from ..services.matching import crop_target, haversine_m, match
from ..services.pipeline import process_capture
from ..storage import get_bytes, put_bytes
from ..util import clean, now, oid
from .captures import parse_meta, store_capture

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
    for it in h["items"]:
        st = await db().stickers.find_one({"_id": it["sticker_id"]})
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
    if out["found_count"] == out["total"]:
        await db().hunt_progress.update_one({"hunt_id": h["_id"], "user_id": user_id}, {"$set": {"completed_at": now()}})
    return out


@router.post("/{hunt_id}/attempt")
async def attempt(
    hunt_id: str,
    tasks: BackgroundTasks,
    image: UploadFile = File(...),
    meta: str = Form("{}"),
    user=Depends(current_user),
):
    s = get_settings()
    h = await _visible_hunt(hunt_id, user)
    m = parse_meta(meta)
    cap = await store_capture(user, image, m, {"hunt_id": h["_id"]})
    tasks.add_task(process_capture, cap["_id"])  # still a normal scrapbook capture for the finder

    progress = await db().hunt_progress.find_one({"hunt_id": h["_id"], "user_id": user["_id"]}) or {}
    found = progress.get("found", {})
    query = _decode_bgr(await get_bytes(cap["original_file_id"]))

    best = None
    for it in h["items"]:
        if it["item_id"] in found:
            continue
        loc = it.get("location")
        if loc and m.lat is not None and m.lng is not None:
            lng, lat = loc["coordinates"]
            slack = (m.accuracy_m or 0) + it.get("radius_m", s.hunt_default_radius_m)
            if haversine_m(lat, lng, m.lat, m.lng) > slack:
                continue
        target = _decode_bgr(await get_bytes(it["target_file_id"]))
        r = await asyncio.to_thread(match, query, target, s.match_min_inliers, s.match_min_inlier_ratio)
        if r.matched and (best is None or r.inliers > best[1].inliers):
            best = (it, r)

    if best is None:
        return {"matched": False, "capture": capture_out(cap), "hunt": await _hunt_out(h, user["_id"])}
    item, r = best
    hunt = await _mark_found(h, user["_id"], item["item_id"], "glasses", cap["_id"])
    found_item = next(i for i in hunt["items"] if i["item_id"] == item["item_id"])
    return {"matched": True, "item": found_item, "inliers": r.inliers, "capture": capture_out(cap), "hunt": hunt}


@router.post("/{hunt_id}/items/{item_id}/found")
async def found(hunt_id: str, item_id: str, method: str = "phone_ar", user=Depends(current_user)):
    h = await _visible_hunt(hunt_id, user)
    if not any(i["item_id"] == item_id for i in h["items"]):
        raise HTTPException(404, "No such item")
    return await _mark_found(h, user["_id"], item_id, method)


@router.delete("/{hunt_id}")
async def delete_hunt(hunt_id: str, user=Depends(current_user)):
    res = await db().hunts.delete_one({"_id": oid(hunt_id), "owner_id": user["_id"]})
    if not res.deleted_count:
        raise HTTPException(404, "Not found")
    await db().hunt_progress.delete_many({"hunt_id": oid(hunt_id)})
    return {"ok": True}
