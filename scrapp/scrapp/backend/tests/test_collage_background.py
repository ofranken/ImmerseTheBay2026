"""Collage backdrops (scene.background): validation on save, signed photo URLs on read, public viewer, old collages unchanged."""
import json


def _user(c, name):
    r = c.post("/auth/register", json={"username": name, "email": f"{name}@example.com", "password": "password1"})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}, r.json()["user"]


def _capture(c, user):
    async def go():
        from app.db import db
        from app.storage import put_bytes
        from app.util import now, oid
        owner = oid(user["id"])
        fid = await put_bytes(b"\xff\xd8 fake jpeg", "p.jpg", "image/jpeg", owner, "original")
        r = await db().captures.insert_one({"owner_id": owner, "original_file_id": fid, "created_at": now()})
        return str(r.inserted_id)
    return c.portal.call(go)


def _post(c, h, background=..., title="t"):
    scene = {"items": []}
    if background is not ...:
        scene["background"] = background
    return c.post("/collages", headers=h, data={"title": title, "scene": json.dumps(scene)})


def test_old_collages_without_a_background_are_unchanged(api):
    h, _ = _user(api, "bg_old")
    r = _post(api, h)
    assert r.status_code == 200 and "background" not in r.json()["scene"]
    assert "background" not in api.get(f"/collages/{r.json()['id']}", headers=h).json()["scene"]
    assert "background" not in _post(api, h, None).json()["scene"]  # explicit null means none


def test_color_paper_and_gradient_round_trip(api):
    h, _ = _user(api, "bg_basic")
    cases = [
        ({"type": "color", "value": "#3E6B89"}, {"type": "color", "value": "#3E6B89"}),
        ({"type": "paper"}, {"type": "paper"}),
        ({"type": "gradient", "colors": ["#FFB36B", "#5B4B9A"], "angle": 180}, {"type": "gradient", "colors": ["#FFB36B", "#5B4B9A"], "angle": 180}),
        # Unknown / irrelevant keys are dropped, so a client cannot smuggle data into the scene.
        ({"type": "color", "value": "#000000", "colors": ["#fff", "#000"], "url": "http://evil", "ref_id": "x"}, {"type": "color", "value": "#000000"}),
    ]
    for sent, stored in cases:
        cid = _post(api, h, sent).json()["id"]
        assert api.get(f"/collages/{cid}", headers=h).json()["scene"]["background"] == stored


def test_bad_backgrounds_are_rejected(api):
    h, _ = _user(api, "bg_bad")
    for bad in [
        {"type": "color"},                                    # no value
        {"type": "color", "value": "red"},                    # not #rrggbb
        {"type": "color", "value": "#12345"},
        {"type": "gradient", "colors": ["#ffffff"]},          # needs 2-4
        {"type": "gradient", "colors": ["#ffffff", "blue"]},
        {"type": "gradient", "colors": ["#111111", "#222222"], "angle": 400},
        {"type": "photo"},                                    # no ref
        {"type": "video", "value": "#ffffff"},                # unknown type
        "paper",                                              # not an object
    ]:
        assert _post(api, h, bad).status_code == 422, bad


def test_photo_background_resolves_a_fresh_signed_url_and_shows_in_the_public_viewer(api):
    h, u = _user(api, "bg_photo")
    cap = _capture(api, u)
    created = _post(api, h, {"type": "photo", "ref_id": cap, "url": "http://stale.example/old"})
    assert created.status_code == 200
    assert created.json()["scene"]["background"] == {"type": "photo", "ref_id": cap}  # the stale url was not stored
    cid = created.json()["id"]

    bg = api.get(f"/collages/{cid}", headers=h).json()["scene"]["background"]
    assert bg["ref_id"] == cap and "/files/" in bg["url"] and "t=" in bg["url"]
    assert api.get(bg["url"]).status_code == 200                           # the link actually serves the image

    token = api.post(f"/collages/{cid}/publish", headers=h).json()["url"].rsplit("/", 1)[1]
    pub = api.get(f"/public/collages/{token}").json()["scene"]["background"]  # no login needed
    assert pub["ref_id"] == cap and pub["url"].startswith("http")


def test_photo_must_be_your_own_capture(api):
    a, au = _user(api, "bg_owner")
    b, _ = _user(api, "bg_other")
    cap = _capture(api, au)
    assert _post(api, b, {"type": "photo", "ref_id": cap}).status_code == 422     # someone else's photo
    assert _post(api, b, {"type": "photo", "ref_id": "not-an-id"}).status_code == 422
    assert _post(api, b, {"type": "photo", "ref_id": "6af90f12d417f7c888272971"}).status_code == 422  # valid id, no such capture


def test_deleted_photo_degrades_to_the_default_backdrop(api):
    h, u = _user(api, "bg_gone")
    cap = _capture(api, u)
    cid = _post(api, h, {"type": "photo", "ref_id": cap}).json()["id"]
    assert api.delete(f"/captures/{cap}", headers=h).status_code == 200
    got = api.get(f"/collages/{cid}", headers=h)
    assert got.status_code == 200                       # the collage still opens
    assert got.json()["scene"]["background"]["url"] is None  # the editor falls back to paper


def test_update_validates_and_can_clear_the_background(api):
    h, _ = _user(api, "bg_update")
    cid = _post(api, h, {"type": "color", "value": "#112233"}).json()["id"]
    bad = api.put(f"/collages/{cid}", headers=h, data={"title": "t", "scene": json.dumps({"items": [], "background": {"type": "color"}})})
    assert bad.status_code == 422
    ok = api.put(f"/collages/{cid}", headers=h, data={"title": "t", "scene": json.dumps({"items": []})})
    assert ok.status_code == 200
    assert "background" not in api.get(f"/collages/{cid}", headers=h).json()["scene"]
