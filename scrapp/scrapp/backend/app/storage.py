from bson import ObjectId

from .db import files


async def put_bytes(data: bytes, filename: str, content_type: str, owner_id: ObjectId | None, kind: str) -> ObjectId:
    return await files().upload_from_stream(
        filename,
        data,
        metadata={"content_type": content_type, "owner_id": owner_id, "kind": kind},
    )


async def get_bytes(file_id: ObjectId) -> bytes:
    stream = await files().open_download_stream(file_id)
    return await stream.read()


async def open_stream(file_id: ObjectId):
    return await files().open_download_stream(file_id)


async def delete(file_id: ObjectId | None) -> None:
    if file_id is None:
        return
    try:
        await files().delete(file_id)
    except Exception:
        pass
