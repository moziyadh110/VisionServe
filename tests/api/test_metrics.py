from prometheus_client import REGISTRY

from tests.conftest import make_image


def sample(name: str, **labels) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


async def test_metrics_endpoint_exposes_all_series(client, auth):
    files = {"file": ("a.png", make_image(), "image/png")}
    await client.post("/v1/infer/caption", files=files, headers=auth)

    body = (await client.get("/metrics")).text
    for name in (
        "http_requests_total",
        "inference_latency_seconds_bucket",
        "batch_size_bucket",
        "cache_hits_total",
        "cache_misses_total",
        "queue_depth",
    ):
        assert name in body


async def test_inference_updates_metrics(client, auth):
    files = {"file": ("a.png", make_image(color=(9, 9, 9)), "image/png")}
    hits = sample("cache_hits_total", task="caption")
    misses = sample("cache_misses_total", task="caption")
    batches = sample("batch_size_count")

    await client.post("/v1/infer/caption", files=files, headers=auth)
    await client.post("/v1/infer/caption", files=files, headers=auth)

    assert sample("cache_misses_total", task="caption") == misses + 1
    assert sample("cache_hits_total", task="caption") == hits + 1
    assert sample("batch_size_count") == batches + 1


async def test_http_counter_uses_route_template(client, auth):
    before = sample(
        "http_requests_total", method="GET", route="/v1/requests/{request_id}", status="404"
    )
    await client.get("/v1/requests/12345", headers=auth)
    after = sample(
        "http_requests_total", method="GET", route="/v1/requests/{request_id}", status="404"
    )
    assert after == before + 1


class TestCacheDisabled:
    @staticmethod
    def _png():
        return {"file": ("a.png", make_image(color=(5, 5, 5)), "image/png")}

    async def test_no_cache_hits_when_disabled(self, app, client, auth, fake_model):
        app.state.settings.cache_enabled = False
        await client.post("/v1/infer/caption", files=self._png(), headers=auth)
        second = (await client.post("/v1/infer/caption", files=self._png(), headers=auth)).json()
        assert second["cache_hit"] is False
        assert len(fake_model.calls) == 2
