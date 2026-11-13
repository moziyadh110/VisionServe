async def test_healthz(client):
    resp = await client.get("/healthz")
    assert resp.status_code == 200


async def test_readyz_ok_when_model_loaded(client):
    resp = await client.get("/readyz")
    assert resp.status_code == 200
    assert resp.json()["checks"]["model"] is True


async def test_readyz_503_while_model_loading(app, client):
    app.state.model = None
    resp = await client.get("/readyz")
    assert resp.status_code == 503
