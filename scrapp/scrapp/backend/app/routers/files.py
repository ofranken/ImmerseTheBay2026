from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from gridfs.errors import NoFile

from ..security import verify_file_token
from ..storage import open_stream
from ..util import oid

router = APIRouter(tags=["files"])


@router.get("/files/{file_id}")
async def get_file(file_id: str, t: str = Query(...)):
    # URLs are signed when an authorized response is built, so the token is the access check.
    if not verify_file_token(file_id, t):
        raise HTTPException(403, "Link expired")
    try:
        stream = await open_stream(oid(file_id))
    except NoFile:
        raise HTTPException(404, "Not found")
    meta = stream.metadata or {}

    async def body():
        while True:
            chunk = await stream.readchunk()
            if not chunk:
                break
            yield chunk

    return StreamingResponse(
        body(),
        media_type=meta.get("content_type", "application/octet-stream"),
        headers={"Cache-Control": "private, max-age=86400", "Access-Control-Allow-Origin": "*"},
    )
