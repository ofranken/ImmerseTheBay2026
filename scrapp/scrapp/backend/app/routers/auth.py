import hmac

from fastapi import APIRouter, Depends, HTTPException
from pymongo.errors import DuplicateKeyError

from ..access import user_public
from ..config import get_settings
from ..db import db
from ..schemas import LoginIn, RegisterIn, TokenOut
from ..security import create_token, current_user, hash_password, verify_password
from ..util import now

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=TokenOut)
async def register(body: RegisterIn):
    required = get_settings().invite_code.strip()
    if required and not hmac.compare_digest((body.invite_code or "").strip().lower().encode(), required.lower().encode()):
        raise HTTPException(403, "Invalid invite code")
    doc = {
        "username": body.username.lower(),
        "email": body.email.lower(),
        "display_name": body.display_name or body.username,
        "password_hash": hash_password(body.password),
        "created_at": now(),
    }
    try:
        res = await db().users.insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(409, "Username or email already taken")
    doc["_id"] = res.inserted_id
    return {"token": create_token(str(res.inserted_id)), "user": user_public(doc)}


@router.post("/login", response_model=TokenOut)
async def login(body: LoginIn):
    key = body.username_or_email.lower()
    user = await db().users.find_one({"$or": [{"username": key}, {"email": key}]})
    if not user or not verify_password(body.password, user["password_hash"]):
        raise HTTPException(401, "Wrong username or password")
    return {"token": create_token(str(user["_id"])), "user": user_public(user)}


@router.get("/me")
async def me(user=Depends(current_user)):
    return user_public(user)
