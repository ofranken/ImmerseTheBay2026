"""Meshy integration, no network and no database: request shapes, error mapping, retries, cutouts."""
import asyncio
import base64
import json

import cv2
import httpx
import numpy as np
import pytest

from app.config import get_settings
from app.services import meshy as meshy_mod
from app.services.meshy import MeshyClient, MeshyError
from app.services.segmentation import cutout_png


@pytest.fixture(autouse=True)
def meshy_env(monkeypatch):
    monkeypatch.setenv("MESHY_API_KEY", "msy_test_key")
    monkeypatch.setenv("MESHY_BASE_URL", "https://api.meshy.ai/openapi")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def client_with(handler) -> MeshyClient:
    return MeshyClient(transport=httpx.MockTransport(handler))


def run(coro):
    return asyncio.run(coro)


def test_text_preview_request_matches_the_current_api():
    seen = {}

    def handler(req: httpx.Request):
        seen.update(url=str(req.url), auth=req.headers["authorization"], body=json.loads(req.content))
        return httpx.Response(200, json={"result": "task-1"})

    assert run(client_with(handler).text_preview("a tiny frog")) == "task-1"
    assert seen["url"] == "https://api.meshy.ai/openapi/v2/text-to-3d"
    assert seen["auth"] == "Bearer msy_test_key"
    assert seen["body"] == {"mode": "preview", "prompt": "a tiny frog", "ai_model": "meshy-6-lite", "target_formats": ["glb"]}
    assert "art_style" not in seen["body"]  # deprecated: Meshy ignores it


def test_refine_references_the_preview_and_skips_pbr_by_default():
    seen = {}

    def handler(req):
        seen.update(body=json.loads(req.content))
        return httpx.Response(200, json={"result": "task-2"})

    run(client_with(handler).text_refine("task-1"))
    assert seen["body"] == {"mode": "refine", "preview_task_id": "task-1", "enable_pbr": False, "target_formats": ["glb"]}


def test_image_to_3d_sends_a_png_data_uri():
    seen = {}

    def handler(req):
        seen.update(url=str(req.url), body=json.loads(req.content))
        return httpx.Response(200, json={"result": "task-3"})

    run(client_with(handler).image_to_3d(b"\x89PNGfake"))
    b = seen["body"]
    assert seen["url"].endswith("/openapi/v1/image-to-3d")
    assert b["image_url"] == "data:image/png;base64," + base64.b64encode(b"\x89PNGfake").decode()
    assert b["should_texture"] is True and b["ai_model"] == "meshy-6-lite" and b["target_formats"] == ["glb"]


@pytest.mark.parametrize("status,headers", [(402, {}), (429, {"Retry-After": "7"}), (401, {}), (400, {})])
def test_errors_carry_meshys_status_and_message(status, headers):
    def handler(req):
        return httpx.Response(status, json={"message": f"boom {status}"}, headers=headers)

    with pytest.raises(MeshyError) as e:
        run(client_with(handler).text_preview("x" * 5))
    assert e.value.status == status and e.value.message == f"boom {status}"
    if status == 429:
        assert e.value.retry_after == 7.0


def test_polling_retries_a_transient_server_error(monkeypatch):
    async def no_sleep(_):
        return None

    monkeypatch.setattr(meshy_mod.asyncio, "sleep", no_sleep)
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(503, text="down") if len(calls) < 3 else httpx.Response(200, json={"status": "SUCCEEDED"})

    assert run(client_with(handler).task("text", "t"))["status"] == "SUCCEEDED"
    assert len(calls) == 3


def test_polling_does_not_retry_a_404(monkeypatch):
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(404, json={"message": "Task not found"})

    with pytest.raises(MeshyError) as e:
        run(client_with(handler).task("image", "gone"))
    assert e.value.status == 404 and len(calls) == 1


def test_missing_key_is_a_clear_error(monkeypatch):
    monkeypatch.setenv("MESHY_API_KEY", "")
    get_settings.cache_clear()
    with pytest.raises(RuntimeError, match="MESHY_API_KEY"):
        MeshyClient()


def test_user_facing_messages_for_meshy_failures():
    from app.routers.meshes import _http_error

    assert "out of credits" in _http_error(MeshyError(402, "x")).detail
    assert _http_error(MeshyError(429, "x")).status_code == 429
    assert _http_error(MeshyError(403, "ip_not_authorized")).status_code == 503
    assert _http_error(MeshyError(500, "x")).status_code == 502


def test_cutout_is_the_object_alone_on_transparent_background():
    h, w = 400, 600
    img = np.full((h, w, 3), (30, 90, 160), np.uint8)
    yy, xx = np.mgrid[:h, :w]
    mask = (xx - 300) ** 2 + (yy - 200) ** 2 <= 80 ** 2
    img[mask] = (200, 40, 40)
    png = cutout_png(img, mask)
    out = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_UNCHANGED)
    assert out.shape[2] == 4
    assert out.shape[0] <= 190 and out.shape[1] <= 190  # cropped to the object plus a small margin
    assert out[0, 0, 3] == 0  # corner transparent
    assert out[out.shape[0] // 2, out.shape[1] // 2, 3] == 255  # centre opaque
    opaque = out[..., 3] > 200
    white = (out[..., :3] > 240).all(axis=2)
    assert not (opaque & white).any()  # no white sticker outline baked in


def test_cutout_is_downscaled_for_the_upload():
    h, w = 3000, 2000
    img = np.zeros((h, w, 3), np.uint8)
    mask = np.zeros((h, w), bool)
    mask[200:2800, 200:1800] = True
    out = cv2.imdecode(np.frombuffer(cutout_png(img, mask, max_side=1024), np.uint8), cv2.IMREAD_UNCHANGED)
    assert max(out.shape[:2]) <= 1024


def test_no_key_gives_the_app_a_plain_503(monkeypatch):
    from fastapi import HTTPException

    from app.routers.meshes import _client

    monkeypatch.setenv("MESHY_API_KEY", "")
    get_settings.cache_clear()
    with pytest.raises(HTTPException) as e:
        _client()
    assert e.value.status_code == 503 and "not set up" in e.value.detail
