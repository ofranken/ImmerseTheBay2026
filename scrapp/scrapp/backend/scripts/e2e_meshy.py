"""End-to-end check of the Meshy flow against a running Scrapp server and tests/mock_meshy.py (no credits spent).

    uvicorn tests.mock_meshy:app --port 9100 &
    MESHY_API_KEY=test MESHY_BASE_URL=http://127.0.0.1:9100/openapi SEGMENTER=grabcut \\
        uvicorn app.main:app --port 8001 &
    python scripts/e2e_meshy.py http://127.0.0.1:8001 http://127.0.0.1:9100 USER PASSWORD
"""
import concurrent.futures as cf
import struct
import sys
import time

import httpx

base, mock, user, pw = sys.argv[1:5]
c = httpx.Client(base_url=base, timeout=60)
m = httpx.Client(base_url=mock, timeout=30)
fails = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global fails
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail and not ok else ""))
    fails += 0 if ok else 1


tok = c.post("/auth/login", json={"username_or_email": user, "password": pw}).json()["token"]
H = {"authorization": f"Bearer {tok}"}


def wait_done(mesh_id: str, timeout: int = 60) -> dict:
    end = time.time() + timeout
    stages = []
    while time.time() < end:
        d = c.get(f"/meshes/{mesh_id}", headers=H).json()
        if not stages or stages[-1] != (d["stage"], d["status"]):
            stages.append((d["stage"], d["status"]))
        if d.get("glb_url") or d["status"] in ("FAILED", "CANCELED"):
            d["_stages"] = stages
            return d
        time.sleep(0.4)
    raise TimeoutError(mesh_id)


# ---- text to 3D: preview -> refine -> stored GLB + thumbnail
r = c.post("/meshes/text", json={"prompt": "a tiny ceramic frog wearing a beret"}, headers=H)
check("text job accepted", r.status_code == 200 and r.json()["status"] == "PENDING", r.text[:120])
d = wait_done(r.json()["id"])
check("text job finishes with a GLB", bool(d.get("glb_url")), str(d))
check("went preview then refine", ("refine", "PENDING") in d["_stages"] or ("refine", "IN_PROGRESS") in d["_stages"], str(d["_stages"]))
glb = httpx.get(d["glb_url"]).content
check("GLB is served from OUR server, valid glTF", glb[:4] == b"glTF" and struct.unpack("<I", glb[4:8])[0] == 2, d["glb_url"][:60])
check("thumbnail is ours, not Meshy's", bool(d.get("thumbnail_url")) and "9100" not in d["thumbnail_url"], str(d.get("thumbnail_url")))
check("thumbnail downloads", httpx.get(d["thumbnail_url"]).content[:4] == b"\x89PNG")
text_id = d["id"]

# ---- exactly one refine per job, even when many polls land together
r = c.post("/meshes/text", json={"prompt": "a race between pollers"}, headers=H)
rid = r.json()["id"]
with cf.ThreadPoolExecutor(12) as ex:
    for _ in range(14):
        list(ex.map(lambda _: c.get(f"/meshes/{rid}", headers=H).status_code, range(12)))
        time.sleep(0.05)
d = wait_done(rid)
seen = m.get("/_debug/requests").json()
mine = [s for s in seen if s["kind"] == "refine"]
# refine bodies reference their preview task id; count refines for this job's preview
check("job with racing pollers finished", bool(d.get("glb_url")), str(d))
refs = {}
for s in mine:
    refs[s["body"]["preview_task_id"]] = refs.get(s["body"]["preview_task_id"], 0) + 1
check("no preview was refined (and billed) twice", all(n == 1 for n in refs.values()), str(refs))

# ---- sticker to 3D: a transparent cutout without the white outline
stickers = c.get("/stickers", params={"scope": "mine"}, headers=H).json()
used = {j.get("sticker_id") for j in c.get("/meshes", headers=H).json()}
stickers = [x for x in stickers if x["id"] not in used]  # pick one with no model yet
if stickers:
    r = c.post("/meshes/from-sticker", json={"sticker_id": stickers[0]["id"]}, headers=H)
    check("sticker job accepted", r.status_code == 200, r.text[:150])
    d = wait_done(r.json()["id"])
    check("sticker job finishes with a GLB", bool(d.get("glb_url")), str(d))
    again = c.post("/meshes/from-sticker", json={"sticker_id": stickers[0]["id"]}, headers=H)
    check("second tap on the same sticker returns the same job (no second charge)",
          again.status_code == 200 and again.json()["id"] == d["id"], again.text[:120])
    n_image = len([s for s in m.get("/_debug/requests").json() if s["kind"] == "image"])
    check("Meshy was asked for exactly one image-to-3D job", n_image == 1, str(n_image))
    img = [s for s in m.get("/_debug/requests").json() if s["kind"] == "image"][-1]
    import base64
    import io

    from PIL import Image

    png = Image.open(io.BytesIO(base64.b64decode(img["image_url"].split(",", 1)[1]))).convert("RGBA")
    px = png.load()
    check("cutout has a transparent corner", px[0, 0][3] == 0)
    opaque_white = sum(1 for x in range(png.width) for y in range(png.height) if px[x, y][3] > 200 and min(px[x, y][:3]) > 245)
    check("no white outline in what Meshy receives", opaque_white < 0.02 * png.width * png.height, f"{opaque_white} white px of {png.width * png.height}")
    check("upload is small enough", max(png.size) <= 1024, str(png.size))
else:
    print("SKIP sticker job (user has no stickers)")

# ---- failures read like sentences
r = c.post("/meshes/text", json={"prompt": "FAIL402 frog"}, headers=H)
check("402 -> 'out of credits' message", r.status_code == 402 and "credits" in r.json()["detail"], r.text[:150])
r = c.post("/meshes/text", json={"prompt": "FAIL429 frog"}, headers=H)
check("429 -> 'busy' message", r.status_code == 429 and "busy" in r.json()["detail"], r.text[:150])
r = c.post("/meshes/text", json={"prompt": "FAILTASK frog"}, headers=H)
d = wait_done(r.json()["id"])
check("failed job reports Meshy's reason", d["status"] == "FAILED" and "too complex" in (d.get("error") or ""), str(d))

# ---- per-user caps protect the credits
ids = []
for i in range(4):
    r = c.post("/meshes/text", json={"prompt": f"cap test {i}"}, headers=H)
    ids.append(r.status_code)
check("active-job cap kicks in", 429 in ids, str(ids))
for j in c.get("/meshes", headers=H).json():  # let them finish so later runs start clean
    if not j.get("glb_url") and j["status"] not in ("FAILED", "CANCELED"):
        try:
            wait_done(j["id"])
        except TimeoutError:
            pass

# ---- delete cleans up
r = c.delete(f"/meshes/{text_id}", headers=H)
check("delete works", r.status_code == 200 and c.get(f"/meshes/{text_id}", headers=H).status_code == 404)

print(f"\n{'ALL PASSED' if not fails else str(fails) + ' FAILED'}")
sys.exit(1 if fails else 0)
