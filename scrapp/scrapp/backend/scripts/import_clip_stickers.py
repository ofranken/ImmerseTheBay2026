"""Add hand-made sticker PNGs (media/) to an account as if they had arrived as glasses clips.

    .venv/bin/python scripts/import_clip_stickers.py [--user 22222222]

The PNGs are stored exactly as given (they already have their white die-cut edge, so make_sticker is NOT applied). Each one gets a
capture of its own (the app expects every sticker to belong to a capture) and is starred so it shows in the Book. Re-running skips
titles the account already has.
"""
import argparse
import asyncio
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db import db  # noqa: E402
from app.services.segmentation import mask_png  # noqa: E402
from app.storage import put_bytes  # noqa: E402
from app.util import now  # noqa: E402

MEDIA = ROOT.parent / "media"
TITLES = {"scrapp-sticker (1).png": "Bronze statue", "scrapp-sticker (2).png": "City map", "scrapp-sticker.png": "Palm tree"}


async def main(user: str):
    u = await db().users.find_one({"username": user})
    if not u:
        raise SystemExit(f"no such user {user}")
    have = {s.get("title") async for s in db().stickers.find({"owner_id": u["_id"]}, {"title": 1})}
    for fname, title in TITLES.items():
        if title in have:
            print(f"skip {title}: already there")
            continue
        data = (MEDIA / fname).read_bytes()
        im = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_UNCHANGED)
        h, w = im.shape[:2]
        alpha = im[..., 3] > 127
        ys, xs = np.nonzero(alpha)
        bbox = [int(xs.min()), int(ys.min()), int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1)]
        img_id = await put_bytes(data, fname, "image/png", u["_id"], "sticker")
        mask_id = await put_bytes(mask_png(alpha), "mask.png", "image/png", u["_id"], "mask")
        t = now()
        cap = await db().captures.insert_one({
            "owner_id": u["_id"], "original_file_id": img_id, "captured_at": t, "location": None, "place_name": "From clips",
            "trigger": "voice", "transcript": "scrap that", "device": "Meta glasses clip", "status": "ready",
            "sticker_ids": [], "width": w, "height": h, "processed_at": t, "created_at": t,
        })
        st = await db().stickers.insert_one({
            "owner_id": u["_id"], "capture_id": cap.inserted_id, "image_file_id": img_id, "mask_file_id": mask_id,
            "bbox": bbox, "crop_box": [0, 0, w, h], "score": 1.0, "is_hero": True, "starred": True, "source": "clip",
            "title": title, "location": None, "place_name": "From clips", "captured_at": t, "created_at": t,
        })
        await db().captures.update_one({"_id": cap.inserted_id}, {"$set": {"sticker_ids": [st.inserted_id], "hero_sticker_id": st.inserted_id}})
        print(f"added {title}: sticker {st.inserted_id} ({w}x{h})")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--user", default="22222222")
    asyncio.run(main(ap.parse_args().user))
