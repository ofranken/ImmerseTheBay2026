import json
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile

from ..access import capture_out, sticker_out
from ..db import db
from ..schemas import CaptureMeta, PointIn
from ..security import current_user
from ..services.pipeline import process_capture, sticker_at_point
from ..storage import delete, put_bytes
from ..util import geo_point, now, oid

router = APIRouter(prefix="/captures", tags=["captures"])


def parse_meta(meta: str) -> CaptureMeta:
    try:
        return CaptureMeta.model_validate(json.loads(meta or "{}"))
    except Exception as e:
        raise HTTPException(422, f"Bad meta: {e}")


async def store_capture(user: dict, image: UploadFile, m: CaptureMeta, extra: dict | None = None) -> dict:
    data = await image.read()
    if not data:
        raise HTTPException(422, "Empty image")
    # The original is stored first and never rewritten: stickers, hunts and re-cuts all derive from it.
    file_id = await put_bytes(data, image.filename or "capture.jpg", image.content_type or "image/jpeg", user["_id"], "original")
    try:
        captured_at = datetime.fromisoformat(m.captured_at) if m.captured_at else now()
    except ValueError:
        captured_at = now()
    doc = {
        "owner_id": user["_id"],
        "original_file_id": file_id,
        "captured_at": captured_at,
        "location": geo_point(m.lat, m.lng),
        "accuracy_m": m.accuracy_m,
        "altitude_m": m.altitude_m,
        "place_name": m.place_name,
        "trigger": m.trigger,
        "transcript": m.transcript,
        "prompt": m.prompt,
        "device": m.device,
        "status": "processing",
        "sticker_ids": [],
        "created_at": now(),
        **(extra or {}),
    }
    res = await db().captures.insert_one(doc)
    doc["_id"] = res.inserted_id
    return doc


@router.post("")
async def create_capture(
    tasks: BackgroundTasks,
    image: UploadFile = File(...),
    meta: str = Form("{}"),
    user=Depends(current_user),
):
    doc = await store_capture(user, image, parse_meta(meta))
    tasks.add_task(process_capture, doc["_id"])
    return capture_out(doc)


@router.get("")
async def list_captures(limit: int = 50, before: str | None = None, user=Depends(current_user)):
    q = {"owner_id": user["_id"]}
    if before:
        q["captured_at"] = {"$lt": datetime.fromisoformat(before)}
    docs = await db().captures.find(q).sort("captured_at", -1).limit(min(limit, 200)).to_list(None)
    return [capture_out(d) for d in docs]


@router.get("/{capture_id}")
async def get_capture(capture_id: str, user=Depends(current_user)):
    c = await db().captures.find_one({"_id": oid(capture_id), "owner_id": user["_id"]})
    if not c:
        raise HTTPException(404, "Not found")
    out = capture_out(c)
    stickers = await db().stickers.find({"capture_id": c["_id"]}).sort("score", -1).to_list(None)
    out["stickers"] = [sticker_out(s) for s in stickers]
    return out


@router.post("/{capture_id}/reprocess")
async def reprocess(capture_id: str, tasks: BackgroundTasks, user=Depends(current_user)):
    c = await db().captures.find_one({"_id": oid(capture_id), "owner_id": user["_id"]})
    if not c:
        raise HTTPException(404, "Not found")
    await db().captures.update_one({"_id": c["_id"]}, {"$set": {"status": "processing", "error": None}})
    tasks.add_task(process_capture, c["_id"])
    return {"status": "processing"}


@router.post("/{capture_id}/point")
async def cut_at_point(capture_id: str, body: PointIn, user=Depends(current_user)):
    c = await db().captures.find_one({"_id": oid(capture_id), "owner_id": user["_id"]})
    if not c:
        raise HTTPException(404, "Not found")
    sid = await sticker_at_point(c, body.x, body.y)
    if sid is None:
        raise HTTPException(422, "Nothing to cut there")
    return sticker_out(await db().stickers.find_one({"_id": sid}))


@router.delete("/{capture_id}")
async def delete_capture(capture_id: str, user=Depends(current_user)):
    c = await db().captures.find_one({"_id": oid(capture_id), "owner_id": user["_id"]})
    if not c:
        raise HTTPException(404, "Not found")
    async for s in db().stickers.find({"capture_id": c["_id"]}):
        await delete(s.get("image_file_id"))
        await delete(s.get("mask_file_id"))
    await db().stickers.delete_many({"capture_id": c["_id"]})
    await delete(c["original_file_id"])
    await db().captures.delete_one({"_id": c["_id"]})
    return {"ok": True}
