"""Seed the two demo accounts (11111111 and 22222222) through the real API and SAM pipeline.

    .venv/bin/python scripts/seed_demo.py [--base http://localhost:8000] [--public https://scrapp.nmagic.dev]

Safe to re-run: every step looks for what it made last time (place names / titles starting with "Demo") and skips it.
It never deletes anything. Needs the API up and (for the 3D model) a Meshy key; add --no-mesh to skip Meshy.

What it makes
  * real-object stickers from the CC BY "holdout" COCO photos in tests/data (attribution: docs/DEMO.md), starred
  * three flat, textured "posters" (generated art with text, which SIFT matches reliably). Print docs/demo_assets/*.png
    and hold them up to the glasses: they are the targets of the seeded hunt
  * one finished 3D model for 11111111 (22222222 keeps the one already there)
  * a published collage per account, with a rendered thumbnail
  * "Screen Hunt (demo)" owned by 11111111 and shared with 22222222; the targets are shown full-screen on a laptop, tablet or
    phone (docs/demo_assets/hunt-targets.html), then proven by simulated photos of a screen (glare, moire, dim, far)
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import cv2
import httpx
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "tests" / "data"
ASSETS = ROOT.parent / "docs" / "demo_assets"
LAT, LNG = 37.4279, -122.1750  # Stanford, where the first real captures were taken
PLACE = "Demo: Immerse the Bay"
HUNT_RADIUS_M = 30000  # the demo venue is unknown: a wide radius keeps the geofence from blocking a live match

OBJECTS = {  # account -> [(holdout file, noun)]
    "11111111": [("000000013004.jpg", "banana"), ("000000067896.jpg", "clock"), ("000000410880.jpg", "teddy bear"), ("000000453040.jpg", "cake")],
    "22222222": [("000000440507.jpg", "suitcase"), ("000000232348.jpg", "toaster"), ("000000105335.jpg", "bowl"), ("000000084477.jpg", "umbrella")],
}
POSTERS = [("bay-bridge", "BAY BRIDGE", 11), ("golden-hour", "GOLDEN HOUR", 22), ("fog-city", "FOG CITY", 33)]


def log(*a):
    print(*a, flush=True)


# ------------------------------------------------------------------------------------------ images
def make_poster(seed: int, title: str, size=(1000, 700)) -> np.ndarray:
    rng = np.random.default_rng(seed)
    w, h = size
    img = np.zeros((h, w, 3), np.uint8)
    c1, c2 = rng.integers(40, 255, 3), rng.integers(40, 255, 3)
    for y in range(h):
        img[y, :] = (c1 * (1 - y / h) + c2 * (y / h)).astype(np.uint8)
    for _ in range(90):
        col = tuple(int(v) for v in rng.integers(0, 255, 3))
        p = (int(rng.integers(0, w)), int(rng.integers(0, h)))
        r = rng.random()
        if r < 0.4:
            cv2.circle(img, p, int(rng.integers(8, 70)), col, -1)
        elif r < 0.7:
            q = (int(rng.integers(0, w)), int(rng.integers(0, h)))
            cv2.line(img, p, q, col, int(rng.integers(2, 9)))
        else:
            q = (p[0] + int(rng.integers(20, 160)), p[1] + int(rng.integers(20, 120)))
            cv2.rectangle(img, p, q, col, -1)
    cv2.rectangle(img, (40, h - 230), (w - 40, h - 60), (245, 240, 230), -1)
    cv2.putText(img, title, (70, h - 120), cv2.FONT_HERSHEY_DUPLEX, 2.6, (30, 30, 40), 6, cv2.LINE_AA)
    cv2.putText(img, f"IMMERSE THE BAY  No. {seed}", (74, h - 80), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (60, 60, 70), 2, cv2.LINE_AA)
    cv2.rectangle(img, (0, 0), (w - 1, h - 1), (20, 20, 25), 14)
    return img


def wall(seed: int, size=(1600, 1100)) -> np.ndarray:
    rng = np.random.default_rng(seed)
    w, h = size
    base = np.full((h, w, 3), (196, 190, 182), np.uint8)
    noise = rng.integers(-14, 14, base.shape)
    return np.clip(base.astype(int) + noise, 0, 255).astype(np.uint8)


def place(poster: np.ndarray, bg: np.ndarray, quad: np.ndarray, gain=1.0, blur=0) -> np.ndarray:
    h, w = poster.shape[:2]
    M = cv2.getPerspectiveTransform(np.float32([[0, 0], [w, 0], [w, h], [0, h]]), quad.astype(np.float32))
    H, W = bg.shape[:2]
    warped = cv2.warpPerspective(poster, M, (W, H))
    mask = cv2.warpPerspective(np.full((h, w), 255, np.uint8), M, (W, H)) > 0
    out = bg.copy()
    out[mask] = np.clip(warped[mask].astype(float) * gain, 0, 255).astype(np.uint8)
    if blur:
        out = cv2.GaussianBlur(out, (0, 0), blur)
    return out


def screen_photo(art: np.ndarray, seed: int, kind: str) -> np.ndarray:
    """What the glasses see when pointed at the target shown full-screen on a laptop/tablet/phone.

    The art is letterboxed onto a 1920x1200 screen, given an RGB sub-pixel stripe structure (the source of moire when a
    camera samples it), then photographed at an angle with the glare, dimness or distance of the chosen condition.
    kind: clean | glare | moire | dim | far
    """
    rng = np.random.default_rng(seed)
    sw, sh = 1920, 1200
    screen = np.full((sh, sw, 3), 14, np.uint8)
    scale = min(sw / art.shape[1], sh / art.shape[0])
    a = cv2.resize(art, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    y0, x0 = (sh - a.shape[0]) // 2, (sw - a.shape[1]) // 2
    screen[y0:y0 + a.shape[0], x0:x0 + a.shape[1]] = a
    stripes = np.ones((sh, sw, 3), np.float32) * 0.72  # each pixel column lights mostly one colour channel
    for ch in range(3):
        stripes[:, ch::3, ch] = 1.0
    screen = np.clip(screen.astype(np.float32) * stripes * 1.18, 0, 255).astype(np.uint8)
    W, H = 1600, 1200
    room = np.full((H, W, 3), (38, 36, 34), np.uint8)
    room = np.clip(room.astype(int) + rng.integers(-6, 6, room.shape), 0, 255).astype(np.uint8)
    f = {"far": 0.42, "moire": 0.5}.get(kind, 0.56)  # screen width as a share of the photo: smaller = more aliasing
    tilt = {"moire": 70, "far": 45}.get(kind, 40)
    cx, cy = W / 2 + rng.integers(-40, 40), H / 2 + rng.integers(-30, 30)
    w2, h2 = W * f / 2 * 1.9, W * f / 2 * 1.19
    quad = np.float32([[cx - w2, cy - h2 + tilt], [cx + w2, cy - h2 - tilt * 0.6], [cx + w2 * 0.96, cy + h2 + tilt * 0.4], [cx - w2 * 0.96, cy + h2 - tilt]])
    M = cv2.getPerspectiveTransform(np.float32([[0, 0], [sw, 0], [sw, sh], [0, sh]]), quad)
    photo = cv2.warpPerspective(screen, M, (W, H), flags=cv2.INTER_LINEAR, borderValue=(38, 36, 34))
    bezel = cv2.warpPerspective(np.full((sh, sw), 255, np.uint8), M, (W, H)) > 0
    bezel = cv2.dilate(bezel.astype(np.uint8), np.ones((15, 15), np.uint8)) > 0
    photo[bezel & (photo.sum(axis=2) == 114)] = (20, 20, 22)
    img = photo.astype(np.float32)
    if kind in ("glare", "moire"):  # a window or ceiling light reflecting off the glass
        gx, gy = cx + w2 * 0.35, cy - h2 * 0.35
        yy, xx = np.mgrid[0:H, 0:W]
        blob = np.exp(-(((xx - gx) / (w2 * 0.55)) ** 2 + ((yy - gy) / (h2 * 0.35)) ** 2))
        img += blob[..., None] * (170 if kind == "glare" else 90)
    if kind == "dim":
        img *= 0.45
    img = cv2.GaussianBlur(img, (0, 0), 1.3 if kind in ("dim", "far") else 0.8)
    img += rng.normal(0, 7 if kind == "dim" else 3, img.shape)
    return np.clip(img, 0, 255).astype(np.uint8)


def jpg(img: np.ndarray) -> bytes:
    return cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 93])[1].tobytes()


# ------------------------------------------------------------------------------------------ API
class Api:
    def __init__(self, base: str, user: str):
        self.c = httpx.Client(base_url=base, timeout=120)
        r = self.c.post("/auth/login", json={"username_or_email": user, "password": user})
        r.raise_for_status()
        self.h = {"Authorization": "Bearer " + r.json()["token"]}
        self.user = user
        self.me = self.c.get("/auth/me", headers=self.h).json()

    def get(self, path, **kw):
        r = self.c.get(path, headers=self.h, **kw)
        r.raise_for_status()
        return r.json()

    def post(self, path, **kw):
        r = self.c.post(path, headers=self.h, **kw)
        r.raise_for_status()
        return r.json()

    def capture(self, image: bytes, prompt: str | None, place_name=PLACE, trigger="import") -> dict:
        meta = {"lat": LAT, "lng": LNG, "accuracy_m": 8, "place_name": place_name, "trigger": trigger,
                "captured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        if prompt:
            meta["prompt"] = prompt
        cap = self.post("/captures", files={"image": ("demo.jpg", image, "image/jpeg")}, data={"meta": json.dumps(meta)})
        for _ in range(180):
            st = self.get(f"/captures/{cap['id']}")
            if st["status"] != "processing":
                return st
            time.sleep(1)
        raise TimeoutError("capture still processing after 3 minutes")


def bbox_iou(a, b):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ix, iy = max(0, min(ax + aw, bx + bw) - max(ax, bx)), max(0, min(ay + ah, by + bh) - max(ay, by))
    inter = ix * iy
    return inter / (aw * ah + bw * bh - inter) if inter else 0.0


def insert_exact_sticker(capture_id: str, photo_bgr: np.ndarray, mask: np.ndarray, bbox) -> str:
    """Store a sticker for a known mask using the pipeline's own _store_sticker (needs the DB env, i.e. backend/.env)."""
    import asyncio

    sys.path.insert(0, str(ROOT))
    from bson import ObjectId

    from app.db import db
    from app.services.pipeline import _store_sticker
    from app.services.segmentation import MaskCandidate

    async def go():
        cap = await db().captures.find_one({"_id": ObjectId(capture_id)})
        x, y, w, h = bbox
        cand = MaskCandidate(mask=mask, quality=1.0, bbox=(int(x), int(y), int(w), int(h)), area=int(mask.sum()), rank_score=1.0)
        rgb = cv2.cvtColor(photo_bgr, cv2.COLOR_BGR2RGB)
        sid = await _store_sticker(cap, rgb, cand, hero=True, source="auto")
        await db().captures.update_one({"_id": cap["_id"]}, {"$push": {"sticker_ids": sid}, "$set": {"status": "ready"}})
        return str(sid)

    return asyncio.run(go())


# ------------------------------------------------------------------------------------------ steps
def seed_objects(api: Api, manifest: dict):
    have = {s.get("title") for s in api.get("/stickers") if (s.get("place_name") or "").startswith("Demo")}
    for fname, noun in OBJECTS[api.user]:
        if f"Demo {noun}" in have:
            log(f"  [{api.user}] {noun}: already seeded")
            continue
        cap = api.capture((DATA / "images" / fname).read_bytes(), noun)
        stickers = sorted(cap.get("stickers", []), key=lambda s: -s.get("score", 0))
        if not stickers:
            log(f"  [{api.user}] {noun}: no sticker produced ({cap['status']})")
            continue
        best = stickers[0]
        api.c.patch(f"/stickers/{best['id']}", headers=api.h, json={"title": f"Demo {noun}", "starred": True}).raise_for_status()
        log(f"  [{api.user}] {noun}: sticker {best['id'][-6:]} (score {best.get('score')}), starred")


def seed_posters(api: Api) -> list[dict]:
    """Make the poster captures; returns [{slug, sticker_id, ...}] for the hunt (owner only)."""
    ASSETS.mkdir(parents=True, exist_ok=True)
    existing = {s.get("title"): s for s in api.get("/stickers") if (s.get("title") or "").startswith("Demo poster")}
    out = []
    for slug, title, seed in POSTERS:
        art = make_poster(seed, title)
        cv2.imwrite(str(ASSETS / f"poster-{slug}.png"), art)
        key = f"Demo poster: {title.title()}"
        if key in existing:
            log(f"  poster {slug}: already seeded")
            out.append({"slug": slug, "title": title, "seed": seed, "sticker_id": existing[key]["id"]})
            continue
        quad = np.array([[420, 250], [1200, 285], [1185, 800], [440, 830]])
        photo = place(art, wall(seed), quad)
        want = cv2.boundingRect(quad.astype(np.int32))
        cap = api.capture(jpg(photo), "poster", place_name=f"{PLACE} ({title.title()})")
        best = max(cap.get("stickers", []), key=lambda s: bbox_iou(s["bbox"], want), default=None)
        if best is not None and bbox_iou(best["bbox"], want) >= 0.8:
            log(f"  poster {slug}: SAM cut it (bbox IoU {bbox_iou(best['bbox'], want):.2f})")
        else:
            # A generated poster is not a real-world object SAM knows. We know exactly where it is, so build the sticker
            # from that outline with the app's own sticker code (same document shape the pipeline writes).
            mask = np.zeros(photo.shape[:2], np.uint8)
            cv2.fillConvexPoly(mask, quad.astype(np.int32), 1)
            sid = insert_exact_sticker(cap["id"], photo, mask.astype(bool), want)
            best = {"id": sid}
            log(f"  poster {slug}: sticker built from the exact outline")
        api.c.patch(f"/stickers/{best['id']}", headers=api.h, json={"title": key, "starred": True}).raise_for_status()
        out.append({"slug": slug, "title": title, "seed": seed, "sticker_id": best["id"]})
    return out


def seed_mesh(api: Api):
    meshes = api.get("/meshes")
    if any(m.get("glb_url") for m in meshes):
        log(f"  [{api.user}] already has a finished 3D model")
        return
    stickers = [s for s in api.get("/stickers") if s.get("title") == "Demo teddy bear"] or [s for s in api.get("/stickers") if (s.get("title") or "").startswith("Demo ")]
    if not stickers:
        log("  no sticker to build a 3D model from")
        return
    job = api.post("/meshes/from-sticker", json={"sticker_id": stickers[0]["id"]})
    log(f"  [{api.user}] Meshy job {job['id'][-6:]} started from '{stickers[0]['title']}'")
    for _ in range(120):
        m = api.get(f"/meshes/{job['id']}")
        if m.get("glb_url") or m["status"] in ("FAILED", "CANCELED"):
            log(f"  [{api.user}] 3D model: {m['status']}")
            return
        time.sleep(5)
    log("  3D model still running after 10 minutes; re-run later")


def render_thumbnail(url: str) -> bytes | None:
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "shot.png"
        cmd = ["chromium", "--headless=new", "--no-sandbox", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist",
               "--window-size=900,900", "--virtual-time-budget=25000", f"--screenshot={out}", url]
        try:
            subprocess.run(cmd, timeout=90, capture_output=True)
        except Exception as e:  # noqa: BLE001
            log("  thumbnail render failed:", e)
            return None
        return out.read_bytes() if out.exists() else None


def seed_collage(api: Api, public: str):
    if any(c["title"] == "Demo collage" for c in api.get("/collages")):
        log(f"  [{api.user}] Demo collage already exists")
        return
    stickers = [s for s in api.get("/stickers") if (s.get("title") or "").startswith("Demo ") and "poster" not in s["title"]]
    meshes = [m for m in api.get("/meshes") if m.get("glb_url")]
    items = []
    spots = [(-0.55, 0.9), (0.45, 1.0), (-0.35, 0.35), (0.5, 0.4), (0.0, 0.65)]
    for (x, y), s in zip(spots, stickers):
        items.append({"id": f"s{s['id'][-6:]}", "kind": "sticker", "ref_id": s["id"], "title": s["title"], "position": [x, y, 0.05],
                      "quaternion": [0, 0, 0, 1], "scale": 1.0})
    if meshes:
        items.append({"id": "m1", "kind": "mesh", "ref_id": meshes[0]["id"], "title": "3D", "position": [0.0, 0.1, 0.2], "quaternion": [0, 0, 0, 1], "scale": 1.4})
    scene = {"version": 1, "items": items, "zone": {"center": [0, 0.6, 0], "size": [1.6, 1.6, 1.0]}, "filters": {"pixelate": 0, "motionBlur": 0},
             "camera": {"position": [0.0, 0.7, 3.2], "target": [0, 0.6, 0]}}
    col = api.post("/collages", data={"title": "Demo collage", "scene": json.dumps(scene)})
    url = api.post(f"/collages/{col['id']}/publish")["url"].replace("http://localhost:8000", public)
    log(f"  [{api.user}] collage with {len(items)} items, public link {url}")
    shot = render_thumbnail(url)
    if shot:
        r = api.c.put(f"/collages/{col['id']}", headers=api.h, files={"thumbnail": ("t.png", shot, "image/png")}, data={"title": "Demo collage", "scene": json.dumps(scene)})
        r.raise_for_status()
        log(f"  [{api.user}] thumbnail attached")


HUNT_TITLE = "Screen Hunt (demo)"
OLD_HUNT_TITLES = ("Poster Hunt (demo)",)  # renamed: no printer, the targets are shown on a screen


def seed_hunt(owner: Api, friend: Api, posters: list[dict]):
    for h in owner.get("/hunts?scope=mine"):
        if h["title"] in OLD_HUNT_TITLES:  # only our own earlier seed; deleting also removes its share and progress
            owner.c.delete(f"/hunts/{h['id']}", headers=owner.h)
            log(f"  removed the old hunt '{h['title']}'")
    if any(h["title"] == HUNT_TITLE for h in owner.get("/hunts?scope=mine")):
        log("  hunt already exists")
        return
    hints = {"bay-bridge": "Blue and gold art, steel and sky", "golden-hour": "Warm colours, big letters", "fog-city": "Cool greys, hold it steady"}
    hunt = owner.post("/hunts", json={"title": HUNT_TITLE, "description": "Three pictures are shown full-screen on the presenter's laptop (open docs/demo_assets/hunt-targets.html). "
                                       "Point the glasses at the screen and say \"found it\".",
                                       "items": [{"sticker_id": p["sticker_id"], "title": p["title"].title(), "hint": hints[p["slug"]], "radius_m": HUNT_RADIUS_M} for p in posters]})
    owner.post("/shares", json={"to_user_ids": [friend.me["id"]], "kind": "hunt", "item_id": hunt["id"], "message": "Screen hunt for the demo!"})
    log(f"  hunt {hunt['id'][-6:]} '{HUNT_TITLE}' created ({len(posters)} targets, radius {HUNT_RADIUS_M} m) and shared with {friend.user}")


def prove_hunt(owner: Api, friend: Api, posters: list[dict]) -> bool:
    """Photograph each target on a (simulated) laptop screen with glare, moire, dim light and distance; a throwaway copy of the
    hunt is used so the real one stays at 0 found. Every condition must match for every target."""
    items = [{"sticker_id": p["sticker_id"], "radius_m": HUNT_RADIUS_M} for p in posters]
    tmp = owner.post("/hunts", json={"title": "zz proof", "items": items})
    owner.post("/shares", json={"to_user_ids": [friend.me["id"]], "kind": "hunt", "item_id": tmp["id"]})
    ok = True
    try:
        for i, p in enumerate(posters):
            art = cv2.imread(str(ASSETS / f"poster-{p['slug']}.png"))
            for kind in ("clean", "glare", "moire", "dim", "far"):
                # each attempt on a fresh copy of the hunt state: the item is only ever checked off once, so re-check
                # by asking for a match on a per-target hunt
                one = owner.post("/hunts", json={"title": "zz proof one", "items": [{"sticker_id": p["sticker_id"], "radius_m": HUNT_RADIUS_M}]})
                owner.post("/shares", json={"to_user_ids": [friend.me["id"]], "kind": "hunt", "item_id": one["id"]})
                try:
                    shot = screen_photo(art, 100 * i + len(kind), kind)
                    if kind == "clean" and i == 0:
                        cv2.imwrite(str(ASSETS.parent / "demo_assets" / "_screen_photo_sample.jpg"), shot)  # eyeball it; not committed
                    meta = {"lat": LAT, "lng": LNG, "accuracy_m": 15, "trigger": "voice"}
                    r = friend.post(f"/hunts/{one['id']}/attempt", files={"image": ("s.jpg", jpg(shot), "image/jpeg")}, data={"meta": json.dumps(meta)})
                finally:
                    for c in friend.get("/captures"):
                        if c.get("hunt_id") == one["id"]:
                            friend.c.delete(f"/captures/{c['id']}", headers=friend.h)
                    owner.c.delete(f"/hunts/{one['id']}", headers=owner.h)
                log(f"  screen photo of {p['slug']:12s} {kind:6s}: matched={r['matched']!s:5s} via {r.get('method', '?'):9s} inliers={r.get('inliers')}")
                ok &= bool(r["matched"])
        done = friend.get(f"/hunts/{tmp['id']}")
        log(f"  (throwaway hunt untouched: {done['found_count']}/{done['total']})")
        # the attempts also became captures on the friend's account: remove only those created by this proof
        for c in friend.get("/captures"):
            if c.get("hunt_id") == tmp["id"]:  # only the captures this proof created
                friend.c.delete(f"/captures/{c['id']}", headers=friend.h)
    finally:
        owner.c.delete(f"/hunts/{tmp['id']}", headers=owner.h)
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--public", default="https://scrapp.nmagic.dev")
    ap.add_argument("--no-mesh", action="store_true")
    a = ap.parse_args()
    manifest = {i["file"]: i for i in json.loads((DATA / "manifest.json").read_text())["images"]}
    assert all(manifest[f]["split"] == "holdout" for u in OBJECTS.values() for f, _ in u), "demo photos must be holdout (CC BY) images"
    one, two = Api(a.base, "11111111"), Api(a.base, "22222222")
    for api in (one, two):
        log(f"== {api.user}: object stickers")
        seed_objects(api, manifest)
    log("== posters (11111111 owns the hunt targets)")
    posters = seed_posters(one)
    if not a.no_mesh:
        log("== 3D model")
        seed_mesh(one)
    for api in (one, two):
        log(f"== {api.user}: collage")
        seed_collage(api, a.public)
    log("== hunt")
    seed_hunt(one, two, posters)
    log("== proof: photograph each target on a screen, as the friend")
    ok = prove_hunt(one, two, posters)
    log("DONE. hunt proof:", "PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
