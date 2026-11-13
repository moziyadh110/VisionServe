"""Shared fixtures.

Tests never touch a GPU, Postgres, Redis or MinIO: a FakeModel stands in for
Florence-2, each test gets a fresh SQLite file created from the same models,
fakeredis (which also runs our Lua script) replaces Redis, and FakeStorage keeps
objects in a dict.
"""

import io

import fakeredis
import pytest
from httpx import ASGITransport, AsyncClient
from PIL import Image

from app.config import Settings
from app.db.models import Base
from app.main import create_app

ADMIN_TOKEN = "test-admin"


class FakeModel:
    def __init__(self):
        self.calls: list[tuple[str, int]] = []  # (task, batch size)

    def predict_batch(self, images, task):
        self.calls.append((task.value, len(images)))
        return [f"fake {task.value}" for _ in images]


class FakeStorage:
    def __init__(self):
        self.objects: dict[str, bytes] = {}
        self.puts = 0

    def ensure_bucket(self):
        pass

    def put(self, key, data, content_type):
        self.puts += 1
        self.objects[key] = data

    def presigned_url(self, key, expires_s):
        return f"http://storage.test/{key}?expires={expires_s}"


def make_image(fmt: str = "PNG", size=(32, 32), color=(200, 30, 30)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format=fmt)
    return buf.getvalue()


@pytest.fixture
def fake_model():
    return FakeModel()


@pytest.fixture
def storage():
    return FakeStorage()


@pytest.fixture
def redis():
    return fakeredis.FakeAsyncRedis(decode_responses=True)


@pytest.fixture
def settings_overrides():
    """Override in a test module to change settings for its tests."""
    return {}


@pytest.fixture
def settings(tmp_path, settings_overrides):
    values = dict(
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'test.db').as_posix()}",
        admin_token=ADMIN_TOKEN,
        max_batch_wait_ms=1,
        log_json=False,
        log_level="WARNING",
    )
    values.update(settings_overrides)
    return Settings(_env_file=None, **values)


@pytest.fixture
async def app(settings, fake_model, storage, redis):
    app = create_app(settings, model_loader=lambda: fake_model, storage=storage, redis=redis)
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
