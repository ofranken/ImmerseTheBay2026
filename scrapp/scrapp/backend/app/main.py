import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from .db import ensure_indexes
from .services.segmentation import get_segmenter
from .routers import auth, captures, collages, files, hunts, meshes, social, stickers, supersecret, webapp

logging.basicConfig(level=logging.INFO)



@asynccontextmanager
async def lifespan(_: FastAPI):
    await ensure_indexes()
    # Load SAM 3 in the background at startup so the first photo doesn't pay for it (and never blocks the API).
    if not os.getenv("SCRAPP_SKIP_WARMUP"):  # tests set this: they stub segmentation
        warm = asyncio.create_task(asyncio.to_thread(get_segmenter))
        warm.add_done_callback(lambda t: t.exception() and logging.getLogger("scrapp").warning("segmenter warm-up failed: %s", t.exception()))
    yield


app = FastAPI(title="Scrapp API", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

for r in (auth.router, files.router, captures.router, stickers.router, collages.router, collages.public,
          meshes.router, social.router, hunts.router, supersecret.router, webapp.router):
    app.include_router(r)

# The same three.js collage renderer the app bundles is served here for public web-viewer links.
WEB_DIR = Path(os.getenv("WEB_ASSETS_DIR", Path(__file__).resolve().parents[2] / "app" / "assets" / "web"))
class RevalidatingStatic(StaticFiles):
    """The viewer's JS/HTML change with every release; without this Cloudflare serves a 4-hour-old copy. no-cache means
    "ask the server first" (a cheap 304 via the ETag), not "never cache"."""

    def file_response(self, *args, **kwargs):
        resp = super().file_response(*args, **kwargs)
        resp.headers["Cache-Control"] = "no-cache"
        return resp


if WEB_DIR.exists():
    app.mount("/web", RevalidatingStatic(directory=WEB_DIR), name="web")


@app.get("/health")
async def health():
    return {"ok": True}


@app.get("/c/{token}")
async def web_viewer(token: str):
    return RedirectResponse(f"/web/editor.html?mode=view&src=/public/collages/{token}")
