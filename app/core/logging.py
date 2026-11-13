"""Structured JSON logs.

Every log line is one JSON object, so a log system can filter on fields
(request_id=..., status=500) instead of grepping text. merge_contextvars adds
whatever the request middleware bound (request_id) to every line logged while
handling that request, without passing it around by hand.
"""

import logging

import structlog


def configure_logging(level: str = "INFO", json: bool = True) -> None:
    renderer = structlog.processors.JSONRenderer() if json else structlog.dev.ConsoleRenderer()
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.dict_tracebacks if json else structlog.dev.set_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelNamesMapping().get(level.upper(), logging.INFO)
        ),
        cache_logger_on_first_use=True,
    )
