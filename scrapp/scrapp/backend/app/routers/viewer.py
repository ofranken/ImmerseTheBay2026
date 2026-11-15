"""The public face of a published collage: /c/<token>.

  GET /c/<token>            the 3D viewer page, with Open Graph tags so link previews (iMessage, Slack, WhatsApp) look good
  GET /c/<token>/qr.png     a QR code of that link
  GET /c/<token>/thumb.png  the collage picture (a stable URL for og:image; the signed file links expire)
  GET /c/<token>/scene.glb  the whole collage as one glTF binary, for "View in AR" (exists once the owner has saved it from the app)

Anyone with the token can open these: the token is the access control, like an unlisted link.
"""
from __future__ import annotations

import html
import io
import json
import os
from pathlib import Path

import segno
from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse, Response

from ..config import get_settings
from ..db import db
from ..storage import get_bytes

router = APIRouter(tags=["viewer"], include_in_schema=False)

WEB_DIR = Path(os.getenv("WEB_ASSETS_DIR", Path(__file__).resolve().parents[3] / "app" / "assets" / "web"))
CORS = {"Access-Control-Allow-Origin": "*"}


async def _published(token: str) -> dict:
    c = await db().collages.find_one({"public_token": token})
    if not c:
        raise HTTPException(404, "Not found")
    return c


def _version(*names: str) -> str:
    """Changes whenever a viewer file does, so the page never runs a stale copy from an edge or browser cache."""
    return str(max(int((WEB_DIR / n).stat().st_mtime) for n in names))


def render_page(token: str, title: str, has_thumb: bool, has_ar: bool, base_url: str) -> str:
    v = _version("editor.js", "viewer_fx.js", "viewer_ar.js")
    page = (WEB_DIR / "editor.html").read_text(encoding="utf-8")
    url = f"{base_url}/c/{token}"
    safe_title = html.escape(title or "Scrapp collage", quote=True)
    og = [
        ('property', 'og:type', 'website'), ('property', 'og:site_name', 'Scrapp'),
        ('property', 'og:title', f"{safe_title}: a 3D collage on Scrapp"),
        ('property', 'og:description', "Open it to look around in 3D. Made with Scrapp."),
        ('property', 'og:url', url),
        ('name', 'twitter:card', 'summary_large_image' if has_thumb else 'summary'),
        ('name', 'twitter:title', f"{safe_title}: a 3D collage on Scrapp"),
    ]
    if has_thumb:
        og += [('property', 'og:image', f"{url}/thumb.png"), ('name', 'twitter:image', f"{url}/thumb.png")]
    tags = "\n  ".join(f'<meta {k}="{n}" content="{c}">' for k, n, c in og)
    head = (f'<base href="/web/">\n  <meta name="robots" content="noindex">\n  {tags}\n'
            f'  <script>window.__SCRAPP_VIEW = {json.dumps({"src": f"/public/collages/{token}", "token": token, "ar": has_ar, "glb": f"/c/{token}/scene.glb"})};</script>')
    page = page.replace("<head>", "<head>\n  " + head, 1)
    page = page.replace("<title>Scrapp collage</title>", f"<title>{safe_title} · Scrapp</title>", 1)
    # Version the scripts: viewer_fx.js / viewer_ar.js are imported by editor.js, so map their resolved URLs to versioned ones.
    imap = f'"/web/viewer_fx.js": "/web/viewer_fx.js?v={v}", "/web/viewer_ar.js": "/web/viewer_ar.js?v={v}", '
    page = page.replace('{ "imports": {', '{ "imports": {\n        ' + imap, 1)
    page = page.replace('src="./editor.js"', f'src="/web/editor.js?v={v}"', 1)
    return page


@router.get("/c/{token}", response_class=HTMLResponse)
async def viewer_page(token: str):
    c = await _published(token)
    return HTMLResponse(render_page(token, c.get("title", ""), bool(c.get("thumbnail_file_id")), bool(c.get("scene_glb_file_id")),
                                    get_settings().public_base_url),
                        headers={"Cache-Control": "no-cache"})


@router.get("/c/{token}/qr.png")
async def qr_png(token: str):
    await _published(token)
    buf = io.BytesIO()
    segno.make(f"{get_settings().public_base_url}/c/{token}", error="m").save(buf, kind="png", scale=12, border=3, dark="#5C3A26", light="#FFF0DE")
    return Response(buf.getvalue(), media_type="image/png", headers={**CORS, "Cache-Control": "public, max-age=86400"})


@router.get("/c/{token}/thumb.png")
async def thumb_png(token: str):
    c = await _published(token)
    if not c.get("thumbnail_file_id"):
        raise HTTPException(404, "No picture for this collage")
    return Response(await get_bytes(c["thumbnail_file_id"]), media_type="image/png", headers={**CORS, "Cache-Control": "public, max-age=300"})


@router.get("/c/{token}/scene.glb")
async def scene_glb(token: str):
    c = await _published(token)
    if not c.get("scene_glb_file_id"):
        raise HTTPException(404, "No AR model for this collage yet")
    return Response(await get_bytes(c["scene_glb_file_id"]), media_type="model/gltf-binary",
                    headers={**CORS, "Cache-Control": "no-cache", "Content-Disposition": 'inline; filename="collage.glb"'})
