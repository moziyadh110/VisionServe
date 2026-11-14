import asyncio

import pytest

from tests.conftest import make_image


def png(color=(7, 7, 7)):
    return {"file": ("a.png", make_image(color=color), "image/png")}


def timing(resp) -> dict[str, str]:
    """Parse Server-Timing into {name: raw params}."""
    out = {}
    for part in resp.headers["Server-Timing"].split(", "):
        name, _, params = part.partition(";")
        out[name] = params
    return out


async def test_root_redirects_to_ui(client):
    resp = await client.get("/")
    assert resp.status_code in (302, 307)
    assert resp.headers["location"] == "/ui/"


@pytest.mark.parametrize("path", ["/ui/", "/ui/app.js", "/ui/styles.css"])
async def test_ui_files_are_served(client, path):
    resp = await client.get(path)
    assert resp.status_code == 200
    assert len(resp.text) > 100


async def test_server_timing_on_gpu_path(client, auth):
    resp = await client.post("/v1/infer/caption", files=png(), headers=auth)
    stages = timing(resp)
    assert list(stages) == ["decode", "cache", "store", "queue", "gpu", "save"]
    assert 'desc="batch-' in stages["gpu"]


async def test_server_timing_on_cache_hit_skips_gpu(client, auth):
    await client.post("/v1/infer/caption", files=png(), headers=auth)
    resp = await client.post("/v1/infer/caption", files=png(), headers=auth)
    assert list(timing(resp)) == ["decode", "cache", "store", "save"]


class TestBatchIds:
    @pytest.fixture
    def settings_overrides(self):
        return {"max_batch_size": 8, "max_batch_wait_ms": 200}

    async def test_requests_in_one_pass_share_a_batch_id(self, client, auth):
        responses = await asyncio.gather(
            *(client.post("/v1/infer/ocr", files=png((i, 1, 1)), headers=auth) for i in range(3))
        )
        ids = {timing(r)["gpu"].split("desc=")[1] for r in responses}
        assert len(ids) == 1
