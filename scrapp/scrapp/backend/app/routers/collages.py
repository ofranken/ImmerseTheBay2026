import json
import secrets

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from ..access import collage_out, shared_with
from ..config import get_settings
from ..db import db
from ..security import current_user, file_url
from ..storage import delete, put_bytes
from ..util import clean, now, oid

router = APIRouter(prefix="/collages", tags=["collages"])
public = APIRouter(prefix="/public", tags=["public"])


def _scene(scene: str) -> dict:
    try:
        data = json.loads(scene)
    except json.JSONDecodeError:
        raise HTTPException(422, "scene must be JSON")
    if not isinstance(data, dict) or "items" not in data:
        raise HTTPException(422, "scene.items missing")
    return data


@router.post("")
async def create_collage(
    title: str = Form("Untitled collage"),
    scene: str = Form(...),
    thumbnail: UploadFile | None = File(None),
    user=Depends(current_user),
):
    thumb_id = None
    if thumbnail is not None:
        thumb_id = await put_bytes(await thumbnail.read(), "collage.png", "image/png", user["_id"], "collage_render")
    doc = {
        "owner_id": user["_id"], "title": title, "scene": _scene(scene),
        "thumbnail_file_id": thumb_id, "created_at": now(), "updated_at": now(),
    }
    res = await db().collages.insert_one(doc)
    doc["_id"] = res.inserted_id
    return collage_out(doc)


@router.put("/{collage_id}")
async def update_collage(
    collage_id: str,
    title: str = Form(...),
    scene: str = Form(...),
    thumbnail: UploadFile | None = File(None),
    user=Depends(current_user),
):
    c = await db().collages.find_one({"_id": oid(collage_id), "owner_id": user["_id"]})
    if not c:
        raise HTTPException(404, "Not found")
    upd = {"title": title, "scene": _scene(scene), "updated_at": now()}
    if thumbnail is not None:
        await delete(c.get("thumbnail_file_id"))
        upd["thumbnail_file_id"] = await put_bytes(await thumbnail.read(), "collage.png", "image/png", user["_id"], "collage_render")
    await db().collages.update_one({"_id": c["_id"]}, {"$set": upd})
    return collage_out({**c, **upd})


@router.get("")
async def list_collages(scope: str = "mine", user=Depends(current_user)):
    if scope == "received":
        ids = [s["item_id"] async for s in db().shares.find({"to_id": user["_id"], "kind": "collage"})]
        q = {"_id": {"$in": ids}}
    else:
        q = {"owner_id": user["_id"]}
    docs = await db().collages.find(q).sort("updated_at", -1).to_list(200)
    return [collage_out(d) for d in docs]


async def _resolve_scene_urls(scene: dict) -> dict:
    """Refresh signed URLs for every sticker/mesh referenced by the scene."""
    for item in scene.get("items", []):
        ref = item.get("ref_id")
        if not ref:
            continue
        if item.get("kind") == "sticker":
            s = await db().stickers.find_one({"_id": oid(ref)}, {"image_file_id": 1})
            item["url"] = file_url(s["image_file_id"]) if s else None
        elif item.get("kind") == "mesh":
            m = await db().meshes.find_one({"_id": oid(ref)}, {"glb_file_id": 1})
            item["url"] = file_url(m.get("glb_file_id")) if m else None
    return scene


@router.get("/{collage_id}")
async def get_collage(collage_id: str, user=Depends(current_user)):
    c = await db().collages.find_one({"_id": oid(collage_id)})
    if not c or (c["owner_id"] != user["_id"] and not await shared_with(user["_id"], "collage", c["_id"])):
        raise HTTPException(404, "Not found")
    c["scene"] = await _resolve_scene_urls(c["scene"])
    return collage_out(c)


@router.post("/{collage_id}/publish")
async def publish(collage_id: str, user=Depends(current_user)):
    """Creates an unlisted web-viewer link (spec: web viewer deployment)."""
    c = await db().collages.find_one({"_id": oid(collage_id), "owner_id": user["_id"]})
    if not c:
        raise HTTPException(404, "Not found")
    token = c.get("public_token") or secrets.token_urlsafe(12)
    await db().collages.update_one({"_id": c["_id"]}, {"$set": {"public_token": token}})
    return {"url": f"{get_settings().public_base_url}/c/{token}"}


@router.delete("/{collage_id}")
async def delete_collage(collage_id: str, user=Depends(current_user)):
    c = await db().collages.find_one({"_id": oid(collage_id), "owner_id": user["_id"]})
    if not c:
        raise HTTPException(404, "Not found")
    await delete(c.get("thumbnail_file_id"))
    await db().collages.delete_one({"_id": c["_id"]})
    return {"ok": True}


@public.get("/collages/{token}")
async def public_collage(token: str):
    c = await db().collages.find_one({"public_token": token})
    if not c:
        raise HTTPException(404, "Not found")
    scene = await _resolve_scene_urls(c["scene"])
    return {"title": c["title"], "scene": clean(scene)}
