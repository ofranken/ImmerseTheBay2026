import asyncio
import logging
from datetime import timedelta

import httpx
from fastapi import APIRouter, Depends, HTTPException

from ..access import mesh_out, sticker_visible
from ..config import get_settings
from ..db import db
from ..schemas import MeshFromStickerIn, MeshTextIn
from ..security import current_user
from ..services.meshy import MeshyClient, MeshyError
from ..services.pipeline import decode_rgb
from ..services.segmentation import cutout_png
from ..storage import delete, get_bytes, put_bytes
from ..util import now, oid

import cv2
import numpy as np

router = APIRouter(prefix="/meshes", tags=["meshes"])
log = logging.getLogger("scrapp.meshes")


def _client() -> MeshyClient:
    try:
        return MeshyClient()
    except RuntimeError as e:
        raise HTTPException(503, "3D generation is not set up on this server (no Meshy key).") from e


def _http_error(e: MeshyError) -> HTTPException:
    """Turn a Meshy failure into something the app can show to a person."""
    if e.status == 402:
        return HTTPException(402, "Meshy is out of credits. Ask the project owner to top them up.")
    if e.status == 429:
        return HTTPException(429, "Meshy is busy right now. Try again in a minute.")
    if e.status in (401, 403):
        log.error("Meshy rejected our request (%s): %s", e.status, e.message)
        return HTTPException(503, "The 3D service refused our request (key or plan problem). Tell the project owner.")
    if e.status == 400:
        return HTTPException(400, f"Meshy could not use that: {e.message}")
    log.warning("Meshy error %s: %s", e.status, e.message)
    return HTTPException(502, "The 3D service had a problem. Try again in a minute.")


async def _check_quota(user: dict) -> None:
    """Every job spends the project's credits and the API is public, so cap each user."""
    s = get_settings()
    uid = user["_id"]
    active = await db().meshes.count_documents(
        {"owner_id": uid, "status": {"$nin": ["FAILED", "CANCELED"]}, "glb_file_id": {"$exists": False}})
    if active >= s.meshy_max_active_per_user:
        raise HTTPException(429, f"You already have {active} models growing. Wait for one to finish.")
    today = await db().meshes.count_documents({"owner_id": uid, "created_at": {"$gte": now() - timedelta(days=1)}})
    if today >= s.meshy_daily_limit_per_user:
        raise HTTPException(429, f"Daily limit reached ({s.meshy_daily_limit_per_user} models). Try again tomorrow.")


@router.post("/text")
async def from_text(body: MeshTextIn, user=Depends(current_user)):
    client = _client()
    await _check_quota(user)
    try:
        task_id = await client.text_preview(body.prompt.strip())
    except MeshyError as e:
        raise _http_error(e) from e
    doc = {"owner_id": user["_id"], "source": "text", "prompt": body.prompt.strip(), "meshy_task_id": task_id,
           "stage": "preview", "status": "PENDING", "progress": 0, "created_at": now()}
    doc["_id"] = (await db().meshes.insert_one(doc)).inserted_id
    return mesh_out(doc)


async def _sticker_cutout(s: dict) -> bytes:
    """The object alone, transparent, no white outline. Falls back to the outlined sticker if the source is gone."""
    try:
        cap = await db().captures.find_one({"_id": s["capture_id"]})
        original = decode_rgb(await get_bytes(cap["original_file_id"]))
        mask = cv2.imdecode(np.frombuffer(await get_bytes(s["mask_file_id"]), np.uint8), cv2.IMREAD_GRAYSCALE) > 127
        if mask.shape != original.shape[:2]:
            raise ValueError("mask/photo size mismatch")
        return await asyncio.to_thread(cutout_png, original, mask)
    except Exception as e:  # noqa: BLE001 - any failure here just means "use the sticker as-is"
        log.warning("cutout for sticker %s failed (%s); sending the sticker image", s.get("_id"), e)
        return await get_bytes(s["image_file_id"])


@router.post("/from-sticker")
async def from_sticker(body: MeshFromStickerIn, user=Depends(current_user)):
    s = await db().stickers.find_one({"_id": oid(body.sticker_id)})
    if not s or not await sticker_visible(user["_id"], s):
        raise HTTPException(404, "Sticker not found")
    # One model per sticker: asking again returns the existing job, so a double tap never spends credits twice.
    # A failed or cancelled job doesn't count, so "try again" works.
    existing = await db().meshes.find_one(
        {"owner_id": user["_id"], "sticker_id": s["_id"], "status": {"$nin": ["FAILED", "CANCELED"]}},
        sort=[("created_at", -1)])
    if existing:
        return mesh_out(await _advance(existing))
    client = _client()
    await _check_quota(user)
    try:
        task_id = await client.image_to_3d(await _sticker_cutout(s))
    except MeshyError as e:
        raise _http_error(e) from e
    doc = {"owner_id": user["_id"], "source": "sticker", "sticker_id": s["_id"], "prompt": s.get("title"),
           "meshy_task_id": task_id, "stage": "image", "status": "PENDING", "progress": 0, "created_at": now()}
    doc["_id"] = (await db().meshes.insert_one(doc)).inserted_id
    return mesh_out(doc)


async def _fail(m: dict, message: str) -> dict:
    upd = {"status": "FAILED", "error": message}
    await db().meshes.update_one({"_id": m["_id"]}, {"$set": upd})
    return {**m, **upd}


def _task_error(task: dict) -> str:
    err = task.get("task_error") or {}
    return (err.get("message") or "Meshy could not make this model.")[:300]


async def _promote_to_refine(m: dict, client: MeshyClient) -> dict:
    """Preview finished -> start the textured refine. Exactly once, however many polls arrive together:
    the conditional update is the claim, and only the winner calls Meshy (each refine costs credits)."""
    claimed = await db().meshes.update_one(
        {"_id": m["_id"], "stage": "preview"},
        {"$set": {"stage": "refine", "status": "PENDING", "progress": 0,
                  "preview_task_id": m["meshy_task_id"], "meshy_task_id": None}})
    if claimed.modified_count != 1:
        return await db().meshes.find_one({"_id": m["_id"]}) or m  # someone else is promoting it
    try:
        refine_id = await client.text_refine(m["meshy_task_id"])
    except MeshyError as e:
        return await _fail(m, _http_error(e).detail)
    await db().meshes.update_one({"_id": m["_id"]}, {"$set": {"meshy_task_id": refine_id}})
    return await db().meshes.find_one({"_id": m["_id"]}) or m


async def _store_result(m: dict, task: dict, client: MeshyClient) -> dict:
    """Final task done: copy the GLB (and thumbnail) into our storage, because Meshy's links expire in days."""
    glb = (task.get("model_urls") or {}).get("glb")
    if not glb:
        return await _fail(m, "Meshy finished but returned no GLB model.")
    claimed = await db().meshes.update_one(
        {"_id": m["_id"], "glb_file_id": {"$exists": False}, "downloading": {"$ne": True}},
        {"$set": {"downloading": True, "status": "SUCCEEDED", "progress": 100}})
    if claimed.modified_count != 1:
        return await db().meshes.find_one({"_id": m["_id"]}) or m
    try:
        glb_id = await put_bytes(await client.download(glb), "model.glb", "model/gltf-binary", m["owner_id"], "mesh")
        upd: dict = {"glb_file_id": glb_id}
        thumb = task.get("thumbnail_url")
        if thumb:
            try:
                upd["thumb_file_id"] = await put_bytes(await client.download(thumb), "thumb.png", "image/png", m["owner_id"], "mesh_thumb")
            except httpx.HTTPError as e:
                log.warning("thumbnail download failed: %s", e)
        await db().meshes.update_one({"_id": m["_id"]}, {"$set": upd, "$unset": {"downloading": ""}})
    except httpx.HTTPError as e:
        log.warning("GLB download failed (will retry on the next poll): %s", e)
        await db().meshes.update_one({"_id": m["_id"]}, {"$unset": {"downloading": ""}})
    return await db().meshes.find_one({"_id": m["_id"]}) or m


async def _advance(m: dict) -> dict:
    """Poll Meshy once and move the job along: preview -> refine -> download. Safe to call from many pollers."""
    if m.get("glb_file_id") or m["status"] in ("FAILED", "CANCELED") or not m.get("meshy_task_id"):
        return m
    client = _client()
    try:
        task = await client.task(m["stage"], m["meshy_task_id"])
    except MeshyError as e:
        if e.status == 404:
            return await _fail(m, "Meshy lost this job (it may have expired).")
        log.warning("meshy poll failed: %s", e)
        return m
    status = task.get("status", m["status"])
    progress = int(task.get("progress") or 0)
    if status == "SUCCEEDED":
        return await (_promote_to_refine(m, client) if m["stage"] == "preview" else _store_result(m, task, client))
    if status in ("FAILED", "CANCELED"):
        await db().meshes.update_one({"_id": m["_id"]}, {"$set": {"status": status, "progress": progress, "error": _task_error(task)}})
        return {**m, "status": status, "error": _task_error(task)}
    await db().meshes.update_one({"_id": m["_id"]}, {"$set": {"status": status, "progress": progress}})
    return {**m, "status": status, "progress": progress}


@router.get("")
async def list_meshes(user=Depends(current_user)):
    docs = await db().meshes.find({"owner_id": user["_id"]}).sort("created_at", -1).to_list(200)
    return [mesh_out(d) for d in docs]


@router.get("/{mesh_id}")
async def get_mesh(mesh_id: str, user=Depends(current_user)):
    m = await db().meshes.find_one({"_id": oid(mesh_id), "owner_id": user["_id"]})
    if not m:
        raise HTTPException(404, "Not found")
    return mesh_out(await _advance(m))


@router.delete("/{mesh_id}")
async def delete_mesh(mesh_id: str, user=Depends(current_user)):
    m = await db().meshes.find_one({"_id": oid(mesh_id), "owner_id": user["_id"]})
    if not m:
        raise HTTPException(404, "Not found")
    await delete(m.get("glb_file_id"))
    await delete(m.get("thumb_file_id"))
    await db().meshes.delete_one({"_id": m["_id"]})
    return {"ok": True}
