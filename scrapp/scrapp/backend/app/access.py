"""Who can see what, plus response shaping (adds signed media URLs)."""
from bson import ObjectId

from .db import db
from .security import file_url
from .util import clean


async def friend_ids(user_id: ObjectId) -> list[ObjectId]:
    out = []
    async for f in db().friendships.find({"status": "accepted", "$or": [{"requester_id": user_id}, {"addressee_id": user_id}]}):
        out.append(f["addressee_id"] if f["requester_id"] == user_id else f["requester_id"])
    return out


async def shared_with(user_id: ObjectId, kind: str, item_id: ObjectId) -> bool:
    return await db().shares.find_one({"to_id": user_id, "kind": kind, "item_id": item_id}) is not None


async def hunt_visible(user_id: ObjectId, hunt: dict) -> bool:
    return hunt["owner_id"] == user_id or await shared_with(user_id, "hunt", hunt["_id"])


async def sticker_visible(user_id: ObjectId, sticker: dict) -> bool:
    if sticker["owner_id"] == user_id or await shared_with(user_id, "sticker", sticker["_id"]):
        return True
    # Stickers inside a hunt shared with this user are visible too.
    async for h in db().hunts.find({"items.sticker_id": sticker["_id"]}, {"_id": 1, "owner_id": 1}):
        if await hunt_visible(user_id, h):
            return True
    return False


def sticker_out(s: dict) -> dict:
    d = clean(s)
    d["image_url"] = file_url(s.get("image_file_id"))
    d["mask_url"] = file_url(s.get("mask_file_id"))
    loc = s.get("location")
    if loc:
        d["lng"], d["lat"] = loc["coordinates"]
    return d


def capture_out(c: dict) -> dict:
    d = clean(c)
    d["original_url"] = file_url(c.get("original_file_id"))
    loc = c.get("location")
    if loc:
        d["lng"], d["lat"] = loc["coordinates"]
    return d


def collage_out(c: dict) -> dict:
    d = clean(c)
    d["thumbnail_url"] = file_url(c.get("thumbnail_file_id"))
    return d


def mesh_out(m: dict) -> dict:
    d = clean(m)
    d["glb_url"] = file_url(m.get("glb_file_id"))
    return d


def user_public(u: dict) -> dict:
    return {"id": str(u["_id"]), "username": u["username"], "display_name": u.get("display_name") or u["username"]}
