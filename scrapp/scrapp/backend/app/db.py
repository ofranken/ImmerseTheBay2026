from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase, AsyncIOMotorGridFSBucket
from pymongo import ASCENDING, DESCENDING, GEOSPHERE

from .config import get_settings

_client: AsyncIOMotorClient | None = None


def client() -> AsyncIOMotorClient:
    global _client
    if _client is None:
        _client = AsyncIOMotorClient(get_settings().mongo_uri, tz_aware=True)
    return _client


def db() -> AsyncIOMotorDatabase:
    return client()[get_settings().mongo_db]


def files() -> AsyncIOMotorGridFSBucket:
    # Originals, sticker PNGs, masks, collage renders and GLBs all live in one GridFS bucket.
    return AsyncIOMotorGridFSBucket(db(), bucket_name="media")


async def ensure_indexes() -> None:
    d = db()
    await d.users.create_index("username", unique=True)
    await d.users.create_index("email", unique=True)
    await d.friendships.create_index([("requester_id", ASCENDING), ("addressee_id", ASCENDING)], unique=True)
    await d.captures.create_index([("owner_id", ASCENDING), ("captured_at", DESCENDING)])
    await d.captures.create_index([("location", GEOSPHERE)], sparse=True)
    await d.stickers.create_index([("owner_id", ASCENDING), ("created_at", DESCENDING)])
    await d.stickers.create_index("capture_id")
    await d.stickers.create_index([("location", GEOSPHERE)], sparse=True)
    await d.collages.create_index([("owner_id", ASCENDING), ("updated_at", DESCENDING)])
    await d.collages.create_index("public_token", unique=True, sparse=True)
    await d.meshes.create_index([("owner_id", ASCENDING), ("created_at", DESCENDING)])
    await d.shares.create_index([("to_id", ASCENDING), ("created_at", DESCENDING)])
    await d.shares.create_index([("kind", ASCENDING), ("item_id", ASCENDING), ("to_id", ASCENDING)])
    await d.hunts.create_index([("owner_id", ASCENDING), ("created_at", DESCENDING)])
    await d.hunts.create_index("items.sticker_id")
    await d.hunt_progress.create_index([("hunt_id", ASCENDING), ("user_id", ASCENDING)], unique=True)
