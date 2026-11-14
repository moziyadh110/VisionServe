import asyncio
import time

import structlog
from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache.results import cache_key, get_cached, set_cached
from app.core.metrics import CACHE_HITS, CACHE_MISSES, INFERENCE_LATENCY
from app.core.rate_limit import rate_limited_user
from app.db.models import InferenceRequest, User
from app.db.queries import get_or_create_image
from app.db.session import get_session
from app.ml.batcher import QueueFull
from app.ml.images import read_upload
from app.schemas.inference import InferenceResponse, InferenceResult, Task

router = APIRouter(prefix="/v1", tags=["inference"])
log = structlog.get_logger()


def _ms_since(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)


async def _save(session: AsyncSession, **fields) -> InferenceRequest:
    row = InferenceRequest(**fields)
    session.add(row)
    await session.commit()
    return row


class StageTimer:
    """Measures each stage of the request path for the Server-Timing header.

    Server-Timing is a standard HTTP header (browsers show it in DevTools under
    Network -> Timing) that tells the client where the server spent its time,
    without changing the JSON response body.
    """

    def __init__(self):
        self.stages: dict[str, float] = {}
        self.descs: dict[str, str] = {}
        self._last = time.perf_counter()

    def mark(self, name: str) -> None:
        now = time.perf_counter()
        self.stages[name] = (now - self._last) * 1000
        self._last = now

    def add(self, name: str, ms: float, desc: str | None = None) -> None:
        self.stages[name] = ms
        if desc:
            self.descs[name] = desc

    def header(self) -> str:
        parts = []
        for name, ms in self.stages.items():
            desc = f';desc="{self.descs[name]}"' if name in self.descs else ""
            parts.append(f"{name};dur={ms:.1f}{desc}")
        return ", ".join(parts)


@router.post("/infer/{task}", response_model=InferenceResponse)
async def infer(
    task: Task,
    request: Request,
    response: Response,
    file: UploadFile = File(...),
    user: User = Depends(rate_limited_user),  # auth -> rate limit
    session: AsyncSession = Depends(get_session),
) -> InferenceResponse:
    """auth -> rate limit -> validate -> hash -> cache -> store image -> batch -> GPU
    -> cache write -> save row -> respond."""
    state = request.app.state
    settings = state.settings
    if state.model is None:
        raise HTTPException(503, "Model is still loading")

    # Copy plain values now: a rollback inside get_or_create_image expires ORM objects,
    # and touching an expired attribute in async code would try a hidden DB call.
    user_id = user.id
    timer = StageTimer()
    upload = await read_upload(file, settings.max_upload_bytes)
    timer.mark("decode")  # validate format, decode pixels, SHA-256
    start = time.perf_counter()

    key = cache_key(task.value, settings.model_version, upload.sha256)
    cached = await get_cached(state.redis, key) if settings.cache_enabled else None
    timer.mark("cache")
    image_id = (await get_or_create_image(session, state.storage, user_id, upload)).id
    # Commit now so the DB connection goes back to the pool while we wait on the GPU.
    # Holding a transaction open across inference would pin one pooled connection per
    # in-flight request and exhaust the pool long before the GPU is the bottleneck.
    await session.commit()
    timer.mark("store")
    base = dict(user_id=user_id, image_id=image_id, task=task.value)

    if cached is not None:
        CACHE_HITS.labels(task.value).inc()
        latency_ms = _ms_since(start)
        INFERENCE_LATENCY.labels(task.value, "hit").observe(latency_ms / 1000)
        row = await _save(
            session, **base, status="ok", cache_hit=True, latency_ms=latency_ms,
            result={"text": cached},
        )  # fmt: skip
        timer.mark("save")
        response.headers["Server-Timing"] = timer.header()
        return InferenceResponse(
            request_id=row.id,
            task=task,
            result=InferenceResult(text=cached),
            cache_hit=True,
            batch_size=None,
            latency_ms=latency_ms,
        )

    CACHE_MISSES.labels(task.value).inc()

    # The GPU work happens in the batcher's worker thread; this coroutine just
    # awaits its future, so the event loop stays free for other requests.
    try:
        out = await asyncio.wait_for(
            state.batcher.submit(upload.image, task), settings.inference_timeout_s
        )
    except QueueFull:
        raise HTTPException(
            503, "Server is overloaded, try again shortly", headers={"Retry-After": "1"}
        ) from None
    except TimeoutError:
        await _save(
            session, **base, status="timeout", latency_ms=_ms_since(start),
            error=f"timed out after {settings.inference_timeout_s}s",
        )  # fmt: skip
        raise HTTPException(504, "Inference timed out") from None
    except Exception as exc:
        log.exception("inference_failed", task=task.value)
        await _save(
            session, **base, status="error", latency_ms=_ms_since(start), error=str(exc)[:500]
        )
        raise HTTPException(500, "Inference failed") from exc
    timer.mark("batch")
    # Split the batcher's share into its two parts: waiting for companions vs the GPU.
    del timer.stages["batch"]
    timer.add("queue", out.queue_ms)
    timer.add("gpu", out.gpu_ms, desc=f"batch-{out.batch_id}")

    if settings.cache_enabled:
        await set_cached(state.redis, key, out.text, settings.cache_ttl_s)
    latency_ms = _ms_since(start)
    INFERENCE_LATENCY.labels(task.value, "miss").observe(latency_ms / 1000)
    row = await _save(
        session, **base, status="ok", cache_hit=False, batch_size=out.batch_size,
        latency_ms=latency_ms, result={"text": out.text},
    )  # fmt: skip
    timer.mark("save")
    response.headers["Server-Timing"] = timer.header()
    return InferenceResponse(
        request_id=row.id,
        task=task,
        result=InferenceResult(text=out.text),
        cache_hit=False,
        batch_size=out.batch_size,
        latency_ms=latency_ms,
    )
