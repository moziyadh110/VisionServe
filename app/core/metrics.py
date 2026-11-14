"""Prometheus metrics, served at /metrics.

Prometheus scrapes this endpoint every few seconds and stores the numbers as time
series. Counters only go up (rates come from their slope); a histogram counts
observations into buckets, which is how p50/p95/p99 are computed without storing
every single latency. Labels must stay low-cardinality: route templates like
/v1/requests/{request_id}, never raw paths with ids in them.

Metrics live at module level because the Prometheus registry is process-global.
"""

from prometheus_client import Counter, Gauge, Histogram

HTTP_REQUESTS = Counter(
    "http_requests_total", "HTTP requests by route and status", ["method", "route", "status"]
)

INFERENCE_LATENCY = Histogram(
    "inference_latency_seconds",
    "Time from validated upload to result, per task",
    ["task", "cache"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
)

BATCH_SIZE = Histogram(
    "batch_size", "Images per GPU forward pass", buckets=(1, 2, 4, 8, 16, 32, 64)
)

CACHE_HITS = Counter("cache_hits_total", "Result cache hits", ["task"])
CACHE_MISSES = Counter("cache_misses_total", "Result cache misses", ["task"])

QUEUE_DEPTH = Gauge("queue_depth", "Requests waiting in the batch queue")
