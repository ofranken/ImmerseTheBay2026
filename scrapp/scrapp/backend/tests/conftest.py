"""Shared fixtures. `api` is a real app + a throwaway local MongoDB (never the shared Atlas one)."""
import uuid

import pytest
from fastapi.testclient import TestClient
from pymongo import MongoClient

LOCAL = "mongodb://localhost:27017"


@pytest.fixture()
def api(monkeypatch):
    try:
        MongoClient(LOCAL, serverSelectionTimeoutMS=800).admin.command("ping")
    except Exception:
        pytest.skip("no local MongoDB")
    dbname = "scrapp_test_" + uuid.uuid4().hex[:8]
    monkeypatch.setenv("MONGO_URI", LOCAL)
    monkeypatch.setenv("MONGO_DB", dbname)
    monkeypatch.setenv("SCRAPP_SKIP_WARMUP", "1")
    monkeypatch.setenv("INVITE_CODE", "")  # open sign-up unless a test sets a code
    monkeypatch.setenv("EMBED_ENABLED", "0")  # hunt tests are SIFT-only unless a test installs an embedder
    from app import db as dbmod
    from app.config import get_settings
    get_settings.cache_clear()
    dbmod._client = None

    async def noop(*_a, **_k):
        return None

    import app.routers.captures as caps
    import app.routers.hunts as hunts
    monkeypatch.setattr(caps, "process_capture", noop)
    monkeypatch.setattr(hunts, "process_capture", noop)
    from app.main import app
    with TestClient(app) as c:
        yield c
    MongoClient(LOCAL).drop_database(dbname)
    get_settings.cache_clear()
    dbmod._client = None
