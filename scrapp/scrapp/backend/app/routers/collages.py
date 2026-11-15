import json
import re
import secrets

from bson import ObjectId
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import ValidationError

from ..access import collage_out, shared_with
from ..config import get_settings
from ..db import db
from ..schemas import SceneBackground
from ..security import current_user, file_url
from ..storage import delete, put_bytes

MAX_SCENE_GLB_BYTES = 40 * 1024 * 1024  # the AR model of a whole collage; stickers are small, meshes dominate

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


async def _check_background(scene: dict, user: dict) -> None:
    """Validate scene.background in place: normalise it, or drop it when absent. A photo must be one of YOUR captures."""
    raw = scene.get("background")
    if raw is None:
        scene.pop("background", None)
        return
    try:
        bg = SceneBackground.model_validate(raw)
        if bg.type == "color" and not bg.value:
            raise ValueError("color needs a value")
        if bg.type == "gradient" and (not bg.colors or not all(re.fullmatch(r"#[0-9a-fA-F]{6}", c) for c in bg.colors)):
            raise ValueError("gradient needs 2-4 #rrggbb colors")
        if bg.type == "photo" and not bg.ref_id:
            raise ValueError("photo needs ref_id")
    except (ValueError, ValidationError) as e:
        raise HTTPException(422, f"Bad background: {e}")
    if bg.type == "photo":
        if not ObjectId.is_valid(bg.ref_id) or not await db().captures.find_one({"_id": ObjectId(bg.ref_id), "owner_id": user["_id"]}, {"_id": 1}):
            raise HTTPException(422, "Background photo not found")
    keep = {"color": ("value",), "paper": (), "gradient": ("colors", "angle"), "photo": ("ref_id",)}[bg.type]
    out = {"type": bg.type, **{k: getattr(bg, k) for k in keep if getattr(bg, k) is not None}}
    scene["background"] = out


async def _store_glb(upload: UploadFile, user: dict):
    data = await upload.read(MAX_SCENE_GLB_BYTES + 1)
    if len(data) > MAX_SCENE_GLB_BYTES:
        raise HTTPException(413, "The 3D scene file is too big")
    if data[:4] != b"glTF":
        raise HTTPException(422, "scene_glb must be a binary glTF (.glb) file")
    return await put_bytes(data, "collage.glb", "model/gltf-binary", user["_id"], "collage_scene_glb")


@router.post("")
async def create_collage(
    title: str = Form("Untitled collage"),
    scene: str = Form(...),
    thumbnail: UploadFile | None = File(None),
    scene_glb: UploadFile | None = File(None),
    user=Depends(current_user),
):
    scene_doc = _scene(scene)
    await _check_background(scene_doc, user)
    thumb_id = None
    if thumbnail is not None:
        thumb_id = await put_bytes(await thumbnail.read(), "collage.png", "image/png", user["_id"], "collage_render")
    doc = {
        "owner_id": user["_id"], "title": title, "scene": scene_doc,
        "thumbnail_file_id": thumb_id, "created_at": now(), "updated_at": now(),
    }
    if scene_glb is not None:
        doc["scene_glb_file_id"] = await _store_glb(scene_glb, user)
    res = await db().collages.insert_one(doc)
    doc["_id"] = res.inserted_id
    return collage_out(doc)


@router.put("/{collage_id}")
async def update_collage(
    collage_id: str,
    title: str = Form(...),
    scene: str = Form(...),
    thumbnail: UploadFile | None = File(None),
    scene_glb: UploadFile | None = File(None),
    user=Depends(current_user),
):
    c = await db().collages.find_one({"_id": oid(collage_id), "owner_id": user["_id"]})
    if not c:
        raise HTTPException(404, "Not found")
    scene_doc = _scene(scene)
    await _check_background(scene_doc, user)
    upd = {"title": title, "scene": scene_doc, "updated_at": now()}
    if thumbnail is not None:
        await delete(c.get("thumbnail_file_id"))
        upd["thumbnail_file_id"] = await put_bytes(await thumbnail.read(), "collage.png", "image/png", user["_id"], "collage_render")
    unset = {}
    if scene_glb is not None:
        new_glb = await _store_glb(scene_glb, user)
        await delete(c.get("scene_glb_file_id"))
        upd["scene_glb_file_id"] = new_glb
    elif c.get("scene_glb_file_id") and scene_doc != c.get("scene"):
        # The scene changed but no fresh AR model came with it: an old one would show the wrong collage in AR.
        await delete(c["scene_glb_file_id"])
        unset["scene_glb_file_id"] = ""
    await db().collages.update_one({"_id": c["_id"]}, {"$set": upd, **({"$unset": unset} if unset else {})})
    return collage_out({**{k: v for k, v in c.items() if k not in unset}, **upd})


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
    bg = scene.get("background")
    if isinstance(bg, dict) and bg.get("type") == "photo":
        ref = bg.get("ref_id")
        cap = await db().captures.find_one({"_id": ObjectId(ref)}, {"original_file_id": 1}) if ref and ObjectId.is_valid(ref) else None
        bg["url"] = file_url(cap["original_file_id"]) if cap else None  # fresh signed link; none if the photo was deleted
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
    await delete(c.get("scene_glb_file_id"))
    await db().collages.delete_one({"_id": c["_id"]})
    return {"ok": True}


@public.get("/collages/{token}")
async def public_collage(token: str):
    c = await db().collages.find_one({"public_token": token})
    if not c:
        raise HTTPException(404, "Not found")
    scene = await _resolve_scene_urls(c["scene"])
    return {"title": c["title"], "scene": clean(scene), "has_ar": bool(c.get("scene_glb_file_id"))}
