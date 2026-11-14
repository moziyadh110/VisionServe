import asyncio
import contextlib
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.api import health, images, inference, metrics, requests, users
from app.config import Settings, get_settings
from app.core.errors import register_error_handlers
from app.core.logging import configure_logging
from app.core.metrics import QUEUE_DEPTH
from app.core.middleware import request_context
from app.core.rate_limit import RateLimiter
from app.db.session import make_engine
from app.ml.batcher import Batcher
from app.ml.model import ImageModel
from app.storage.s3 import ObjectStore, S3Storage

log = structlog.get_logger()


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
        log.info("model_loaded")
    except Exception:
        log.exception("model_load_failed")


async def _ensure_bucket(storage: ObjectStore) -> None:
    try:
        await asyncio.to_thread(storage.ensure_bucket)
    except Exception:
        log.exception("bucket_setup_failed")


def create_app(
    settings: Settings | None = None,
    model_loader: Callable[[], ImageModel] | None = None,
    storage: ObjectStore | None = None,
    redis: Redis | None = None,
) -> FastAPI:
    """App factory: tests pass their own settings, a fake model, storage and Redis."""
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.log_json)
    loader = model_loader or _default_loader(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Startup: runs once per process, before the first request.
        state = app.state
        state.settings = settings
        state.engine = make_engine(
            settings.database_url, settings.db_pool_size, settings.db_max_overflow
        )
        state.sessionmaker = async_sessionmaker(state.engine, expire_on_commit=False)
        redis_client = redis or Redis.from_url(settings.redis_url, decode_responses=True)
        state.redis = redis_client
        state.rate_limiter = RateLimiter(state.redis, settings.rate_limit_algorithm)
        state.storage = storage or S3Storage(settings)
        await _ensure_bucket(state.storage)

        # Exactly one thread ever touches the GPU, so model calls never overlap.
        state.gpu_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="gpu")
        state.model = None
        state.batcher = Batcher(
            # Look the model up at call time: it's still loading when the batcher starts.
            predict_batch=lambda imgs, task: state.model.predict_batch(imgs, task),
            executor=state.gpu_executor,
            max_batch=settings.max_batch_size,
            max_wait_ms=settings.max_batch_wait_ms,
            max_queue=settings.max_queue_size,
        )
        QUEUE_DEPTH.set_function(lambda: state.batcher.depth)  # read at scrape time
        state.batcher_task = asyncio.create_task(state.batcher.run())
        state.model_task = asyncio.create_task(_load_model(app, loader))
        yield

        # Shutdown.
        for task in (state.batcher_task, state.model_task):
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        state.gpu_executor.shutdown(wait=False, cancel_futures=True)
        await redis_client.aclose()
        await state.engine.dispose()

    app = FastAPI(title="VisionServe", version="0.1.0", lifespan=lifespan)
    app.middleware("http")(request_context)
    register_error_handlers(app)
    app.include_router(health.router)
    app.include_router(users.router)
    app.include_router(inference.router)
    app.include_router(requests.router)
    app.include_router(images.router)
    app.include_router(metrics.router)
    return app


app = create_app()
