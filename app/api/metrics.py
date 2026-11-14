from fastapi import APIRouter
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

router = APIRouter(tags=["health"])


@router.get("/metrics", include_in_schema=False)
async def metrics() -> Response:
    """Prometheus text format. Internal only: block it at the reverse proxy in production."""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
