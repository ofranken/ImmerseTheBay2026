"""Friends and sharing over HTTP: requests, accept, who can share what with whom, de-duplication, visibility."""

def _user(c, name):
    r = c.post("/auth/register", json={"username": name, "email": f"{name}@example.com", "password": "password1"})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}, r.json()["user"]


def _friends(c, a, b, b_user):
    assert c.post("/friends/request", headers=a, json={"username": b_user["username"]}).status_code == 200
    rid = c.get("/friends", headers=b).json()["incoming"][0]["request_id"]
    assert c.post(f"/friends/{rid}/accept", headers=b).status_code == 200


def _seed(c, owner_user, **docs):
    """Insert documents straight into the test database (segmentation and Meshy are out of scope here)."""
    async def go():
        from app.db import db
        from app.storage import put_bytes
        from app.util import now, oid
        owner = oid(owner_user["id"])
        out = {}
        if docs.get("sticker"):
            img = await put_bytes(b"\x89PNG fake", "s.png", "image/png", owner, "sticker")
            cap = await db().captures.insert_one({"owner_id": owner, "original_file_id": img, "created_at": now()})
            st = await db().stickers.insert_one({"owner_id": owner, "capture_id": cap.inserted_id, "image_file_id": img,
                                                 "title": "Cup", "bbox": [0, 0, 10, 10], "created_at": now()})
            out["sticker"] = str(st.inserted_id)
        if docs.get("mesh_done"):
            glb = await put_bytes(b"glTF fake", "m.glb", "model/gltf-binary", owner, "mesh")
            m = await db().meshes.insert_one({"owner_id": owner, "status": "SUCCEEDED", "glb_file_id": glb, "created_at": now()})
            out["mesh_done"] = str(m.inserted_id)
        if docs.get("mesh_pending"):
            m = await db().meshes.insert_one({"owner_id": owner, "status": "IN_PROGRESS", "created_at": now()})
            out["mesh_pending"] = str(m.inserted_id)
        return out

    return c.portal.call(go)


def _share(c, headers, to_ids, kind, item_id, **extra):
    return c.post("/shares", headers=headers, json={"to_user_ids": to_ids, "kind": kind, "item_id": item_id, **extra})


def test_friend_request_lifecycle(api):
    c = api
    a, au = _user(c, "alice1")
    b, bu = _user(c, "bobby1")
    assert c.post("/friends/request", headers=a, json={"username": "nobody99"}).status_code == 404
    assert c.post("/friends/request", headers=a, json={"username": "alice1"}).status_code == 404  # not yourself
    assert c.post("/friends/request", headers=a, json={"username": "BOBBY1"}).json() == {"status": "pending"}  # case-insensitive
    # Asking again reports the same pending request; it does not claim a new one was sent.
    assert c.post("/friends/request", headers=a, json={"username": "bobby1"}).json() == {"status": "pending"}
    assert c.get("/friends", headers=a).json() == {"friends": [], "incoming": []}
    inc = c.get("/friends", headers=b).json()["incoming"]
    assert [i["from"]["username"] for i in inc] == ["alice1"]
    # Only the addressee can accept.
    assert c.post(f"/friends/{inc[0]['request_id']}/accept", headers=a).status_code == 404
    assert c.post(f"/friends/{inc[0]['request_id']}/accept", headers=b).json() == {"status": "accepted"}
    assert [f["username"] for f in c.get("/friends", headers=a).json()["friends"]] == ["bobby1"]
    assert [f["username"] for f in c.get("/friends", headers=b).json()["friends"]] == ["alice1"]
    # Once friends, asking again says so.
    assert c.post("/friends/request", headers=a, json={"username": "bobby1"}).json() == {"status": "accepted"}


def test_mutual_requests_become_friends(api):
    c = api
    a, au = _user(c, "mutual_a")
    b, bu = _user(c, "mutual_b")
    c.post("/friends/request", headers=a, json={"username": "mutual_b"})
    assert c.post("/friends/request", headers=b, json={"username": "mutual_a"}).json() == {"status": "accepted"}
    assert len(c.get("/friends", headers=a).json()["friends"]) == 1


def test_user_search_excludes_yourself(api):
    c = api
    a, _ = _user(c, "searcher")
    _user(c, "searchee")
    assert [u["username"] for u in c.get("/users/search", params={"q": "search"}, headers=a).json()] == ["searchee"]


def test_sharing_rules_and_visibility(api):
    c = api
    a, au = _user(c, "owner01")
    b, bu = _user(c, "friend1")
    s, su = _user(c, "stranger")
    sticker = _seed(c, au, sticker=True)["sticker"]

    # Friends only; only your own items.
    assert _share(c, a, [bu["id"]], "sticker", sticker).status_code == 403
    _friends(c, a, b, bu)
    assert _share(c, b, [au["id"]], "sticker", sticker).status_code == 404
    assert c.get(f"/stickers/{sticker}", headers=b).status_code == 404  # not shared yet

    anchor = {"mode": "object", "object_class": "apple", "animation": "wiggle"}
    assert _share(c, a, [bu["id"]], "sticker", sticker, anchor=anchor, message="hi").json() == {"shared": 1}
    assert _share(c, a, [su["id"]], "sticker", sticker).status_code == 403

    # The friend sees it (inbox + direct fetch + "received" list); the stranger still does not.
    inbox = c.get("/shares/inbox", headers=b).json()
    assert len(inbox) == 1 and inbox[0]["from"]["username"] == "owner01" and inbox[0]["message"] == "hi"
    assert inbox[0]["anchor"]["object_class"] == "apple" and inbox[0]["item"]["image_url"]
    assert c.get(f"/stickers/{sticker}", headers=b).status_code == 200
    assert [x["id"] for x in c.get("/stickers?scope=received", headers=b).json()] == [sticker]
    assert c.get(f"/stickers/{sticker}", headers=s).status_code == 404

    # Mark seen.
    assert inbox[0]["seen_at"] is None
    assert c.post(f"/shares/{inbox[0]['id']}/seen", headers=b).status_code == 200
    assert c.get("/shares/inbox", headers=b).json()[0]["seen_at"] is not None


def test_resharing_updates_instead_of_duplicating(api):
    c = api
    a, au = _user(c, "resend_a")
    b, bu = _user(c, "resend_b")
    _friends(c, a, b, bu)
    sticker = _seed(c, au, sticker=True)["sticker"]
    _share(c, a, [bu["id"]], "sticker", sticker, anchor={"mode": "surface"}, message="one")
    first = c.get("/shares/inbox", headers=b).json()
    c.post(f"/shares/{first[0]['id']}/seen", headers=b)
    again = _share(c, a, [bu["id"], bu["id"]], "sticker", sticker, anchor={"mode": "geo"}, message="two")
    assert again.json() == {"shared": 1}  # the same friend listed twice is still one share
    inbox = c.get("/shares/inbox", headers=b).json()
    assert len(inbox) == 1
    assert inbox[0]["message"] == "two" and inbox[0]["anchor"]["mode"] == "geo"
    assert inbox[0]["seen_at"] is None  # unread again


def test_sharing_collages_and_3d_models(api):
    c = api
    a, au = _user(c, "maker01")
    b, bu = _user(c, "viewer1")
    _friends(c, a, b, bu)

    collage = c.post("/collages", headers=a, data={"title": "Trip", "scene": '{"items": []}'}).json()["id"]
    assert _share(c, a, [bu["id"]], "collage", collage).json() == {"shared": 1}

    meshes = _seed(c, au, mesh_done=True, mesh_pending=True)
    assert _share(c, a, [bu["id"]], "mesh", meshes["mesh_pending"]).status_code == 409  # not finished
    assert _share(c, a, [bu["id"]], "mesh", meshes["mesh_done"]).json() == {"shared": 1}

    kinds = {e["kind"]: e for e in c.get("/shares/inbox", headers=b).json()}
    assert set(kinds) == {"collage", "mesh"}
    assert kinds["collage"]["item"]["title"] == "Trip"
    assert kinds["mesh"]["item"]["glb_url"], "the friend needs a link to the model to preview it"
    assert "scene" in kinds["collage"]["item"]


def test_deleting_a_shared_item_drops_it_from_the_inbox(api):
    c = api
    a, au = _user(c, "deleter1")
    b, bu = _user(c, "deletee1")
    _friends(c, a, b, bu)
    collage = c.post("/collages", headers=a, data={"title": "Gone", "scene": '{"items": []}'}).json()["id"]
    _share(c, a, [bu["id"]], "collage", collage)
    assert len(c.get("/shares/inbox", headers=b).json()) == 1
    assert c.delete(f"/collages/{collage}", headers=a).status_code == 200
    assert c.get("/shares/inbox", headers=b).json() == []


def test_invalid_ids_are_rejected_cleanly(api):
    c = api
    a, au = _user(c, "badid_a")
    r = c.post("/shares", headers=a, json={"to_user_ids": ["nope"], "kind": "collage", "item_id": "also-nope"})
    assert r.status_code in (400, 404, 422)
    assert c.post("/friends/not-an-id/accept", headers=a).status_code in (400, 404, 422)
