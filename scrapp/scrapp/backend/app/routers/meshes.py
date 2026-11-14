import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException

from ..access import mesh_out, sticker_visible
from ..db import db
from ..schemas import MeshFromStickerIn, MeshTextIn
from ..security import current_user
from ..services.meshy import TERMINAL, MeshyClient
from ..storage import get_bytes, put_bytes
from ..util import now, oid

router = APIRouter(prefix="/meshes", tags=["meshes"])
log = logging.getLogger("scrapp.meshes")


def _client() -> MeshyClient:
    try:
        return MeshyClient()
    except RuntimeError as e:
        raise HTTPException(503, str(e))


@router.post("/text")
async def from_text(body: MeshTextIn, user=Depends(current_user)):
    task_id = await _client().text_preview(body.prompt, body.art_style)
    doc = {"owner_id": user["_id"], "source": "text", "prompt": body.prompt, "meshy_task_id": task_id,
           "stage": "preview", "status": "PENDING", "progress": 0, "created_at": now()}
    doc["_id"] = (await db().meshes.insert_one(doc)).inserted_id
    return mesh_out(doc)


@router.post("/from-sticker")
async def from_sticker(body: MeshFromStickerIn, user=Depends(current_user)):
    s = await db().stickers.find_one({"_id": oid(body.sticker_id)})
    if not s or not await sticker_visible(user["_id"], s):
        raise HTTPException(404, "Sticker not found")
    task_id = await _client().image_to_3d(await get_bytes(s["image_file_id"]))
    doc = {"owner_id": user["_id"], "source": "sticker", "sticker_id": s["_id"], "prompt": s.get("title"),
           "meshy_task_id": task_id, "stage": "image", "status": "PENDING", "progress": 0, "created_at": now()}
    doc["_id"] = (await db().meshes.insert_one(doc)).inserted_id
    return mesh_out(doc)


async def _advance(m: dict) -> dict:
    """Poll Meshy once; promote preview -> refine; download the GLB into GridFS when done."""
    if m["status"] in TERMINAL and (m["stage"] != "preview" or m["status"] != "SUCCEEDED"):
        return m
    client = _client()
    try:
        task = await client.task(m["stage"], m["meshy_task_id"])
    except httpx.HTTPError as e:
        log.warning("meshy poll failed: %s", e)
        return m
    upd = {"status": task.get("status", m["status"]), "progress": task.get("progress", m.get("progress", 0)),
           "thumbnail_url": task.get("thumbnail_url")}
    if upd["status"] == "SUCCEEDED" and m["stage"] == "preview":
        upd.update({"stage": "refine", "status": "PENDING", "progress": 0,
                    "preview_task_id": m["meshy_task_id"],
                    "meshy_task_id": await client.text_refine(m["meshy_task_id"])})
    elif upd["status"] == "SUCCEEDED":
        glb = (task.get("model_urls") or {}).get("glb")
        if glb and not m.get("glb_file_id"):
            upd["glb_file_id"] = await put_bytes(await client.download(glb), "model.glb", "model/gltf-binary", m["owner_id"], "mesh")
    elif upd["status"] in ("FAILED", "CANCELED"):
        upd["error"] = (task.get("task_error") or {}).get("message")
    await db().meshes.update_one({"_id": m["_id"]}, {"$set": upd})
    return {**m, **upd}


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
