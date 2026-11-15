"""Scavenger hunt HTTP flow against a throwaway local MongoDB (never the shared Atlas one).

Skipped when no local mongod answers on localhost:27017. SAM is stubbed: the sticker is inserted directly.
"""
import uuid

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient
from pymongo import MongoClient

from tests.test_matching import _artwork, _gallery_photo

LOCAL = "mongodb://localhost:27017"
LAT, LNG = 38.9404, -92.3277


def _jpg(img) -> bytes:
    return cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 95])[1].tobytes()


@pytest.fixture()
def api(monkeypatch):
    try:
        MongoClient(LOCAL, serverSelectionTimeoutMS=800).admin.command("ping")
    except Exception:
        pytest.skip("no local MongoDB")
    dbname = "scrapp_test_" + uuid.uuid4().hex[:8]
    monkeypatch.setenv("MONGO_URI", LOCAL)
    monkeypatch.setenv("MONGO_DB", dbname)
    monkeypatch.setenv("SCRAPP_SKIP_WARMUP", "1")
    from app import db as dbmod
    from app.config import get_settings
    get_settings.cache_clear()
    dbmod._client = None

    async def noop(*_a, **_k):
        return None

    import app.routers.captures as caps
    import app.routers.hunts as hunts
    monkeypatch.setattr(caps, "process_capture", noop)
    monkeypatch.setattr(hunts, "process_capture", noop)
    from app.main import app
    with TestClient(app) as c:
        yield c
    MongoClient(LOCAL).drop_database(dbname)
    get_settings.cache_clear()
    dbmod._client = None


def _user(c, name):
    r = c.post("/auth/register", json={"username": name, "email": f"{name}@example.com", "password": "password1"})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}, r.json()["user"]


def _befriend(c, a, b, b_user):
    assert c.post("/friends/request", headers=a, json={"username": b_user["username"]}).status_code == 200
    rid = c.get("/friends", headers=b).json()["incoming"][0]["request_id"]
    assert c.post(f"/friends/{rid}/accept", headers=b).status_code == 200


def _make_sticker(c, headers, art, place=(LAT, LNG)):
    """Creator's original photo with the artwork in it, plus a sticker pointing at that region."""
    photo = np.full((600, 800, 3), 200, np.uint8)
    photo[150:450, 200:600] = art
    meta = '{"lat": %f, "lng": %f}' % place
    cap = c.post("/captures", headers=headers, files={"image": ("o.jpg", _jpg(photo), "image/jpeg")}, data={"meta": meta}).json()

    async def seed():
        from app.db import db
        from app.util import oid, now
        res = await db().stickers.insert_one({
            "owner_id": oid(cap["owner_id"]) if "owner_id" in cap else (await db().captures.find_one({"_id": oid(cap["id"])}))["owner_id"],
            "capture_id": oid(cap["id"]), "title": "Painting", "bbox": [200, 150, 400, 300],
            "location": {"type": "Point", "coordinates": [place[1], place[0]]}, "place_name": "Gallery",
            "created_at": now(), "is_hero": True,
        })
        return str(res.inserted_id)

    return c.portal.call(seed)


def _hunt(c, headers, sticker_id, **kw):
    r = c.post("/hunts", headers=headers, json={"title": "Art walk", "items": [{"sticker_id": sticker_id, **kw}]})
    assert r.status_code == 200, r.text
    return r.json()


def _attempt(c, headers, hunt_id, img, lat=LAT, lng=LNG):
    meta = '{"lat": %f, "lng": %f, "accuracy_m": 10}' % (lat, lng) if lat is not None else "{}"
    return c.post(f"/hunts/{hunt_id}/attempt", headers=headers, files={"image": ("a.jpg", _jpg(img), "image/jpeg")}, data={"meta": meta})


def test_full_hunt_flow(api):
    c = api
    olivia, _ = _user(c, "olivia1")
    sam, sam_u = _user(c, "sam1234")
    art = _artwork(1)
    hunt = _hunt(c, olivia, _make_sticker(c, olivia, art), hint="by the door")
    hid = hunt["id"]
    assert hunt["total"] == 1 and hunt["found_count"] == 0 and hunt["completed"] is False and hunt["is_owner"]

    # Not shared yet: invisible to others, and to strangers even once friends exist elsewhere.
    assert c.get(f"/hunts/{hid}", headers=sam).status_code == 404
    _befriend(c, olivia, sam, sam_u)
    assert c.post("/shares", headers=olivia, json={"to_user_ids": [sam_u["id"]], "kind": "hunt", "item_id": hid}).json() == {"shared": 1}
    assert [h["id"] for h in c.get("/hunts?scope=shared", headers=sam).json()] == [hid]

    # The inbox card carries the full hunt, no refetch needed.
    inbox = c.get("/shares/inbox", headers=sam).json()
    assert inbox[0]["item"]["items"][0]["target_url"] and inbox[0]["item"]["total"] == 1

    assert c.post(f"/hunts/{hid}/start", headers=sam).json()["started"] is True

    # Wrong object: no match. Right object from another angle, at the spot: match and completion.
    miss = _attempt(c, sam, hid, _gallery_photo(_artwork(2))).json()
    assert miss["matched"] is False and miss["hunt"]["found_count"] == 0
    hit = _attempt(c, sam, hid, _gallery_photo(art)).json()
    assert hit["matched"] is True and hit["hunt"]["completed"] is True
    first_done = hit["hunt"]["completed_at"]
    assert first_done

    # Completion is stamped once.
    again = c.post(f"/hunts/{hid}/items/{hunt['items'][0]['item_id']}/found", headers=sam).json()
    assert again["completed_at"] == first_done

    # Owner sees the player's progress; the player does not.
    prog = c.get(f"/hunts/{hid}/progress", headers=olivia).json()
    assert prog["players"][0]["user"]["username"] == "sam1234" and prog["players"][0]["found_count"] == 1
    assert c.get(f"/hunts/{hid}/progress", headers=sam).status_code == 404

    # Deleting removes the hunt, progress and the share.
    assert c.delete(f"/hunts/{hid}", headers=sam).status_code == 404  # only the owner
    assert c.delete(f"/hunts/{hid}", headers=olivia).status_code == 200
    assert c.get("/hunts?scope=shared", headers=sam).json() == []
    assert c.get("/shares/inbox", headers=sam).json() == []


def test_geofence(api):
    c = api
    olivia, _ = _user(c, "olivia2")
    art = _artwork(1)
    hunt = _hunt(c, olivia, _make_sticker(c, olivia, art), radius_m=50)
    hid, iid = hunt["id"], hunt["items"][0]["item_id"]
    photo = _gallery_photo(art)

    far = _attempt(c, olivia, hid, photo, lat=LAT + 0.01, lng=LNG).json()  # ~1.1 km away
    assert far["matched"] is False
    nogps = _attempt(c, olivia, hid, photo, lat=None, lng=None).json()      # no location: not filtered
    assert nogps["matched"] is True

    # Phone AR check-off keeps the geofence when it sends a location.
    hunt2 = _hunt(c, olivia, _make_sticker(c, olivia, art), radius_m=50)
    h2, i2 = hunt2["id"], hunt2["items"][0]["item_id"]
    assert c.post(f"/hunts/{h2}/items/{i2}/found", params={"lat": LAT + 0.01, "lng": LNG}, headers=olivia).status_code == 409
    assert c.post(f"/hunts/{h2}/items/{i2}/found", params={"lat": LAT, "lng": LNG}, headers=olivia).json()["completed"] is True
    assert c.post(f"/hunts/{h2}/items/nope/found", headers=olivia).status_code == 404


def test_hunt_survives_a_deleted_sticker(api):
    c = api
    olivia, _ = _user(c, "olivia3")
    sid = _make_sticker(c, olivia, _artwork(1))
    hid = _hunt(c, olivia, sid)["id"]
    assert c.delete(f"/stickers/{sid}", headers=olivia).status_code == 200
    got = c.get(f"/hunts/{hid}", headers=olivia).json()
    assert got["items"][0]["sticker"] is None and got["items"][0]["target_url"]
