"""Public collage link: viewer page + Open Graph tags, QR code, thumbnail, and the whole-scene GLB for browser AR."""
import json
import re

import cv2
import numpy as np

from app.config import get_settings


SCENE = json.dumps({"version": 1, "items": [], "zone": {"center": [0, 0.6, 0], "size": [1.2, 1.2, 1.2]}})
GLB = b"glTF" + b"\x02\x00\x00\x00" + b"\x00" * 60  # only the magic matters to the server


def _png() -> bytes:
    return cv2.imencode(".png", np.full((40, 60, 3), 200, np.uint8))[1].tobytes()


def _user(c, name):
    r = c.post("/auth/register", json={"username": name, "email": f"{name}@example.com", "password": "password1"})
    return {"Authorization": "Bearer " + r.json()["token"]}


def _collage(c, h, title="Trip <b>1</b>", thumb=True, glb=False, scene=SCENE):
    files = {}
    if thumb:
        files["thumbnail"] = ("t.png", _png(), "image/png")
    if glb:
        files["scene_glb"] = ("c.glb", GLB, "model/gltf-binary")
    r = c.post("/collages", headers=h, data={"title": title, "scene": scene}, files=files or None)
    assert r.status_code == 200, r.text
    return r.json()


def _publish(c, h, cid):
    url = c.post(f"/collages/{cid}/publish", headers=h).json()["url"]
    return url, url.rsplit("/", 1)[1]


def test_publish_returns_the_public_url(api):
    h = _user(api, "pub1")
    col = _collage(api, h)
    url, token = _publish(api, h, col["id"])
    BASE = get_settings().public_base_url
    assert url == f"{BASE}/c/{token}" and len(token) >= 12
    assert _publish(api, h, col["id"])[1] == token  # publishing again keeps the same link


def test_viewer_page_has_open_graph_tags_and_escapes_the_title(api):
    h = _user(api, "og1")
    token = _publish(api, h, _collage(api, h)["id"])[1]
    r = api.get(f"/c/{token}")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    page = r.text
    base = get_settings().public_base_url
    assert f'property="og:image" content="{base}/c/{token}/thumb.png"' in page
    assert 'property="og:title" content="Trip &lt;b&gt;1&lt;/b&gt;: a 3D collage on Scrapp"' in page  # escaped, no injection
    assert 'name="twitter:card" content="summary_large_image"' in page
    assert "<b>1</b>" not in page
    assert '<base href="/web/">' in page and f'"src": "/public/collages/{token}"' in page
    assert re.search(r'src="/web/editor\.js\?v=\d+"', page) and re.search(r'"/web/viewer_fx\.js": "/web/viewer_fx\.js\?v=\d+"', page)
    assert '"ar": false' in page


def test_page_without_a_thumbnail_has_no_image_tag(api):
    h = _user(api, "og2")
    token = _publish(api, h, _collage(api, h, thumb=False)["id"])[1]
    page = api.get(f"/c/{token}").text
    assert "og:image" not in page and 'content="summary"' in page
    assert api.get(f"/c/{token}/thumb.png").status_code == 404


def test_thumb_and_qr_are_pngs(api):
    h = _user(api, "png1")
    token = _publish(api, h, _collage(api, h)["id"])[1]
    thumb = api.get(f"/c/{token}/thumb.png")
    assert thumb.status_code == 200 and thumb.content == _png() and thumb.headers["access-control-allow-origin"] == "*"
    qr = api.get(f"/c/{token}/qr.png")
    assert qr.status_code == 200 and qr.content[:8] == b"\x89PNG\r\n\x1a\n" and qr.headers["content-type"] == "image/png"
    other = _publish(api, h, _collage(api, h, title="Other")["id"])[1]
    assert api.get(f"/c/{other}/qr.png").content != qr.content  # the code encodes this link


def test_scene_glb_upload_and_public_serving(api):
    h = _user(api, "glb1")
    plain = _collage(api, h, title="no ar")
    assert plain["has_scene_glb"] is False
    t_plain = _publish(api, h, plain["id"])[1]
    assert api.get(f"/c/{t_plain}/scene.glb").status_code == 404
    assert '"ar": false' in api.get(f"/c/{t_plain}").text and api.get(f"/public/collages/{t_plain}").json()["has_ar"] is False

    col = _collage(api, h, title="with ar", glb=True)
    assert col["has_scene_glb"] is True and "scene_glb_file_id" not in col  # the storage id is never exposed
    token = _publish(api, h, col["id"])[1]
    r = api.get(f"/c/{token}/scene.glb")
    assert r.status_code == 200 and r.content == GLB
    assert r.headers["content-type"] == "model/gltf-binary" and r.headers["access-control-allow-origin"] == "*"
    assert '"ar": true' in api.get(f"/c/{token}").text and api.get(f"/public/collages/{token}").json()["has_ar"] is True


def test_scene_glb_must_be_a_glb(api):
    h = _user(api, "glb2")
    r = api.post("/collages", headers=h, data={"title": "x", "scene": SCENE}, files={"scene_glb": ("c.glb", b"not a glb", "application/octet-stream")})
    assert r.status_code == 422


def test_resaving_replaces_or_drops_the_ar_model(api):
    h = _user(api, "glb3")
    col = _collage(api, h, glb=True)
    token = _publish(api, h, col["id"])[1]
    # same scene, new picture only (e.g. attaching a thumbnail): the AR model is kept
    r = api.put(f"/collages/{col['id']}", headers=h, data={"title": "t", "scene": SCENE}, files={"thumbnail": ("t.png", _png(), "image/png")})
    assert r.json()["has_scene_glb"] is True and api.get(f"/c/{token}/scene.glb").status_code == 200
    # a new AR model replaces the old one
    glb2 = b"glTF" + b"\x02\x00\x00\x00" + b"\x01" * 80
    api.put(f"/collages/{col['id']}", headers=h, data={"title": "t", "scene": SCENE}, files={"scene_glb": ("c.glb", glb2, "model/gltf-binary")})
    assert api.get(f"/c/{token}/scene.glb").content == glb2
    # the scene changed and no fresh model came with it: the stale model is dropped, not shown in AR
    changed = json.dumps({"version": 1, "items": [{"id": "a", "kind": "sticker", "ref_id": "x", "position": [0, 0, 0], "quaternion": [0, 0, 0, 1], "scale": 1}]})
    r = api.put(f"/collages/{col['id']}", headers=h, data={"title": "t", "scene": changed})
    assert r.json()["has_scene_glb"] is False and api.get(f"/c/{token}/scene.glb").status_code == 404


def test_unknown_and_unpublished_tokens_are_404(api):
    h = _user(api, "unpub")
    col = _collage(api, h, glb=True)  # exists but was never published: no token
    for path in ("", "/qr.png", "/thumb.png", "/scene.glb"):
        assert api.get(f"/c/nope-token{path}").status_code == 404
    assert api.get(f"/collages/{col['id']}", headers=h).json()["has_scene_glb"] is True
    assert api.get(f"/c/{col['id']}/scene.glb").status_code == 404  # an id is not a token


def test_deleting_a_collage_removes_its_public_link(api):
    h = _user(api, "del1")
    col = _collage(api, h, glb=True)
    token = _publish(api, h, col["id"])[1]
    assert api.delete(f"/collages/{col['id']}", headers=h).status_code == 200
    assert api.get(f"/c/{token}").status_code == 404 and api.get(f"/c/{token}/scene.glb").status_code == 404
