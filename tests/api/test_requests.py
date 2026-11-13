from tests.conftest import make_image, signup


async def run(client, auth, task="caption", n=1):
    ids = []
    for i in range(n):
        files = {"file": ("a.png", make_image(color=(i, 0, 0)), "image/png")}
        resp = await client.post(f"/v1/infer/{task}", files=files, headers=auth)
        ids.append(resp.json()["request_id"])
    return ids


async def test_list_requires_key(client):
    assert (await client.get("/v1/requests")).status_code == 401


async def test_list_paginates_newest_first(client, auth):
    ids = await run(client, auth, n=5)

    page1 = (await client.get("/v1/requests?limit=2", headers=auth)).json()
    assert [r["id"] for r in page1["items"]] == ids[::-1][:2]
    assert page1["next_cursor"] is not None

    page2 = (
        await client.get(f"/v1/requests?limit=2&cursor={page1['next_cursor']}", headers=auth)
    ).json()
    page3 = (
        await client.get(f"/v1/requests?limit=2&cursor={page2['next_cursor']}", headers=auth)
    ).json()
    seen = [r["id"] for p in (page1, page2, page3) for r in p["items"]]
    assert seen == ids[::-1]
    assert page3["next_cursor"] is None


async def test_get_own_request(client, auth):
    [request_id] = await run(client, auth)
    resp = await client.get(f"/v1/requests/{request_id}", headers=auth)
    assert resp.status_code == 200
    assert resp.json()["result"] == {"text": "fake caption"}


async def test_cannot_see_other_users_requests(client, auth):
    [request_id] = await run(client, auth)
    other = {"X-API-Key": await signup(client, "mallory@example.com")}

    assert (await client.get(f"/v1/requests/{request_id}", headers=other)).status_code == 404
    assert (await client.get("/v1/requests", headers=other)).json()["items"] == []


async def test_missing_request_404(client, auth):
    assert (await client.get("/v1/requests/999", headers=auth)).status_code == 404


async def test_stats(client, auth):
    await run(client, auth, "caption", n=3)
    await run(client, auth, "ocr", n=1)

    stats = (await client.get("/v1/stats/me", headers=auth)).json()
    assert stats["total_requests"] == 4
    assert stats["requests_last_24h"] == 4
    assert stats["cache_hit_rate"] == 0.0
    assert stats["p95_latency_ms_last_hour"] is not None
    assert stats["by_task"] == [
        {"task": "caption", "requests": 3},
        {"task": "ocr", "requests": 1},
    ]


async def test_stats_empty(client, auth):
    stats = (await client.get("/v1/stats/me", headers=auth)).json()
    assert stats["total_requests"] == 0
    assert stats["avg_latency_ms"] is None
    assert stats["p95_latency_ms_last_hour"] is None
