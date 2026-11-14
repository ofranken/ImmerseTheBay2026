"""Async client for Meshy's 3D generation API. The API key stays on the server.

Verified against docs.meshy.ai on 2026-11-14:
  text to 3D   POST /openapi/v2/text-to-3d  (mode preview, then mode refine with preview_task_id)
  image to 3D  POST /openapi/v1/image-to-3d (image_url as a public URL or a base64 data URI)
  task status  GET  .../{id} -> status PENDING|IN_PROGRESS|SUCCEEDED|FAILED|CANCELED, progress 0-100,
               model_urls.glb, thumbnail_url, task_error. Result URLs are signed and expire (files kept 3 days).
`art_style` is deprecated (ignored by Meshy), so it is not sent.
"""
from __future__ import annotations

import asyncio
import base64

import httpx

from ..config import get_settings

TERMINAL = {"SUCCEEDED", "FAILED", "CANCELED"}


class MeshyError(Exception):
    """A Meshy API error, with the HTTP status and Meshy's own message."""

    def __init__(self, status: int, message: str, retry_after: float | None = None):
        super().__init__(message)
        self.status = status
        self.message = message
        self.retry_after = retry_after


def _raise_for(r: httpx.Response) -> None:
    if r.status_code < 400:
        return
    try:
        msg = r.json().get("message") or r.text
    except Exception:
        msg = r.text
    ra = r.headers.get("retry-after")
    raise MeshyError(r.status_code, str(msg)[:300], float(ra) if ra and ra.replace(".", "", 1).isdigit() else None)


class MeshyClient:
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        s = get_settings()
        if not s.meshy_api_key:
            raise RuntimeError("MESHY_API_KEY is not set")
        self._base = s.meshy_base_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {s.meshy_api_key}"}
        self._model = s.meshy_ai_model
        self._pbr = s.meshy_enable_pbr
        self._polycount = s.meshy_target_polycount
        self._transport = transport

    def _http(self, timeout: float = 60) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=timeout, transport=self._transport, follow_redirects=True)

    async def _post(self, path: str, body: dict) -> str:
        async with self._http() as c:
            r = await c.post(f"{self._base}{path}", json=body, headers=self._headers)
        _raise_for(r)
        return r.json()["result"]

    async def _get(self, path: str) -> dict:
        # Polling is idempotent: retry transient 5xx / network errors a couple of times.
        last: Exception | None = None
        for attempt in range(3):
            try:
                async with self._http() as c:
                    r = await c.get(f"{self._base}{path}", headers=self._headers)
                if r.status_code >= 500:
                    raise MeshyError(r.status_code, "Meshy server error")
                _raise_for(r)
                return r.json()
            except (httpx.TransportError, MeshyError) as e:
                if isinstance(e, MeshyError) and e.status < 500:
                    raise
                last = e
                await asyncio.sleep(1.5 * (attempt + 1))
        raise last or MeshyError(502, "Meshy unreachable")

    # Text to 3D is two-stage: an untextured preview, then a textured refine (billed separately).
    async def text_preview(self, prompt: str) -> str:
        return await self._post("/v2/text-to-3d", {
            "mode": "preview", "prompt": prompt, "ai_model": self._model, "target_formats": ["glb"],
            "should_remesh": True, "target_polycount": self._polycount,
        })

    async def text_refine(self, preview_task_id: str) -> str:
        # The texture model is inherited from the preview task.
        return await self._post("/v2/text-to-3d", {
            "mode": "refine", "preview_task_id": preview_task_id, "enable_pbr": self._pbr, "target_formats": ["glb"],
        })

    async def image_to_3d(self, png_bytes: bytes) -> str:
        data_uri = "data:image/png;base64," + base64.b64encode(png_bytes).decode()
        return await self._post("/v1/image-to-3d", {
            "image_url": data_uri, "ai_model": self._model, "should_texture": True, "enable_pbr": self._pbr,
            "should_remesh": True, "target_polycount": self._polycount, "target_formats": ["glb"],
        })

    async def task(self, stage: str, task_id: str) -> dict:
        path = f"/v1/image-to-3d/{task_id}" if stage == "image" else f"/v2/text-to-3d/{task_id}"
        return await self._get(path)

    async def download(self, url: str) -> bytes:
        async with self._http(timeout=120) as c:
            r = await c.get(url)
        r.raise_for_status()
        return r.content
