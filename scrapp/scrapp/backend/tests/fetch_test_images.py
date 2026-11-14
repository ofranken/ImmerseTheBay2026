"""Download the real test photos listed in tests/data/manifest.json (COCO 2017 val).

The photos are Flickr uploads under per-image licenses, so they are fetched, not committed
(tests/data/images/ is gitignored). Source URLs and license ids are in the manifest.

    python -m tests.fetch_test_images
"""
import json
import urllib.request
from pathlib import Path

DATA = Path(__file__).parent / "data"


def fetch() -> int:
    manifest = json.loads((DATA / "manifest.json").read_text())
    out = DATA / "images"
    out.mkdir(exist_ok=True)
    n = 0
    for im in manifest["images"]:
        dest = out / im["file"]
        if dest.exists():
            continue
        urllib.request.urlretrieve(im["coco_url"], dest)
        n += 1
    return n


if __name__ == "__main__":
    print(f"downloaded {fetch()} new images into {DATA / 'images'}")
