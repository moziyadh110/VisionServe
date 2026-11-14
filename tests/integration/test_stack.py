"""Real Postgres, Redis and MinIO (fake model). Needs the compose services and migrations:

docker compose up -d postgres redis minio
uv run alembic upgrade head
uv run pytest -m integration
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.main import create_app
from tests.conftest import FakeModel, make_image

pytestmark = pytest.mark.integration

ADMIN = "integration-admin"


@pytest.fixture
async def client():
    settings = Settings(admin_token=ADMIN, log_json=False)  # reads .env for service URLs
    app = create_app(settings, model_loader=FakeModel)
    async with app.router.lifespan_context(app):
        await app.state.model_task
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            c.app = app
            yield c


async def test_full_request_path(client):
    ready = await client.get("/readyz")
    assert ready.status_code == 200, ready.text

    signup = await client.post(
        "/v1/users",
        json={"email": f"it-{uuid.uuid4().hex[:8]}@example.com"},
        headers={"X-Admin-Token": ADMIN},
    )
    assert signup.status_code == 201
    auth = {"X-API-Key": signup.json()["api_key"]}

    # A unique image so the shared Redis cache can't already have it.
    image = make_image("JPEG", color=tuple(uuid.uuid4().bytes[:3]))
    files = {"file": ("a.jpg", image, "image/jpeg")}
    first = (await client.post("/v1/infer/caption", files=files, headers=auth)).json()
    second = (await client.post("/v1/infer/caption", files=files, headers=auth)).json()
    assert first["cache_hit"] is False
    assert second["cache_hit"] is True

    record = (await client.get(f"/v1/requests/{first['request_id']}", headers=auth)).json()
    url = (await client.get(f"/v1/images/{record['image_id']}/url", headers=auth)).json()["url"]

    # The pre-signed URL works without any credentials.
    async with AsyncClient() as anonymous:
        resp = await anonymous.get(url)
    assert resp.status_code == 200
    assert resp.content == image
