from datetime import datetime, timezone
from typing import Any

from bson import ObjectId
from fastapi import HTTPException


def now() -> datetime:
    return datetime.now(timezone.utc)


def oid(value: str | ObjectId) -> ObjectId:
    if isinstance(value, ObjectId):
        return value
    if not ObjectId.is_valid(value):
        raise HTTPException(status_code=404, detail="Not found")
    return ObjectId(value)


def clean(doc: Any) -> Any:
    """Recursively convert ObjectIds/datetimes so a Mongo doc is JSON-safe; renames _id to id."""
    if isinstance(doc, list):
        return [clean(d) for d in doc]
    if isinstance(doc, dict):
        out = {}
        for k, v in doc.items():
            if k == "_id":
                out["id"] = str(v)
            elif k == "password_hash":
                continue
            else:
                out[k] = clean(v)
        return out
    if isinstance(doc, ObjectId):
        return str(doc)
    if isinstance(doc, datetime):
        return doc.isoformat()
    return doc


def geo_point(lat: float | None, lng: float | None) -> dict | None:
    if lat is None or lng is None:
        return None
    return {"type": "Point", "coordinates": [lng, lat]}
