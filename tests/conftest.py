"""Shared fixtures.

Tests never load the real model or need Postgres: a FakeModel stands in for
Florence-2, and each test gets a fresh SQLite file created from the same models.
"""

import io

import pytest
from httpx import ASGITransport, AsyncClient
from PIL import Image

from app.config import Settings
from app.db.models import Base
from app.main import create_app

ADMIN_TOKEN = "test-admin"


class FakeModel:
    def __init__(self):
        self.calls = []

    def predict(self, image, task):
        self.calls.append(task)
        return f"fake {task.value}"


def make_image(fmt: str = "PNG", size=(32, 32), color=(200, 30, 30)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format=fmt)
    return buf.getvalue()


@pytest.fixture
def fake_model():
    return FakeModel()


@pytest.fixture
def settings(tmp_path):
    return Settings(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'test.db').as_posix()}",
        admin_token=ADMIN_TOKEN,
    )


@pytest.fixture
async def app(settings, fake_model):
    app = create_app(settings, model_loader=lambda: fake_model)
    # httpx doesn't run lifespan events, so enter the lifespan ourselves.
    async with app.router.lifespan_context(app):
        async with app.state.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        await app.state.model_task  # wait until the fake model is "loaded"
        yield app


@pytest.fixture
async def client(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def signup(client: AsyncClient, email: str) -> str:
    resp = await client.post(
        "/v1/users", json={"email": email}, headers={"X-Admin-Token": ADMIN_TOKEN}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["api_key"]


@pytest.fixture
async def api_key(client):
    return await signup(client, "alice@example.com")


@pytest.fixture
def auth(api_key):
    return {"X-API-Key": api_key}
