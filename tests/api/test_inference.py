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
    assert len(fake_model.calls) == 1


async def test_infer_requires_key(client):
    resp = await client.post("/v1/infer/caption", files=png())
    assert resp.status_code == 401


async def test_infer_rejects_bad_key(client):
    resp = await client.post(
        "/v1/infer/caption", files=png(), headers={"X-API-Key": "vs_12345678_wrong"}
    )
    assert resp.status_code == 401


async def test_unknown_task_422(client, auth):
    resp = await client.post("/v1/infer/segment", files=png(), headers=auth)
    assert resp.status_code == 422


async def test_too_large_413(client, auth):
    big = b"\x00" * (5 * 1024 * 1024 + 1)
    resp = await client.post(
        "/v1/infer/caption", files={"file": ("big.png", big, "image/png")}, headers=auth
    )
    assert resp.status_code == 413


async def test_wrong_format_415(client, auth):
    gif = {"file": ("a.gif", make_image("GIF"), "image/gif")}
    resp = await client.post("/v1/infer/caption", files=gif, headers=auth)
    assert resp.status_code == 415


async def test_503_while_model_loading(app, client, auth):
    app.state.model = None
    resp = await client.post("/v1/infer/caption", files=png(), headers=auth)
    assert resp.status_code == 503


async def test_same_image_is_stored_once(client, auth):
    first = (await client.post("/v1/infer/caption", files=png(), headers=auth)).json()
    second = (await client.post("/v1/infer/ocr", files=png(), headers=auth)).json()
    other = (await client.post("/v1/infer/ocr", files=png((0, 0, 255)), headers=auth)).json()

    async def image_id(request_id):
        r = await client.get(f"/v1/requests/{request_id}", headers=auth)
        return r.json()["image_id"]

    assert await image_id(first["request_id"]) == await image_id(second["request_id"])
    assert await image_id(first["request_id"]) != await image_id(other["request_id"])


async def test_model_error_is_recorded(client, auth, fake_model):
    def boom(image, task):
        raise RuntimeError("CUDA out of memory")

    fake_model.predict = boom
    resp = await client.post("/v1/infer/caption", files=png(), headers=auth)
    assert resp.status_code == 500

    items = (await client.get("/v1/requests", headers=auth)).json()["items"]
    assert items[0]["status"] == "error"
    assert "out of memory" in items[0]["error"]
