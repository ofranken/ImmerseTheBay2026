"""Thin async client for Meshy's 3D generation API (key stays on the server)."""
from __future__ import annotations

import base64

import httpx

from ..config import get_settings

TERMINAL = {"SUCCEEDED", "FAILED", "CANCELED"}


class MeshyClient:
    def __init__(self) -> None:
        s = get_settings()
        if not s.meshy_api_key:
            raise RuntimeError("MESHY_API_KEY is not set")
        self._base = s.meshy_base_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {s.meshy_api_key}"}

    async def _post(self, path: str, body: dict) -> str:
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.post(f"{self._base}{path}", json=body, headers=self._headers)
            r.raise_for_status()
            return r.json()["result"]

    async def _get(self, path: str) -> dict:
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.get(f"{self._base}{path}", headers=self._headers)
            r.raise_for_status()
            return r.json()

    # Text to 3D is two-stage: an untextured preview, then a textured refine.
    async def text_preview(self, prompt: str, art_style: str | None = None) -> str:
        body = {"mode": "preview", "prompt": prompt}
        if art_style:
            body["art_style"] = art_style
        return await self._post("/v2/text-to-3d", body)

    async def text_refine(self, preview_task_id: str) -> str:
        return await self._post("/v2/text-to-3d", {"mode": "refine", "preview_task_id": preview_task_id, "enable_pbr": True})

    async def image_to_3d(self, png_bytes: bytes) -> str:
        data_uri = "data:image/png;base64," + base64.b64encode(png_bytes).decode()
        return await self._post("/v1/image-to-3d", {"image_url": data_uri, "should_texture": True, "enable_pbr": True})

    async def task(self, stage: str, task_id: str) -> dict:
        path = f"/v1/image-to-3d/{task_id}" if stage == "image" else f"/v2/text-to-3d/{task_id}"
        return await self._get(path)

    async def download(self, url: str) -> bytes:
        async with httpx.AsyncClient(timeout=120, follow_redirects=True) as c:
            r = await c.get(url)
            r.raise_for_status()
            return r.content
