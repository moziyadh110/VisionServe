import asyncio
import time

import pytest

from tests.conftest import make_image


def png(color=(200, 30, 30)):
    return {"file": ("a.png", make_image("PNG", color=color), "image/png")}


@pytest.mark.parametrize("task", ["caption", "detailed_caption", "ocr"])
async def test_infer_ok(client, auth, fake_model, task):
    resp = await client.post(f"/v1/infer/{task}", files=png(), headers=auth)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["task"] == task
    assert body["result"]["text"] == f"fake {task}"
    assert body["cache_hit"] is False
    assert body["batch_size"] == 1
    assert isinstance(body["request_id"], int)
    assert fake_model.calls == [(task, 1)]


async def test_infer_requires_key(client):
    resp = await client.post("/v1/infer/caption", files=png())
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "unauthorized"


async def test_infer_rejects_bad_key(client):
    resp = await client.post(
        "/v1/infer/caption", files=png(), headers={"X-API-Key": "vs_12345678_wrong"}
    )
    assert resp.status_code == 401


async def test_unknown_task_422(client, auth):
    resp = await client.post("/v1/infer/segment", files=png(), headers=auth)
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "validation_error"


async def test_too_large_413(client, auth):
    big = b"\x00" * (5 * 1024 * 1024 + 1)
    resp = await client.post(
        "/v1/infer/caption", files={"file": ("big.png", big, "image/png")}, headers=auth
    )
    assert resp.status_code == 413
    assert resp.json()["error"]["code"] == "payload_too_large"


async def test_wrong_format_415(client, auth):
    gif = {"file": ("a.gif", make_image("GIF"), "image/gif")}
    resp = await client.post("/v1/infer/caption", files=gif, headers=auth)
    assert resp.status_code == 415


async def test_503_while_model_loading(app, client, auth):
    app.state.model = None
    resp = await client.post("/v1/infer/caption", files=png(), headers=auth)
    assert resp.status_code == 503


async def test_model_error_is_recorded(client, auth, fake_model):
    def boom(images, task):
        raise RuntimeError("CUDA out of memory")

    fake_model.predict_batch = boom
    resp = await client.post("/v1/infer/caption", files=png(), headers=auth)
    assert resp.status_code == 500
    assert resp.json()["error"]["code"] == "internal_error"

    items = (await client.get("/v1/requests", headers=auth)).json()["items"]
    assert items[0]["status"] == "error"
    assert "out of memory" in items[0]["error"]


# --- caching -------------------------------------------------------------------


async def test_repeat_image_is_served_from_cache(client, auth, fake_model):
    first = (await client.post("/v1/infer/caption", files=png(), headers=auth)).json()
    second = (await client.post("/v1/infer/caption", files=png(), headers=auth)).json()

    assert first["cache_hit"] is False
    assert second["cache_hit"] is True
    assert second["batch_size"] is None
    assert second["result"] == first["result"]
    assert len(fake_model.calls) == 1  # the GPU ran once


async def test_cache_is_per_task(client, auth, fake_model):
    await client.post("/v1/infer/caption", files=png(), headers=auth)
    resp = (await client.post("/v1/infer/ocr", files=png(), headers=auth)).json()
    assert resp["cache_hit"] is False
    assert len(fake_model.calls) == 2


async def test_cache_key_includes_model_version(client, auth, app, redis):
    await client.post("/v1/infer/caption", files=png(), headers=auth)
    keys = await redis.keys("infer:*")
    assert len(keys) == 1
    assert keys[0].startswith(f"infer:caption:{app.state.settings.model_version}:")


async def test_redis_down_still_serves(client, auth, app, fake_model):
    from redis.exceptions import ConnectionError

    class DeadRedis:
        async def get(self, *a, **k):
            raise ConnectionError("down")

        async def set(self, *a, **k):
            raise ConnectionError("down")

    app.state.redis = DeadRedis()
    app.state.rate_limiter.redis = app.state.redis
    resp = await client.post("/v1/infer/caption", files=png(), headers=auth)
    assert resp.status_code == 200


# --- storage -------------------------------------------------------------------


async def test_same_image_is_stored_once(client, auth, storage):
    first = (await client.post("/v1/infer/caption", files=png(), headers=auth)).json()
    second = (await client.post("/v1/infer/ocr", files=png(), headers=auth)).json()
    other = (await client.post("/v1/infer/ocr", files=png((0, 0, 255)), headers=auth)).json()

    async def image_id(request_id):
        r = await client.get(f"/v1/requests/{request_id}", headers=auth)
        return r.json()["image_id"]

    assert await image_id(first["request_id"]) == await image_id(second["request_id"])
    assert await image_id(first["request_id"]) != await image_id(other["request_id"])
    assert storage.puts == 2
    assert all(k.startswith("users/") for k in storage.objects)


# --- batching, backpressure, timeouts ------------------------------------------


@pytest.fixture
def slow_model(fake_model):
    def slow(images, task):
        time.sleep(0.5)
        return [f"slow {task.value}" for _ in images]

    fake_model.predict_batch = slow
    return fake_model


class TestTimeout:
    @pytest.fixture
    def settings_overrides(self):
        return {"inference_timeout_s": 0.1}

    async def test_slow_inference_returns_504(self, client, auth, slow_model):
        resp = await client.post("/v1/infer/caption", files=png(), headers=auth)
        assert resp.status_code == 504
        assert resp.json()["error"]["code"] == "timeout"

        items = (await client.get("/v1/requests", headers=auth)).json()["items"]
        assert items[0]["status"] == "timeout"


class TestBackpressure:
    @pytest.fixture
    def settings_overrides(self):
        return {"max_queue_size": 0}

    async def test_full_queue_returns_503(self, client, auth):
        resp = await client.post("/v1/infer/caption", files=png(), headers=auth)
        assert resp.status_code == 503
        assert resp.headers["Retry-After"] == "1"


class TestBatching:
    @pytest.fixture
    def settings_overrides(self):
        return {"max_batch_size": 8, "max_batch_wait_ms": 200}

    async def test_concurrent_requests_share_a_batch(self, client, auth, fake_model):
        colors = [(i, i, i) for i in range(4)]
        responses = await asyncio.gather(
            *(client.post("/v1/infer/caption", files=png(c), headers=auth) for c in colors)
        )
        assert all(r.status_code == 200 for r in responses)
        assert fake_model.calls == [("caption", 4)]
        assert {r.json()["batch_size"] for r in responses} == {4}
