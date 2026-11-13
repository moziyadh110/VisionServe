import re
import time
import uuid

import structlog
from fastapi import Request

log = structlog.get_logger()

# Accept a caller's request id (e.g. from a load balancer) only if it looks sane,
# so nobody can inject junk into our logs.
_VALID_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


async def request_context(request: Request, call_next):
    """Give every request an id, attach it to all its logs, and echo it back.

    When a user reports a failure, the X-Request-ID header in their response finds
    every log line for that request.
    """
    incoming = request.headers.get("X-Request-ID", "")
    request_id = incoming if _VALID_ID.match(incoming) else uuid.uuid4().hex
    request.state.request_id = request_id

    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(request_id=request_id)

    start = time.perf_counter()
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    log.info(
        "request",
        method=request.method,
        path=request.url.path,
        status=response.status_code,
        duration_ms=round((time.perf_counter() - start) * 1000, 1),
    )
    return response
