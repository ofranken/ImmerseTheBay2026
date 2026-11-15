"""Sign-in attempts are rate limited per client IP (the studio forwards the visitor's IP in cf-connecting-ip)."""
from app.routers import auth as auth_router


def _reg(c, name):
    assert c.post("/auth/register", json={"username": name, "email": f"{name}@example.com", "password": "password1"}).status_code == 200


def _login(c, who, pw, ip=None):
    return c.post("/auth/login", json={"username_or_email": who, "password": pw}, headers={"cf-connecting-ip": ip} if ip else {})


def test_failed_logins_are_throttled_then_a_success_resets(api, monkeypatch):
    monkeypatch.setitem(auth_router.login_limiter.limits, "login", (4, 600))
    auth_router.login_limiter.hits.clear()
    _reg(api, "limited1")
    assert [_login(api, "limited1", "wrong", "9.9.9.9").status_code for _ in range(4)] == [401] * 4
    blocked = _login(api, "limited1", "password1", "9.9.9.9")  # even the right password waits once the window is full
    assert blocked.status_code == 429 and int(blocked.headers["retry-after"]) > 0
    assert _login(api, "limited1", "password1", "8.8.8.8").status_code == 200  # another visitor is unaffected
    # a successful sign-in clears that visitor's count
    assert [_login(api, "limited1", "wrong", "8.8.8.8").status_code for _ in range(3)] == [401] * 3
    assert _login(api, "limited1", "password1", "8.8.8.8").status_code == 200
    assert _login(api, "limited1", "wrong", "8.8.8.8").status_code == 401
