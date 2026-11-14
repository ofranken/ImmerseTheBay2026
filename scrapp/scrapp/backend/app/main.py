import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from .db import ensure_indexes
from .routers import auth, captures, collages, files, hunts, meshes, social, stickers

logging.basicConfig(level=logging.INFO)



@asynccontextmanager
async def lifespan(_: FastAPI):
    await ensure_indexes()
    yield


app = FastAPI(title="Scrapp API", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

for r in (auth.router, files.router, captures.router, stickers.router, collages.router, collages.public,
          meshes.router, social.router, hunts.router):
    app.include_router(r)

# The same three.js collage renderer the app bundles is served here for public web-viewer links.
WEB_DIR = Path(os.getenv("WEB_ASSETS_DIR", Path(__file__).resolve().parents[2] / "app" / "assets" / "web"))
if WEB_DIR.exists():
    app.mount("/web", StaticFiles(directory=WEB_DIR), name="web")


@app.get("/health")
async def health():
    return {"ok": True}


@app.get("/c/{token}")
async def web_viewer(token: str):
    return RedirectResponse(f"/web/editor.html?mode=view&src=/public/collages/{token}")
