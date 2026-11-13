import asyncio
import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.api import health, inference, requests, users
from app.config import Settings, get_settings
from app.db.session import make_engine
from app.ml.model import ImageModel

log = logging.getLogger("visionserve")


def _default_loader(settings: Settings) -> Callable[[], ImageModel]:
    def load() -> ImageModel:
        from app.ml.model import Florence2Model

        return Florence2Model.load(settings.model_id, settings.device, settings.max_new_tokens)

    return load


async def _load_model(app: FastAPI, loader: Callable[[], ImageModel]) -> None:
    """Load the model on the GPU thread, then flip /readyz to 200.

    Runs as a background task so the server starts answering /healthz immediately;
    /readyz and /v1/infer return 503 until this finishes.
    """
    loop = asyncio.get_running_loop()
    try:
        app.state.model = await loop.run_in_executor(app.state.gpu_executor, loader)
        log.info("model loaded")
    except Exception:
        log.exception("model failed to load; /readyz will stay 503")


def create_app(
    settings: Settings | None = None,
    model_loader: Callable[[], ImageModel] | None = None,
) -> FastAPI:
    """App factory: tests call this with their own settings and a fake model."""
    settings = settings or get_settings()
    loader = model_loader or _default_loader(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Startup: runs once per process, before the first request.
        app.state.settings = settings
        app.state.engine = make_engine(
            settings.database_url, settings.db_pool_size, settings.db_max_overflow
        )
        app.state.sessionmaker = async_sessionmaker(app.state.engine, expire_on_commit=False)
        # Exactly one thread ever touches the GPU, so model calls never overlap.
        app.state.gpu_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="gpu")
        app.state.model = None
        app.state.model_task = asyncio.create_task(_load_model(app, loader))
        yield
        # Shutdown.
        app.state.model_task.cancel()
        app.state.gpu_executor.shutdown(wait=False, cancel_futures=True)
        await app.state.engine.dispose()

    app = FastAPI(title="VisionServe", version="0.1.0", lifespan=lifespan)
    app.include_router(health.router)
    app.include_router(users.router)
    app.include_router(inference.router)
    app.include_router(requests.router)
    return app


logging.basicConfig(level=logging.INFO)
app = create_app()
