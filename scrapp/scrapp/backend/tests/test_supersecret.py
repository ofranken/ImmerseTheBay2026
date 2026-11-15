"""/supersecret sticker maker: upload cap, rate limits, no second model, and stickers identical to the app's."""
import cv2
import numpy as np
import pytest

from app.routers import supersecret as ss
from app.services.segmentation import candidate_from_mask, make_sticker, upscale_mask


def _photo(w=640, h=480) -> bytes:
    img = np.full((h, w, 3), (200, 190, 170), np.uint8)
    cv2.circle(img, (320, 240), 90, (30, 60, 200), -1)
    cv2.rectangle(img, (40, 40), (140, 120), (20, 140, 40), -1)
    return cv2.imencode(".jpg", img)[1].tobytes()


class FakeSeg:
    """Stands in for SAM 3: a disc where you click, a canned text match."""
    def __init__(self):
        self.calls = []

    def _disc(self, shape, x, y, r):
        m = np.zeros(shape[:2], np.uint8)
        cv2.circle(m, (int(x), int(y)), r, 1, -1)
        return m.astype(bool)

    def masks_for_points(self, rgb, pts):
        self.calls.append(("points", pts))
        x, y, _ = pts[0]
        return [candidate_from_mask(self._disc(rgb.shape, x, y, r), q) for r, q in ((60, 0.9), (30, 0.8), (90, 0.7))]

    def auto_masks(self, rgb, prompt=None):
        self.calls.append(("text", prompt))
        return [candidate_from_mask(self._disc(rgb.shape, rgb.shape[1] // 4, rgb.shape[0] // 4, 70), 0.9)]


@pytest.fixture()
def client(api, monkeypatch):
    fake = FakeSeg()
    monkeypatch.setattr(ss, "get_segmenter", lambda: fake)
    ss.SESSIONS.clear()
    ss.limiter.hits.clear()
    api.fake = fake
    return api


def _upload(c, data=None, name="p.jpg"):
    return c.post("/supersecret/api/upload", files={"file": (name, data or _photo(), "image/jpeg")})


def test_page_is_served_unindexed(client):
    r = client.get("/supersecret")
    assert r.status_code == 200 and "STICKER MAKER" in r.text
    assert "noindex" in r.headers.get("x-robots-tag", "")
    assert client.get("/supersecret/").status_code == 200


def test_upload_rejects_non_images_and_oversize(client):
    assert _upload(client, b"not an image at all").status_code == 415
    big = b"\xff\xd8" + b"0" * (ss.MAX_UPLOAD_BYTES + 10)
    assert _upload(client, big).status_code == 413


def test_click_flow_returns_candidates_and_a_transparent_png(client):
    sid = _upload(client).json()["id"]
    r = client.post("/supersecret/api/points", json={"id": sid, "points": [{"x": 0.5, "y": 0.5, "positive": True}]})
    cands = r.json()["candidates"]
    assert r.status_code == 200 and len(cands) == 3 and cands[0]["overlay"] and cands[0]["thumb"]
    # a negative click is passed through as label 0
    client.post("/supersecret/api/points", json={"id": sid, "points": [{"x": 0.5, "y": 0.5, "positive": True}, {"x": 0.1, "y": 0.1, "positive": False}]})
    assert client.fake.calls[-1][1][1][2] == 0
    png = client.post("/supersecret/api/sticker", json={"id": sid, "mask_ids": [cands[0]["id"]], "download": True})
    assert png.status_code == 200 and "attachment" in png.headers["content-disposition"]
    im = cv2.imdecode(np.frombuffer(png.content, np.uint8), cv2.IMREAD_UNCHANGED)
    assert im.shape[2] == 4 and im[0, 0, 3] == 0 and im[..., 3].max() == 255  # transparent corner, opaque object


def test_exported_sticker_is_exactly_what_the_app_makes(client):
    """The app stores make_sticker(full_photo, upscale_mask(mask)); the export must be that PNG, byte for byte."""
    data = _photo()
    sid = _upload(client, data).json()["id"]
    cand = client.post("/supersecret/api/points", json={"id": sid, "points": [{"x": 0.5, "y": 0.5, "positive": True}]}).json()["candidates"][0]
    export = client.post("/supersecret/api/sticker", json={"id": sid, "mask_ids": [cand["id"]]}).content
    s = ss.SESSIONS[sid]
    expected, _ = make_sticker(s.full, upscale_mask(s.masks[cand["id"]], *s.full.shape[:2]))
    assert export == expected


def test_several_objects_become_one_sticker_sheet(client):
    sid = _upload(client).json()["id"]
    a = client.post("/supersecret/api/points", json={"id": sid, "points": [{"x": 0.5, "y": 0.5, "positive": True}]}).json()["candidates"][0]["id"]
    b = client.post("/supersecret/api/text", json={"id": sid, "prompt": "green box"}).json()["candidates"][0]["id"]
    one = client.post("/supersecret/api/sticker", json={"id": sid, "mask_ids": [a]}).content
    both = client.post("/supersecret/api/sticker", json={"id": sid, "mask_ids": [a, b]}).content
    assert len(both) > len(one) and both != one


def test_unknown_session_and_masks_are_friendly_errors(client):
    assert client.post("/supersecret/api/points", json={"id": "nope", "points": [{"x": .5, "y": .5}]}).status_code == 404
    sid = _upload(client).json()["id"]
    assert client.post("/supersecret/api/sticker", json={"id": sid, "mask_ids": ["gone"]}).status_code == 404
    assert client.post("/supersecret/api/points", json={"id": sid, "points": [{"x": .5, "y": .5, "positive": False}]}).status_code == 422


def test_rate_limits_return_429_with_retry_after(client, monkeypatch):
    monkeypatch.setitem(ss.limiter.limits, "upload", (3, 300))
    codes = [_upload(client).status_code for _ in range(5)]
    assert codes[:3] == [200, 200, 200] and codes[3:] == [429, 429]
    r = _upload(client)
    assert int(r.headers["retry-after"]) > 0 and "try again" in r.json()["detail"].lower()


def test_limiter_window_expires_and_is_per_client():
    lim = ss.RateLimiter({"x": (2, 10)})
    assert lim.check("a", "x", now=0) == 0 and lim.check("a", "x", now=1) == 0
    assert lim.check("a", "x", now=2) > 0           # third hit inside the window
    assert lim.check("b", "x", now=2) == 0          # another client is unaffected
    assert lim.check("a", "x", now=11.5) == 0       # window passed


def test_sessions_are_bounded(client):
    for _ in range(ss.MAX_SESSIONS + 3):
        _upload(client)
    assert len(ss.SESSIONS) <= ss.MAX_SESSIONS


def test_no_second_model_is_loaded():
    src = open(ss.__file__).read()
    assert "build_sam3_image_model" not in src and "Sam3Segmenter(" not in src  # only the shared get_segmenter()
