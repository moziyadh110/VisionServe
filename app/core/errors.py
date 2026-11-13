"""One error format for every failure:

    {"error": {"code": "rate_limited", "message": "...", "request_id": "..."}}

Clients branch on `code` (stable) rather than parsing `message` (for humans).
"""

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = structlog.get_logger()

ERROR_CODES = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    413: "payload_too_large",
    415: "unsupported_media_type",
    422: "validation_error",
    429: "rate_limited",
    500: "internal_error",
    503: "unavailable",
    504: "timeout",
}


def error_response(
    request: Request, status: int, message: str, headers: dict | None = None
) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None)
    body = {
        "error": {
            "code": ERROR_CODES.get(status, "error"),
            "message": message,
            "request_id": request_id,
        }
    }
    response = JSONResponse(body, status_code=status, headers=headers)
    if request_id:
        response.headers["X-Request-ID"] = request_id
    return response


async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    return error_response(request, exc.status_code, str(exc.detail), exc.headers)


async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    message = "; ".join(
        f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in exc.errors()
    )
    return error_response(request, 422, message)


async def _unhandled_error(request: Request, exc: Exception) -> JSONResponse:
    # Log the real cause; never send stack traces or internals to the client.
    log.error("unhandled_error", exc_info=exc)
    return error_response(request, 500, "Internal server error")


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(Exception, _unhandled_error)
