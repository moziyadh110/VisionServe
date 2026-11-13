from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz() -> dict:
    """Liveness: the process is up and the event loop answers. Nothing else."""
    return {"status": "ok"}


@router.get("/readyz")
async def readyz(request: Request) -> JSONResponse:
    """Readiness: can this instance serve traffic right now?

    Returns 503 while the model is still loading, so a load balancer can hold
    traffic back without restarting the process (that's liveness's job).
    """
    if request.app.state.model is None:
        return JSONResponse({"status": "loading", "model": False}, status_code=503)
    return JSONResponse({"status": "ready", "model": True})
