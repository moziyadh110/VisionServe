import asyncio

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

router = APIRouter(tags=["health"])

CHECK_TIMEOUT_S = 1.0


@router.get("/healthz")
async def healthz() -> dict:
    """Liveness: the process is up and the event loop answers. Nothing else.

    It deliberately ignores Postgres/Redis: if they're down, restarting this
    process won't fix them, and an orchestrator acts on liveness by restarting.
    """
    return {"status": "ok"}


async def _check(coro) -> bool:
    try:
        await asyncio.wait_for(coro, CHECK_TIMEOUT_S)
        return True
    except Exception:
        return False


async def _ping_db(request: Request) -> None:
    async with request.app.state.engine.connect() as conn:
        await conn.execute(text("SELECT 1"))


@router.get("/readyz")
async def readyz(request: Request) -> JSONResponse:
    """Readiness: can this instance serve traffic right now?

    503 while the model loads or a dependency is unreachable, so a load balancer
    stops sending traffic here without restarting the process.
    """
    state = request.app.state
    checks = {
        "model": state.model is not None,
        "postgres": await _check(_ping_db(request)),
        "redis": await _check(state.redis.ping()),
    }
    ready = all(checks.values())
    return JSONResponse(
        {"status": "ready" if ready else "not_ready", "checks": checks},
        status_code=200 if ready else 503,
    )
