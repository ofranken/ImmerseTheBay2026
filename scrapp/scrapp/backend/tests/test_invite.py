"""Sign-up gate: with INVITE_CODE set, registering needs the code; logging in never does."""
from app.config import get_settings


def _reg(c, name, code=None):
    body = {"username": name, "email": f"{name}@example.com", "password": "password1"}
    if code is not None:
        body["invite_code"] = code
    return c.post("/auth/register", json=body)


def test_open_signup_when_no_code_configured(api):
    assert _reg(api, "openuser").status_code == 200


def test_invite_code_is_required_and_checked(api, monkeypatch):
    monkeypatch.setenv("INVITE_CODE", "Bay-Demo-7")
    get_settings.cache_clear()
    assert _reg(api, "nocode").status_code == 403
    assert _reg(api, "wrongcode", "nope").status_code == 403
    assert _reg(api, "emptycode", "").status_code == 403
    ok = _reg(api, "goodcode", "  bay-demo-7 ")  # case and surrounding spaces are forgiven
    assert ok.status_code == 200 and ok.json()["token"]
    # Existing accounts sign in without any code.
    login = api.post("/auth/login", json={"username_or_email": "goodcode", "password": "password1"})
    assert login.status_code == 200
    # A rejected attempt creates nothing: the name is still free.
    assert _reg(api, "nocode", "bay-demo-7").status_code == 200
