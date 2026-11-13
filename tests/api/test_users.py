from tests.conftest import ADMIN_TOKEN, make_image, signup


async def test_create_user_returns_key_once(client):
    resp = await client.post(
        "/v1/users", json={"email": "Bob@Example.com"}, headers={"X-Admin-Token": ADMIN_TOKEN}
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["email"] == "bob@example.com"
    assert body["plan"] == "free"
    assert body["api_key"].startswith("vs_")


async def test_duplicate_email_409(client):
    await signup(client, "dup@example.com")
    resp = await client.post(
        "/v1/users", json={"email": "dup@example.com"}, headers={"X-Admin-Token": ADMIN_TOKEN}
    )
    assert resp.status_code == 409


async def test_signup_requires_admin_token(client):
    resp = await client.post("/v1/users", json={"email": "x@example.com"})
    assert resp.status_code == 401
    resp = await client.post(
        "/v1/users", json={"email": "x@example.com"}, headers={"X-Admin-Token": "wrong"}
    )
    assert resp.status_code == 401


async def test_invalid_email_422(client):
    resp = await client.post(
        "/v1/users", json={"email": "not-an-email"}, headers={"X-Admin-Token": ADMIN_TOKEN}
    )
    assert resp.status_code == 422


async def test_rotate_key_revokes_old_key(client, api_key):
    resp = await client.post("/v1/keys/rotate", headers={"X-API-Key": api_key})
    assert resp.status_code == 200
    new_key = resp.json()["api_key"]
    assert new_key != api_key

    files = {"file": ("a.png", make_image(), "image/png")}
    old = await client.post("/v1/infer/caption", files=files, headers={"X-API-Key": api_key})
    assert old.status_code == 401
    new = await client.post("/v1/infer/caption", files=files, headers={"X-API-Key": new_key})
    assert new.status_code == 200


async def test_rotate_requires_key(client):
    resp = await client.post("/v1/keys/rotate")
    assert resp.status_code == 401
