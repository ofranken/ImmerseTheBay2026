"""Friends, sharing and the inbox."""
import re

from fastapi import APIRouter, Depends, HTTPException
from pymongo.errors import DuplicateKeyError

import cv2
import numpy as np

from ..access import collage_out, friend_ids, mesh_out, sticker_out, user_public
from ..db import db
from ..schemas import FriendRequestIn, ShareIn
from ..security import current_user, file_url
from ..services.matching import crop_target
from ..storage import get_bytes, put_bytes
from ..util import clean, now, oid

router = APIRouter(tags=["social"])

KIND_COLLECTION = {"sticker": "stickers", "collage": "collages", "hunt": "hunts", "mesh": "meshes"}


@router.get("/users/search")
async def search_users(q: str, user=Depends(current_user)):
    pattern = "^" + re.escape(q.lower())
    docs = await db().users.find({"username": {"$regex": pattern}, "_id": {"$ne": user["_id"]}}).limit(10).to_list(None)
    return [user_public(u) for u in docs]


@router.get("/friends")
async def friends(user=Depends(current_user)):
    accepted = [user_public(u) for u in await db().users.find({"_id": {"$in": await friend_ids(user["_id"])}}).to_list(None)]
    incoming = []
    async for f in db().friendships.find({"addressee_id": user["_id"], "status": "pending"}):
        u = await db().users.find_one({"_id": f["requester_id"]})
        if u:
            incoming.append({"request_id": str(f["_id"]), "from": user_public(u)})
    return {"friends": accepted, "incoming": incoming}


@router.post("/friends/request")
async def request_friend(body: FriendRequestIn, user=Depends(current_user)):
    other = await db().users.find_one({"username": body.username.lower()})
    if not other or other["_id"] == user["_id"]:
        raise HTTPException(404, "No such user")
    reverse = await db().friendships.find_one({"requester_id": other["_id"], "addressee_id": user["_id"]})
    if reverse:  # they already asked: accept
        await db().friendships.update_one({"_id": reverse["_id"]}, {"$set": {"status": "accepted"}})
        return {"status": "accepted"}
    try:
        await db().friendships.insert_one({"requester_id": user["_id"], "addressee_id": other["_id"], "status": "pending", "created_at": now()})
    except DuplicateKeyError:
        pass
    return {"status": "pending"}


@router.post("/friends/{request_id}/accept")
async def accept(request_id: str, user=Depends(current_user)):
    res = await db().friendships.update_one({"_id": oid(request_id), "addressee_id": user["_id"]}, {"$set": {"status": "accepted"}})
    if not res.matched_count:
        raise HTTPException(404, "Not found")
    return {"status": "accepted"}


@router.post("/shares")
async def share(body: ShareIn, user=Depends(current_user)):
    item = await db()[KIND_COLLECTION[body.kind]].find_one({"_id": oid(body.item_id), "owner_id": user["_id"]})
    if not item:
        raise HTTPException(404, "You can only share your own items")
    friends = set(await friend_ids(user["_id"]))
    targets = [oid(t) for t in body.to_user_ids]
    if any(t not in friends for t in targets):
        raise HTTPException(403, "You can only share with friends")
    anchor = body.anchor.model_dump() if body.anchor else None
    if anchor and anchor["mode"] == "image" and body.kind == "sticker":
        # "On the exact thing": the receiver's AR camera tracks the region of the sender's original photo.
        cap = await db().captures.find_one({"_id": item["capture_id"]})
        original = cv2.imdecode(np.frombuffer(await get_bytes(cap["original_file_id"]), np.uint8), cv2.IMREAD_COLOR)
        ok, jpg = cv2.imencode(".jpg", crop_target(original, item["bbox"]), [cv2.IMWRITE_JPEG_QUALITY, 92])
        anchor["target_file_id"] = await put_bytes(jpg.tobytes(), "target.jpg", "image/jpeg", user["_id"], "share_target")
    docs = [{"from_id": user["_id"], "to_id": t, "kind": body.kind, "item_id": item["_id"], "anchor": anchor,
             "message": body.message, "seen_at": None, "created_at": now()} for t in targets]
    if docs:
        await db().shares.insert_many(docs)
    return {"shared": len(docs)}


@router.get("/shares/inbox")
async def inbox(user=Depends(current_user)):
    out = []
    async for s in db().shares.find({"to_id": user["_id"]}).sort("created_at", -1).limit(100):
        sender = await db().users.find_one({"_id": s["from_id"]})
        item = await db()[KIND_COLLECTION[s["kind"]]].find_one({"_id": s["item_id"]})
        if not item:
            continue
        if s["kind"] == "hunt":
            from .hunts import _hunt_out  # full item data so the card needs no refetch
            shaped = await _hunt_out(item, user["_id"])
        else:
            shaped = {"sticker": sticker_out, "collage": collage_out, "mesh": mesh_out}.get(s["kind"], clean)(item)
        entry = {**clean(s), "from": user_public(sender) if sender else None, "item": shaped}
        if s.get("anchor") and s["anchor"].get("target_file_id"):
            entry["anchor"]["target_url"] = file_url(s["anchor"]["target_file_id"])
        out.append(entry)
    return out


@router.post("/shares/{share_id}/seen")
async def seen(share_id: str, user=Depends(current_user)):
    await db().shares.update_one({"_id": oid(share_id), "to_id": user["_id"]}, {"$set": {"seen_at": now()}})
    return {"ok": True}
