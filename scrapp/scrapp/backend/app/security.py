from datetime import timedelta

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import get_settings
from .db import db
from .util import now, oid

_bearer = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())


def create_token(user_id: str) -> str:
    s = get_settings()
    payload = {"sub": user_id, "typ": "access", "exp": now() + timedelta(hours=s.jwt_ttl_hours)}
    return jwt.encode(payload, s.jwt_secret, algorithm="HS256")


def sign_file(file_id: str) -> str:
    """Short-lived token so phones, WebViews and the web viewer can load media with a plain URL."""
    s = get_settings()
    payload = {"f": file_id, "typ": "file", "exp": now() + timedelta(hours=s.file_url_ttl_hours)}
    return jwt.encode(payload, s.jwt_secret, algorithm="HS256")


def file_url(file_id) -> str | None:
    if not file_id:
        return None
    fid = str(file_id)
    return f"{get_settings().public_base_url}/files/{fid}?t={sign_file(fid)}"


def verify_file_token(file_id: str, token: str) -> bool:
    try:
        payload = jwt.decode(token, get_settings().jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        return False
    return payload.get("typ") == "file" and payload.get("f") == file_id


async def current_user(creds: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> dict:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing token")
    try:
        payload = jwt.decode(creds.credentials, get_settings().jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token")
    if payload.get("typ") != "access":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token")
    user = await db().users.find_one({"_id": oid(payload["sub"])})
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found")
    return user
