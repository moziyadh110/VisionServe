"""Result cache in Redis.

The key is built from everything that determines the output: the task, the model
version and the image's content hash. The same image uploaded by anyone, under any
filename, hits the same entry. Bumping model_version changes every key, so old
results are never served after a model upgrade (invalidation by versioning); they
just expire via their TTL.

Redis failures are logged and treated as a miss: the cache is an optimization, so
an outage should make requests slower, not fail them.
"""

import json

import structlog
from redis.asyncio import Redis
from redis.exceptions import RedisError

log = structlog.get_logger()


def cache_key(task: str, model_version: str, sha256: str) -> str:
    return f"infer:{task}:{model_version}:{sha256}"


async def get_cached(redis: Redis, key: str) -> str | None:
    try:
        raw = await redis.get(key)
    except RedisError as exc:
        log.warning("cache_get_failed", error=str(exc))
        return None
    return json.loads(raw)["text"] if raw else None


async def set_cached(redis: Redis, key: str, text: str, ttl_s: int) -> None:
    try:
        await redis.set(key, json.dumps({"text": text}), ex=ttl_s)
    except RedisError as exc:
        log.warning("cache_set_failed", error=str(exc))
