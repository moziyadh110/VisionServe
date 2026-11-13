"""Cross-cutting behavior: rate limits, request ids, error format, readiness, image URLs."""

import pytest

from tests.conftest import make_image


def png(color=(1, 2, 3)):
    return {"file": ("a.png", make_image(color=color), "image/png")}


# --- rate limiting -------------------------------------------------------------


@pytest.mark.parametrize("algorithm", ["token_bucket", "fixed_window"])
async def test_61st_request_in_a_minute_gets_429(app, client, auth, algorithm, monkeypatch):
    # Freeze the clock so the bucket can't refill while the test runs.
    monkeypatch.setattr("app.core.rate_limit.time.time", lambda: 60 * 1000.0 + 5)
    app.state.rate_limiter.algorithm = algorithm
    for i in range(60):
        resp = await client.post("/v1/infer/caption", files=png((i, 0, 0)), headers=auth)
        assert resp.status_code == 200, (i, resp.text)

    resp = await client.post("/v1/infer/caption", files=png(), headers=auth)
    assert resp.status_code == 429
    assert int(resp.headers["Retry-After"]) >= 1
    body = resp.json()["error"]
    assert body["code"] == "rate_limited"
    assert body["message"] == "60 requests per minute exceeded"


# --- request ids and error format ----------------------------------------------


async def test_every_response_has_a_request_id(client):
    resp = await client.get("/healthz")
    assert len(resp.headers["X-Request-ID"]) == 32


async def test_incoming_request_id_is_reused(client):
    resp = await client.get("/healthz", headers={"X-Request-ID": "lb-abc123"})
    assert resp.headers["X-Request-ID"] == "lb-abc123"


async def test_bad_incoming_request_id_is_replaced(client):
    resp = await client.get("/healthz", headers={"X-Request-ID": "x" * 200})
    assert resp.headers["X-Request-ID"] != "x" * 200


async def test_error_body_carries_the_request_id(client):
    resp = await client.get("/v1/requests")
    error = resp.json()["error"]
    assert error == {
        "code": "unauthorized",
        "message": "Missing or invalid API key",
        "request_id": resp.headers["X-Request-ID"],
    }


async def test_unknown_route_uses_error_format(client):
    resp = await client.get("/nope")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


# --- readiness -----------------------------------------------------------------


async def test_readyz_reports_each_check(client):
    resp = await client.get("/readyz")
    assert resp.status_code == 200
    assert resp.json()["checks"] == {"model": True, "postgres": True, "redis": True}


async def test_readyz_503_when_redis_down(app, client):
    from redis.exceptions import ConnectionError

    class DeadRedis:
        async def ping(self):
            raise ConnectionError("down")

    app.state.redis = DeadRedis()
    resp = await client.get("/readyz")
    assert resp.status_code == 503
    assert resp.json()["checks"]["redis"] is False


async def test_readyz_503_when_postgres_down(app, client):
    real = app.state.engine

    class DeadEngine:
        def connect(self):
            raise OSError("connection refused")

    app.state.engine = DeadEngine()
    try:
        resp = await client.get("/readyz")
    finally:
        app.state.engine = real
    assert resp.status_code == 503
    assert resp.json()["checks"]["postgres"] is False


# --- image URLs ----------------------------------------------------------------


async def test_image_url(client, auth):
    request_id = (await client.post("/v1/infer/caption", files=png(), headers=auth)).json()[
        "request_id"
    ]
    image_id = (await client.get(f"/v1/requests/{request_id}", headers=auth)).json()["image_id"]

    resp = await client.get(f"/v1/images/{image_id}/url", headers=auth)
    assert resp.status_code == 200
    body = resp.json()
    assert body["expires_in_s"] == 900
    assert "users/" in body["url"]


async def test_image_url_of_other_user_404(client, auth):
    from tests.conftest import signup

    request_id = (await client.post("/v1/infer/caption", files=png(), headers=auth)).json()[
        "request_id"
    ]
    image_id = (await client.get(f"/v1/requests/{request_id}", headers=auth)).json()["image_id"]
    other = {"X-API-Key": await signup(client, "eve@example.com")}
    assert (await client.get(f"/v1/images/{image_id}/url", headers=other)).status_code == 404
