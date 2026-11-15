"""Appearance matching for hunts. Decision logic is tested with a stub embedder (fast, no model, no GPU); one smoke
test uses the real DINOv2 model on CPU and is skipped when it cannot be loaded (offline)."""
import json
import logging

import cv2
import numpy as np
import pytest

from app.config import Settings, get_settings
from app.services import embedding_match as em
from app.services.embedding_match import TargetCache, decide, match_embedding, query_views
from tests.test_matching import _artwork, _gallery_photo

LAT, LNG = 38.9404, -92.3277


def unit(*v):
    v = np.array(v, np.float32)
    return v / np.linalg.norm(v)


class ColorEmbedder:
    """Stub: an image's 'appearance' is its mean BGR colour. Counts calls so caching can be asserted."""

    def __init__(self):
        self.calls = 0

    def embed(self, images):
        self.calls += len(images)
        v = np.stack([im.reshape(-1, 3).mean(axis=0) + 1.0 for im in images]).astype(np.float32)
        return v / np.linalg.norm(v, axis=1, keepdims=True)


@pytest.fixture(autouse=True)
def reset_embedder():
    em.set_embedder(None)
    em.target_cache._d.clear()
    yield
    em.set_embedder(None)


# ------------------------------------------------------------------------------------------- decide()
T = {"cup": unit(1, 0, 0), "plant": unit(0, 1, 0), "chair": unit(0, 0, 1)}


def test_accepts_a_clear_winner():
    views = np.stack([unit(1, 0.05, 0), unit(0.3, 0.3, 0.3)])
    r = decide(views, T, min_score=0.5, margin=0.1, standout=0.1)
    assert r.matched and r.item_id == "cup" and r.score > 0.99 and r.reason == "ok"
    assert r.ranking[0][0] == "cup"


def test_rejects_below_min_score():
    views = np.stack([unit(1, 1, 1), unit(1, 1, 0.9)])
    r = decide(views, T, min_score=0.9, margin=0.0, standout=0.0)
    assert not r.matched and r.reason == "below min_score"


def test_rejects_when_two_items_look_alike():
    views = np.stack([unit(1, 0.98, 0)])  # equally close to cup and plant
    r = decide(views, T, min_score=0.5, margin=0.1, standout=0.0)
    assert not r.matched and "runner-up" in r.reason


def test_rejects_when_nothing_stands_out_from_the_frame():
    views = np.stack([unit(1, 0, 0)] * 4)  # every view equally similar: a generic frame
    r = decide(views, {"cup": unit(1, 0, 0)}, min_score=0.5, margin=0.1, standout=0.05)
    assert not r.matched and "stand out" in r.reason


def test_single_item_needs_no_runner_up():
    views = np.stack([unit(1, 0, 0), unit(0, 1, 0)])
    assert decide(views, {"cup": unit(1, 0, 0)}, 0.5, 0.5, 0.1).matched


def test_ranking_orders_items_by_best_view():
    views = np.stack([unit(1, 0.4, 0)])
    r = decide(views, T, 0.0, 0.0, 0.0)
    assert [i for i, _ in r.ranking] == ["cup", "plant", "chair"]


def test_no_items_is_not_a_match():
    assert not decide(np.stack([unit(1, 0, 0)]), {}, 0.1, 0.1, 0.1).matched


# ------------------------------------------------------------------------------------------- views, cache
def test_query_views_cover_whole_frame_centre_and_grid():
    img = np.zeros((480, 640, 3), np.uint8)
    views = query_views(img)
    assert len(views) == 6 and views[0].shape[:2] == (480, 640)
    assert all(v.shape[0] <= 480 and v.shape[1] <= 640 for v in views)
    assert len(query_views(np.zeros((20, 20, 3), np.uint8))) >= 1  # tiny frames do not crash


def test_target_cache_computes_once_and_evicts_oldest():
    c = TargetCache(maxsize=2)
    n = []
    mk = lambda k: (lambda: n.append(k) or np.ones(3))  # noqa: E731
    c.get("a", mk("a")); c.get("a", mk("a")); c.get("b", mk("b")); c.get("c", mk("c"))
    assert n == ["a", "b", "c"]
    c.get("a", mk("a"))  # evicted by c -> recomputed
    assert n == ["a", "b", "c", "a"]


def test_match_embedding_caches_target_embeddings_across_attempts():
    emb, cache, s = ColorEmbedder(), TargetCache(), get_settings()
    red = np.full((64, 64, 3), (0, 0, 200), np.uint8)
    query = np.full((200, 300, 3), 120, np.uint8)
    query[:, :150] = (0, 0, 200)
    items = [("i1", "file1", red)]
    match_embedding(emb, query, items, s, cache)
    first = emb.calls
    match_embedding(emb, query, items, s, cache)
    assert emb.calls - first == len(query_views(query))  # views again, but the target was not re-embedded
    assert cache.misses == 1


# ------------------------------------------------------------------------------------------- model availability
def test_unavailable_model_falls_back_and_logs_once(monkeypatch, caplog):
    boom = []

    def broken(*_a, **_k):
        boom.append(1)
        raise OSError("no weights offline")

    monkeypatch.setattr(em, "DinoEmbedder", broken)
    s = Settings(embed_enabled=True)
    with caplog.at_level(logging.WARNING, logger="scrapp.embedding"):
        assert em.get_embedder(s) is None
        assert em.get_embedder(s) is None
        assert em.get_embedder(s) is None
    assert len(boom) == 1, "a failed load must not be retried on every attempt"
    assert sum("SIFT only" in r.message for r in caplog.records) == 1


def test_disabled_never_loads(monkeypatch):
    monkeypatch.setattr(em, "DinoEmbedder", lambda *a, **k: pytest.fail("must not load when disabled"))
    assert em.get_embedder(Settings(embed_enabled=False)) is None


# ------------------------------------------------------------------------------------------- the /attempt flow
def _user(c, name):
    r = c.post("/auth/register", json={"username": name, "email": f"{name}@example.com", "password": "password1"})
    return {"Authorization": "Bearer " + r.json()["token"]}


def _jpg(img):
    return cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 95])[1].tobytes()


def _hunt_from_artwork(c, h, art):
    photo = np.full((600, 800, 3), 200, np.uint8)
    photo[150:450, 200:600] = art
    cap = c.post("/captures", headers=h, files={"image": ("o.jpg", _jpg(photo), "image/jpeg")},
                 data={"meta": json.dumps({"lat": LAT, "lng": LNG})}).json()

    async def seed():
        from app.db import db
        from app.util import now, oid
        owner = (await db().captures.find_one({"_id": oid(cap["id"])}))["owner_id"]
        res = await db().stickers.insert_one({
            "owner_id": owner, "capture_id": oid(cap["id"]), "title": "Painting", "bbox": [200, 150, 400, 300],
            "location": {"type": "Point", "coordinates": [LNG, LAT]}, "place_name": "Gallery", "created_at": now()})
        return str(res.inserted_id)

    sid = c.portal.call(seed)
    r = c.post("/hunts", headers=h, json={"title": "t", "items": [{"sticker_id": sid}]})
    assert r.status_code == 200, r.text
    return r.json()


def _attempt(c, h, hid, img):
    meta = json.dumps({"lat": LAT, "lng": LNG, "accuracy_m": 10})
    return c.post(f"/hunts/{hid}/attempt", headers=h, files={"image": ("a.jpg", _jpg(img), "image/jpeg")}, data={"meta": meta}).json()


def test_sift_stays_primary_even_with_an_embedder(api):
    h = _user(api, "prim01")
    art = _artwork(1)
    hunt = _hunt_from_artwork(api, h, art)
    em.set_embedder(ColorEmbedder())
    r = _attempt(api, h, hunt["id"], _gallery_photo(art))
    assert r["matched"] and r["method"] == "sift"


def test_embedding_catches_what_sift_misses(api, monkeypatch):
    monkeypatch.setenv("EMBED_ENABLED", "1")
    get_settings.cache_clear()
    h = _user(api, "emb01")
    art = _artwork(1)
    hunt = _hunt_from_artwork(api, h, art)
    em.set_embedder(ColorEmbedder())
    # A textureless frame: SIFT cannot match it, but its left half has the target's mean colour.
    target_color = art.reshape(-1, 3).mean(axis=0)
    frame = np.full((600, 800, 3), (10, 200, 10), np.uint8)
    frame[:, :400] = target_color.astype(np.uint8)
    r = _attempt(api, h, hunt["id"], frame)
    assert r["matched"] is True and r["method"] == "embedding" and r["score"] > 0.9
    assert r["hunt"]["completed"] is True


def test_no_embedder_means_plain_sift_miss(api, monkeypatch):
    monkeypatch.setenv("EMBED_ENABLED", "1")
    get_settings.cache_clear()
    h = _user(api, "emb02")
    hunt = _hunt_from_artwork(api, h, _artwork(1))
    monkeypatch.setattr(em, "DinoEmbedder", lambda *a, **k: (_ for _ in ()).throw(OSError("offline")))
    r = _attempt(api, h, hunt["id"], np.full((600, 800, 3), 90, np.uint8))
    assert r["matched"] is False and r["hunt"]["found_count"] == 0


# ------------------------------------------------------------------------------------------- real model
@pytest.fixture(scope="module")
def real():
    try:
        return em.DinoEmbedder(get_settings().embed_model, "cpu")
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"DINOv2 weights unavailable: {e}")


def test_real_model_prefers_the_same_artwork_under_a_new_viewpoint(real):
    art, other = _artwork(1), _artwork(2)
    target = real.embed([art])[0]
    same = real.embed(query_views(_gallery_photo(art)))
    diff = real.embed(query_views(_gallery_photo(other)))
    assert (same @ target).max() > (diff @ target).max()
    r = decide(same, {"a": target, "b": real.embed([other])[0]}, 0.0, 0.0, 0.0)
    assert r.item_id == "a"


def test_item_with_several_target_embeddings_uses_the_best_one():
    """Photo crop (desk and all) plus the object cut-out: a view matching either counts."""
    targets = {"mouse": np.vstack([unit(0, 1, 0), unit(1, 0, 0)]), "can": unit(0, 0, 1)}
    r = decide(np.stack([unit(1, 0.02, 0)]), targets, min_score=0.5, margin=0.1, standout=0.0)
    assert r.matched and r.item_id == "mouse" and r.score > 0.99
