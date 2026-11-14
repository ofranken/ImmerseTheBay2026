from fastapi import APIRouter, Depends, HTTPException

from ..access import sticker_out, sticker_visible
from ..db import db
from ..schemas import StickerPatch
from ..security import current_user
from ..storage import delete
from ..util import oid

router = APIRouter(prefix="/stickers", tags=["stickers"])


@router.get("")
async def list_stickers(scope: str = "mine", limit: int = 200, user=Depends(current_user)):
    """scope=mine: your stickers. scope=received: stickers friends shared with you."""
    if scope == "received":
        ids = [s["item_id"] async for s in db().shares.find({"to_id": user["_id"], "kind": "sticker"})]
        q = {"_id": {"$in": ids}}
    else:
        q = {"owner_id": user["_id"]}
    docs = await db().stickers.find(q).sort("created_at", -1).limit(min(limit, 500)).to_list(None)
    return [sticker_out(d) for d in docs]


@router.get("/{sticker_id}")
async def get_sticker(sticker_id: str, user=Depends(current_user)):
    s = await db().stickers.find_one({"_id": oid(sticker_id)})
    if not s or not await sticker_visible(user["_id"], s):
        raise HTTPException(404, "Not found")
    return sticker_out(s)


@router.patch("/{sticker_id}")
async def patch_sticker(sticker_id: str, body: StickerPatch, user=Depends(current_user)):
    upd = {k: v for k, v in body.model_dump().items() if v is not None}
    res = await db().stickers.find_one_and_update(
        {"_id": oid(sticker_id), "owner_id": user["_id"]}, {"$set": upd}, return_document=True
    )
    if not res:
        raise HTTPException(404, "Not found")
    return sticker_out(res)


@router.delete("/{sticker_id}")
async def delete_sticker(sticker_id: str, user=Depends(current_user)):
    s = await db().stickers.find_one({"_id": oid(sticker_id), "owner_id": user["_id"]})
    if not s:
        raise HTTPException(404, "Not found")
    await delete(s.get("image_file_id"))
    await delete(s.get("mask_file_id"))
    await db().stickers.delete_one({"_id": s["_id"]})
    await db().captures.update_one({"_id": s["capture_id"]}, {"$pull": {"sticker_ids": s["_id"]}})
    return {"ok": True}
