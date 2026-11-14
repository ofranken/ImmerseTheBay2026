"""A stand-in for api.meshy.ai so the 3D flow can be tested without credits or a key.

    uvicorn tests.mock_meshy:app --port 9100
    MESHY_API_KEY=test MESHY_BASE_URL=http://127.0.0.1:9100/openapi  (then run the Scrapp server)

Behaviour mirrors the documented API (docs.meshy.ai): POST returns {"result": id}; GET walks
PENDING -> IN_PROGRESS -> SUCCEEDED over a few polls; model_urls.glb points at a tiny cube.
Magic words in the prompt trigger failures: FAIL402 (no credits), FAIL429 (rate limit), FAILTASK (task fails).
GET /_debug/requests lists every create request the mock saw, for assertions.
"""
from __future__ import annotations

import base64
import itertools
import json
import struct
import zlib

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

app = FastAPI()
_ids = itertools.count(1)
tasks: dict[str, dict] = {}
seen: list[dict] = []


def make_glb() -> bytes:
    """A valid binary glTF: one orange unit cube."""
    v = [(-.5, -.5, -.5), (.5, -.5, -.5), (.5, .5, -.5), (-.5, .5, -.5), (-.5, -.5, .5), (.5, -.5, .5), (.5, .5, .5), (-.5, .5, .5)]
    idx = [0, 1, 2, 0, 2, 3, 4, 6, 5, 4, 7, 6, 0, 4, 5, 0, 5, 1, 1, 5, 6, 1, 6, 2, 2, 6, 7, 2, 7, 3, 3, 7, 4, 3, 4, 0]
    pos = b"".join(struct.pack("<3f", *p) for p in v)
    ind = struct.pack(f"<{len(idx)}H", *idx)
    ind += b"\0" * (-len(ind) % 4)
    blob = pos + ind
    gltf = {
        "asset": {"version": "2.0"}, "scene": 0, "scenes": [{"nodes": [0]}], "nodes": [{"mesh": 0}],
        "materials": [{"pbrMetallicRoughness": {"baseColorFactor": [0.95, 0.55, 0.2, 1], "metallicFactor": 0, "roughnessFactor": 0.8}}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0}, "indices": 1, "material": 0}]}],
        "buffers": [{"byteLength": len(blob)}],
        "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": len(pos), "target": 34962},
                        {"buffer": 0, "byteOffset": len(pos), "byteLength": len(idx) * 2, "target": 34963}],
        "accessors": [{"bufferView": 0, "componentType": 5126, "count": 8, "type": "VEC3", "min": [-.5] * 3, "max": [.5] * 3},
                      {"bufferView": 1, "componentType": 5123, "count": len(idx), "type": "SCALAR"}],
    }
    js = json.dumps(gltf, separators=(",", ":")).encode()
    js += b" " * (-len(js) % 4)
    total = 12 + 8 + len(js) + 8 + len(blob)
    return b"glTF" + struct.pack("<II", 2, total) + struct.pack("<I4s", len(js), b"JSON") + js + struct.pack("<I4s", len(blob), b"BIN\0") + blob


def make_png(size: int = 96) -> bytes:
    raw = b"".join(b"\0" + bytes([240, 140, 50, 255]) * size for _ in range(size))
    def chunk(t: bytes, d: bytes) -> bytes:
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def _auth_ok(request: Request) -> bool:
    return request.headers.get("authorization", "").startswith("Bearer ") and len(request.headers["authorization"]) > 8


def _create(request: Request, kind: str, body: dict, text: str) -> Response:
    seen.append({"kind": kind, "body": {k: (v if k != "image_url" else f"<{len(v)} chars>") for k, v in body.items()}, "image_url": body.get("image_url")})
    if "FAIL402" in text:
        return JSONResponse({"message": "Insufficient credits"}, status_code=402)
    if "FAIL429" in text:
        return JSONResponse({"message": "Rate limit exceeded"}, status_code=429, headers={"Retry-After": "7"})
    tid = f"mock-{next(_ids)}"
    tasks[tid] = {"kind": kind, "polls": 0, "fail": "FAILTASK" in text, "preview_ok": kind != "refine"}
    return JSONResponse({"result": tid})


@app.post("/openapi/v2/text-to-3d")
async def text_create(request: Request):
    if not _auth_ok(request):
        return JSONResponse({"message": "Unauthorized"}, status_code=401)
    body = await request.json()
    if body.get("mode") == "refine":
        if body.get("preview_task_id") not in tasks:
            return JSONResponse({"message": "preview task not found"}, status_code=400)
        return _create(request, "refine", body, "")
    if len(body.get("prompt", "")) > 800:
        return JSONResponse({"message": "prompt too long"}, status_code=400)
    return _create(request, "preview", body, body.get("prompt", ""))


@app.post("/openapi/v1/image-to-3d")
async def image_create(request: Request):
    if not _auth_ok(request):
        return JSONResponse({"message": "Unauthorized"}, status_code=401)
    body = await request.json()
    if not str(body.get("image_url", "")).startswith("data:image/png;base64,"):
        return JSONResponse({"message": "image_url must be a public URL or a data URI"}, status_code=400)
    return _create(request, "image", body, "")


def _task_json(request: Request, tid: str, kind: str) -> Response:
    t = tasks.get(tid)
    if not t:
        return JSONResponse({"message": "Task not found"}, status_code=404)
    t["polls"] += 1
    base = str(request.base_url).rstrip("/")
    out = {"id": tid, "type": kind, "status": "PENDING", "progress": 0, "model_urls": {}, "task_error": None}
    if t["polls"] == 1:
        pass
    elif t["polls"] == 2:
        out.update(status="IN_PROGRESS", progress=55)
    elif t["fail"]:
        out.update(status="FAILED", task_error={"type": "invalid_input", "code": "image_too_complex", "message": "Mock: the input was too complex"})
    else:
        out.update(status="SUCCEEDED", progress=100, thumbnail_url=f"{base}/assets/{tid}.png",
                   model_urls={"glb": f"{base}/assets/{tid}.glb?Expires=1"})
    return JSONResponse(out)


@app.get("/openapi/v2/text-to-3d/{tid}")
async def text_get(tid: str, request: Request):
    return _task_json(request, tid, "text-to-3d")


@app.get("/openapi/v1/image-to-3d/{tid}")
async def image_get(tid: str, request: Request):
    return _task_json(request, tid, "image-to-3d")


@app.get("/assets/{name}")
async def asset(name: str):
    return Response(make_glb() if name.endswith(".glb") else make_png(), media_type="model/gltf-binary" if name.endswith(".glb") else "image/png")


@app.get("/_debug/requests")
async def debug_requests():
    return seen
